"""One cancellable worker prepares a rolling window of complete animations in RAM.

The animation on screen is streamed by the decoder itself, which records it here
as it plays back. The worker only prepares *later* animations, so preparation can
never delay the frame that is about to be shown, and it steps aside entirely
while the decoder is streaming the foreground item on a single-core device.
"""
import threading
from collections import OrderedDict
from PIL import Image

WINDOW = 10
TOTAL_BYTES = 32 * 1024 * 1024
WORKER_YIELD = 0.002
NO_ROOM = object()


def total_bytes():
    """Read the module budget dynamically so tests and operators can bound it."""
    return TOTAL_BYTES


def animated(item):
    return (item.get("kind") in ("gif", "webp")
            and item.get("animated", item.get("kind") == "gif"))


class AnimationCache:
    def __init__(self, frames, per_animation_limit, total_limit=total_bytes):
        self.frames = frames
        self.per_animation_limit = per_animation_limit
        self.total_limit = total_limit
        self.condition = threading.Condition()
        self.plan = {}
        self.order = []
        self.entries = OrderedDict()
        # Keys already resolved for this plan window: prepared, or tried and found
        # not to fit. Without this an evicted animation would be decoded again on
        # every worker pass, which is exactly the busy work the cache exists to stop.
        self.settled = set()
        self.foreground = None
        self.active = None
        self.busy = 0
        self.closed = False
        self.thread = threading.Thread(target=self._work, name="carousel-animation-cache")
        self.thread.start()

    @staticmethod
    def key(item, size, gpu):
        return (item["id"], item["size"], tuple(size), gpu)

    # ---- planning -------------------------------------------------------

    def budget(self):
        return self.per_animation_limit()

    def update(self, items, size, gpu):
        """Replan the rolling window; drop entries that can never be reached again."""
        plan, order = {}, []
        for item in items:
            if animated(item):
                key = self.key(item, size, gpu)
                if key not in plan:
                    plan[key] = dict(item)
                    order.append(key)
                if len(order) == WINDOW:
                    break
        foreground = self.key(items[0], size, gpu) if items and animated(items[0]) else None
        with self.condition:
            self.plan, self.order, self.foreground = plan, order, foreground
            for key in list(self.entries):
                if key not in plan:
                    del self.entries[key]
            self.settled = {key for key in self.settled if key in plan}
            self._evict()
            active = self.active
            if active is not None and (active[0] not in plan or active[0] == foreground):
                active[1].set()
            self.condition.notify_all()

    def take(self, item, size, gpu):
        """Prepared frames for this item, or None. Never blocks."""
        key = self.key(item, size, gpu)
        with self.condition:
            entry = self.entries.get(key)
            if entry is None:
                return None
            self.entries.move_to_end(key)
            frames, _ = entry
        return None if frames is NO_ROOM else frames

    def store(self, item, size, gpu, frames, used):
        """Publish an animation the decoder just streamed."""
        if not frames:
            return
        key = self.key(item, size, gpu)
        with self.condition:
            if key not in self.plan:
                return
            self.entries.pop(key, None)
            self.entries[key] = (frames, used)
            self.settled.add(key)
            self._evict()
            self.condition.notify_all()

    def skip(self, item, size, gpu):
        """Remember that this animation does not fit, so it is not decoded twice."""
        key = self.key(item, size, gpu)
        with self.condition:
            self.settled.add(key)
            self.entries.pop(key, None)
            self.condition.notify_all()

    def foreground_busy(self, value):
        """Ask the prefetch worker to step aside while the decoder streams."""
        with self.condition:
            self.busy = max(0, self.busy + (1 if value else -1))
            self.condition.notify_all()

    # ---- internals ------------------------------------------------------

    def _used(self):
        return sum(entry[1] for entry in self.entries.values())

    def _drop_furthest(self):
        """Remove the furthest, then the least recently used, non-foreground entry."""
        for key in reversed(self.order):
            if key in self.entries and key != self.foreground:
                del self.entries[key]
                return True
        for key in self.entries:
            if key != self.foreground:
                del self.entries[key]
                return True
        return False

    def _evict(self):
        limit = self.total_limit()
        while self.entries and self._used() > limit:
            if not self._drop_furthest():
                return

    def _reserve(self):
        """Room for one more animation, evicting whole distant entries if needed.

        Reserving up front keeps the per-animation allowance meaningful: an
        animation that still does not fit is genuinely too large and is not
        decoded again on every visit.
        """
        allowance = min(self.per_animation_limit(), self.total_limit())
        if allowance <= 0:
            return 0
        while self.entries and self.total_limit() - self._used() < allowance:
            if not self._drop_furthest():
                break
        return min(allowance, max(0, self.total_limit() - self._used()))

    def _next_key(self):
        for key in self.order:
            if (key != self.foreground and key not in self.entries
                    and key not in self.settled):
                return key
        return None

    def _step_aside(self, cancel):
        """Yield the queue, and wait while the foreground is being streamed."""
        if self.busy:
            with self.condition:
                while self.busy and not self.closed and not cancel.is_set():
                    self.condition.wait(0.05)
            return cancel.is_set()
        return cancel.wait(WORKER_YIELD)

    def _work(self):
        while True:
            with self.condition:
                key = self._next_key()
                while key is None and not self.closed:
                    self.condition.wait()
                    key = self._next_key()
                if self.closed:
                    return
                item = self.plan[key]
                limit = self._reserve()
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
                        used += len(frame.pixels)
                        if used > limit:
                            frames, used = NO_ROOM, 0
                            break
                        frames.append((frame, seconds))
                        if self._step_aside(cancel):
                            break
            except (OSError, ValueError, EOFError, SyntaxError, Image.DecompressionBombError):
                # Foreground streaming reports the original media error normally.
                # Settle the key as unfittable: a corrupt blob must not be decoded
                # again on every worker pass while the playlist sits on a still item.
                frames, used = NO_ROOM, 0
            with self.condition:
                if not cancel.is_set() and key in self.plan and frames is not None:
                    self.settled.add(key)
                    if frames and frames is not NO_ROOM:
                        self.entries[key] = (frames, used)
                        self._evict()
                self.active = None
                self.condition.notify_all()
            # Release local references before reserving the next job's memory.
            frames = None

    def clear(self):
        """Forget every plan; preparation stops until the next update()."""
        with self.condition:
            self.plan = {}
            self.order = []
            self.entries.clear()
            self.settled.clear()
            if self.active:
                self.active[1].set()
            self.condition.notify_all()

    def close(self):
        with self.condition:
            self.closed = True
            self.plan.clear()
            self.order = []
            self.entries.clear()
            if self.active:
                self.active[1].set()
            self.condition.notify_all()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            raise RuntimeError("Animation cache worker did not stop within 3 seconds")
