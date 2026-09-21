"""Validated settings shared by the native UI and HTTP API."""
import threading
from storage import atomic_json, read_json, regular_open

DEFAULTS = {"image_seconds": 5, "repeats": 3, "order": "ordered", "loop": True,
            "convert_gifs": False}
LEGACY = {"image_seconds", "repeats", "order", "loop"}


def validate(data):
    if not isinstance(data, dict) or set(data) not in (LEGACY, set(DEFAULTS)):
        raise ValueError("Settings require image_seconds, repeats, order, loop and convert_gifs")
    if type(data["image_seconds"]) is not int or not 1 <= data["image_seconds"] <= 3600:
        raise ValueError("Still image duration must be 1–3600 whole seconds")
    if type(data["repeats"]) is not int or not 1 <= data["repeats"] <= 100:
        raise ValueError("Animated/video repeats must be 1–100")
    if data["order"] not in ("ordered", "shuffle") or type(data["loop"]) is not bool:
        raise ValueError("Invalid playback order or end-of-folder setting")
    if type(data.get("convert_gifs", False)) is not bool:
        raise ValueError("Convert uploads to WebP must be on or off")
    value = dict(data)
    value.setdefault("convert_gifs", False)
    return value


class Settings:
    def __init__(self, directory):
        self.path = directory / "settings.json"
        self.lock = threading.RLock()
        self.warning = ""
        try:
            self.data = validate(read_json(self.path, 4096))
        except FileNotFoundError:
            self.data = dict(DEFAULTS)
        except (OSError, ValueError, RecursionError):
            self.data = dict(DEFAULTS)
            self.warning = "Settings unreadable; using defaults. Save settings to replace them."

    def snapshot(self):
        with self.lock:
            return dict(self.data)

    def save(self, data):
        value = validate(data)
        with self.lock:
            if self.path.exists() or self.path.is_symlink():
                with regular_open(self.path, 4096):
                    pass
            if value != self.data or self.warning or not self.path.exists():
                warning = atomic_json(self.path, value, 4096)
                self.data = value
                self.warning = warning
        return value
