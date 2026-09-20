"""One cancellable worker prepares a rolling window of complete GIFs in RAM."""
import threading
from PIL import Image

WINDOW = 10
TOTAL_BYTES = 32 * 1024 * 1024
NO_ROOM = object()


class GifCache:
    def __init__(self, frames, per_gif_limit):
        self.frames = frames
        self.per_gif_limit = per_gif_limit
        self.condition = threading.Condition()
        self.plan = {}
        self.entries = {}
        self.foreground = None
        self.active = None
        self.closed = False
        self.thread = threading.Thread(target=self._work, name="carousel-gif-cache")
        self.thread.start()

    @staticmethod
    def key(item, size, gpu):
        return (item["id"], item["size"], tuple(size), gpu)

    def update(self, items, size, gpu):
        plan = {}
        for item in items:
            if item["kind"] == "gif":
                plan[self.key(item, size, gpu)] = dict(item)
                if len(plan) == WINDOW:
                    break
        foreground = self.key(items[0], size, gpu) if items and items[0]["kind"] == "gif" else None
        with self.condition:
            self.plan, self.foreground = plan, foreground
            self.entries = {key: entry for key, entry in self.entries.items()
                            if key in plan and entry[0] is not NO_ROOM}
            missing = foreground is not None and foreground not in self.entries
            if self.active and (self.active[0] not in plan or
                                (missing and (self.active[0] != foreground or
                                              self.active[2] < self.per_gif_limit()))):
                self.active[1].set()
            if missing:
                # Foreground preparation gets a full per-GIF allowance.
                for key in reversed(plan):
                    if self._used() <= TOTAL_BYTES - self.per_gif_limit():
                        break
                    self.entries.pop(key, None)
            self.condition.notify_all()

    def _used(self):
        return sum(entry[1] for entry in self.entries.values())

    def wait(self, item, size, gpu, cancel):
        key = self.key(item, size, gpu)
        with self.condition:
            while not self.closed and not cancel.is_set():
                if key not in self.plan:
                    return None
                if key in self.entries:
                    value = self.entries[key][0]
                    return None if value is NO_ROOM else value
                self.condition.wait(.05)
        return None

    def _work(self):
        while True:
            with self.condition:
                key = next((key for key in self.plan if key not in self.entries), None)
                while key is None and not self.closed:
                    self.condition.wait()
                    key = next((key for key in self.plan if key not in self.entries), None)
                if self.closed:
                    return
                item = self.plan[key]
                limit = min(self.per_gif_limit(), max(0, TOTAL_BYTES - self._used()))
                cancel = threading.Event()
                self.active = (key, cancel, limit)
            frames, used = [], 0
            try:
                if limit == 0:
                    frames = NO_ROOM
                else:
                    for frame, seconds in self.frames(item, key[2], key[3], cancel):
                        if cancel.is_set():
                            break
                        used += frame.width * frame.height * 4
                        if used > limit:
                            frames = NO_ROOM if limit < self.per_gif_limit() else None
                            used = 0
                            break
                        frames.append((frame, seconds))
                        with self.condition:
                            background = key != self.foreground
                        if background and cancel.wait(.01):
                            break
            except (OSError, ValueError, EOFError, SyntaxError, Image.DecompressionBombError):
                # Foreground streaming reports the original media error normally.
                frames, used = None, 0
            with self.condition:
                if not cancel.is_set() and key in self.plan:
                    self.entries[key] = (frames, used)
                self.active = None
                self.condition.notify_all()
            # Release local references before reserving the next job's memory.
            frames = None

    def clear(self):
        self.update([], (1, 1), False)

    def close(self):
        with self.condition:
            self.closed = True
            self.plan.clear()
            self.entries.clear()
            if self.active:
                self.active[1].set()
            self.condition.notify_all()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            raise RuntimeError("GIF cache worker did not stop within 3 seconds")
