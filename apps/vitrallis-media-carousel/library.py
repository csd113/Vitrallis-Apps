"""A bounded, transactional logical library; names never become storage paths."""
import copy
import os
from pathlib import Path
import re
import tempfile
import threading
import unicodedata
import uuid

from media import MAX_UPLOAD
from storage import atomic_json, read_json, regular_open, safe_directory, sync_directory

MAX_METADATA = 2 * 1024 * 1024
MAX_COLLECTIONS = 100
MAX_ITEMS = 2000
ID_PATTERN = re.compile(r"[a-f0-9]{32}\Z")


def identifier(value):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError("Invalid internal ID")
    return value


def display_name(value, maximum=64):
    if not isinstance(value, str):
        raise ValueError("Name must be text")
    value = unicodedata.normalize("NFC", value).strip()
    if (not 1 <= len(value) <= maximum or value in (".", "..") or ".." in value
            or any(ch in "/\\:" or unicodedata.category(ch).startswith("C") for ch in value)):
        raise ValueError("Use a short name without paths, control characters, colon or '..'")
    return value


def new_collection(name):
    return {"id": uuid.uuid4().hex, "name": name, "items": []}


def validate_metadata(data):
    if not isinstance(data, dict) or set(data) != {"version", "collections"} or type(data["version"]) is not int or data["version"] != 1:
        raise ValueError("Invalid library metadata")
    rows = data["collections"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_COLLECTIONS:
        raise ValueError("Invalid collection list")
    ids, names, total = set(), set(), 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "name", "items"}:
            raise ValueError("Invalid collection")
        cid, name = identifier(row["id"]), display_name(row["name"])
        if cid in ids or name.casefold() in names or name != row["name"]:
            raise ValueError("Duplicate collection")
        ids.add(cid)
        names.add(name.casefold())
        if not isinstance(row["items"], list):
            raise ValueError("Invalid media list")
        for item in row["items"]:
            if (not isinstance(item, dict)
                    or set(item) not in ({"id", "name", "kind", "size"},
                                         {"id", "name", "kind", "size", "animated"})):
                raise ValueError("Invalid media entry")
            mid = identifier(item["id"])
            if mid in ids or display_name(item["name"], 160) != item["name"]:
                raise ValueError("Invalid or duplicate media ID/name")
            ids.add(mid)
            if item["kind"] not in ("png", "jpeg", "webp", "gif", "webm"):
                raise ValueError("Invalid media kind")
            if type(item["size"]) is not int or not 1 <= item["size"] <= MAX_UPLOAD:
                raise ValueError("Invalid media size")
            if type(item.get("animated", item["kind"] in ("gif", "webm"))) is not bool:
                raise ValueError("Invalid animation flag")
            # Legacy entries predate animated WebP; only GIF and WebM were animated.
            item["animated"] = item.get("animated", item["kind"] in ("gif", "webm"))
            total += 1
    if total > MAX_ITEMS:
        raise ValueError("Library capacity reached")
    return data


class Library:
    def __init__(self, paths):
        self.paths = paths
        self.path = paths.data / "library.json"
        self.lock = threading.RLock()
        self.revision = 0
        self.warning = ""
        try:
            self.data = validate_metadata(read_json(self.path, MAX_METADATA))
        except FileNotFoundError:
            self.data = {"version": 1, "collections": [new_collection("Unsorted")]}
            self.warning = atomic_json(self.path, self.data, MAX_METADATA)
        # Corrupt library metadata is never silently replaced. Preserve it for repair.
        self.cleanup()

    def cleanup(self):
        live = {item["id"] for row in self.data["collections"] for item in row["items"]}
        for directory in (self.paths.media, self.paths.uploads):
            safe_directory(directory, private=True)
            for path in directory.iterdir():
                if directory == self.paths.media and path.name in live:
                    continue
                if ((directory == self.paths.media and ID_PATTERN.fullmatch(path.name))
                        or (directory == self.paths.uploads
                            and path.name.startswith(("upload-", "convert-")))):
                    with regular_open(path, MAX_UPLOAD):
                        pass
                    path.unlink()
            sync_directory(directory)

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.data["collections"])

    @staticmethod
    def collection(data, cid):
        identifier(cid)
        for row in data["collections"]:
            if row["id"] == cid:
                return row
        raise KeyError("Collection no longer exists")

    def _commit(self, data):
        validate_metadata(data)
        self.warning = atomic_json(self.path, data, MAX_METADATA)
        self.data = data
        self.revision += 1

    def create(self, name):
        name = display_name(name)
        with self.lock:
            data = copy.deepcopy(self.data)
            if any(row["name"].casefold() == name.casefold() for row in data["collections"]):
                raise ValueError("A collection with that name already exists")
            row = new_collection(name)
            data["collections"].append(row)
            self._commit(data)
            return copy.deepcopy(row)

    def rename(self, cid, name):
        name = display_name(name)
        with self.lock:
            data = copy.deepcopy(self.data)
            if any(row["id"] != cid and row["name"].casefold() == name.casefold() for row in data["collections"]):
                raise ValueError("A collection with that name already exists")
            self.collection(data, cid)["name"] = name
            self._commit(data)

    def reorder(self, cid, ids):
        with self.lock:
            data = copy.deepcopy(self.data)
            row = self.collection(data, cid)
            items = {item["id"]: item for item in row["items"]}
            if (not isinstance(ids, list) or not all(isinstance(mid, str) for mid in ids)
                    or len(ids) != len(items) or set(ids) != set(items)):
                raise ValueError("Ordering changed; refresh and include each media ID exactly once")
            row["items"] = [items[mid] for mid in ids]
            self._commit(data)

    def delete(self, cid, mid=None):
        with self.lock:
            data = copy.deepcopy(self.data)
            row = self.collection(data, cid)
            doomed = row["items"] if mid is None else [item for item in row["items"] if item["id"] == identifier(mid)]
            if mid is not None and not doomed:
                raise KeyError("Media no longer exists")
            for item in doomed:
                try:
                    with self.open_item(item):
                        pass
                except FileNotFoundError:
                    pass  # A previously removed file can still be removed from the index.
            if mid is None:
                data["collections"].remove(row)
                if not data["collections"]:
                    data["collections"].append(new_collection("Unsorted"))
            else:
                row["items"] = [item for item in row["items"] if item["id"] != mid]
            # Commit logical deletion before reclaiming bytes. Interruption can leave
            # unreachable blobs, never metadata pointing at half a deletion operation.
            self._commit(data)
            try:
                for item in doomed:
                    path = self.paths.media / item["id"]
                    try:
                        with regular_open(path, MAX_UPLOAD):
                            pass
                        path.unlink()
                    except FileNotFoundError:
                        pass
                sync_directory(self.paths.media)
            except (OSError, ValueError):
                self.warning = "Deletion saved; unused file cleanup failed. Check storage and restart."

    def temporary_upload(self):
        safe_directory(self.paths.uploads, private=True)
        fd, name = tempfile.mkstemp(prefix="upload-", dir=self.paths.uploads)
        return os.fdopen(fd, "wb"), Path(name)

    def add_upload(self, cid, name, temporary, info):
        name = display_name(name, 160)
        if temporary.parent != self.paths.uploads or not temporary.name.startswith("upload-"):
            raise ValueError("Invalid upload staging path")
        with regular_open(temporary, MAX_UPLOAD) as stream:
            size = os.fstat(stream.fileno()).st_size
        with self.lock:
            data = copy.deepcopy(self.data)
            row = self.collection(data, cid)
            item = {"id": uuid.uuid4().hex, "name": name, "kind": info["kind"], "size": size,
                    "animated": bool(info.get("animated", info["kind"] in ("gif", "webm")))}
            row["items"].append(item)
            validate_metadata(data)
            safe_directory(self.paths.media, private=True)
            destination = self.paths.media / item["id"]
            if destination.exists() or destination.is_symlink():
                raise ValueError("Media ID collision")
            os.replace(temporary, destination)
            try:
                sync_directory(self.paths.media)
                self._commit(data)
            except BaseException:
                destination.unlink()
                sync_directory(self.paths.media)
                raise
            return dict(item)

    def replace_upload(self, cid, mid, name, temporary, info):
        """Atomically substitute an item in place, then reclaim the old blob."""
        name = display_name(name, 160)
        if (temporary.parent != self.paths.uploads
                or not temporary.name.startswith(("upload-", "convert-"))):
            raise ValueError("Invalid upload staging path")
        with regular_open(temporary, MAX_UPLOAD) as stream:
            size = os.fstat(stream.fileno()).st_size
        with self.lock:
            data = copy.deepcopy(self.data)
            row = self.collection(data, cid)
            mid = identifier(mid)
            index = next((position for position, item in enumerate(row["items"])
                          if item["id"] == mid), None)
            if index is None:
                raise KeyError("Media no longer exists")
            doomed = row["items"][index]
            item = {"id": uuid.uuid4().hex, "name": name, "kind": info["kind"], "size": size,
                    "animated": bool(info.get("animated", info["kind"] in ("gif", "webm")))}
            row["items"][index] = item
            validate_metadata(data)
            safe_directory(self.paths.media, private=True)
            destination = self.paths.media / item["id"]
            if destination.exists() or destination.is_symlink():
                raise ValueError("Media ID collision")
            os.replace(temporary, destination)
            try:
                sync_directory(self.paths.media)
                self._commit(data)
            except BaseException:
                destination.unlink()
                sync_directory(self.paths.media)
                raise
            # The index now names the replacement. Reclaiming the old blob can fail
            # without making metadata point at bytes that are still being written.
            try:
                path = self.paths.media / doomed["id"]
                try:
                    with regular_open(path, MAX_UPLOAD):
                        pass
                    path.unlink()
                except FileNotFoundError:
                    pass
                sync_directory(self.paths.media)
            except (OSError, ValueError):
                self.warning = "Replacement saved; old file cleanup failed. Check storage and restart."
            return dict(item)

    def playlist(self, cid):
        with self.lock:
            return copy.deepcopy(self.collection(self.data, cid)["items"])

    def open_item(self, item):
        return regular_open(self.paths.media / identifier(item["id"]), MAX_UPLOAD)
