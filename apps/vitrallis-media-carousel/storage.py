"""Current XDG storage assumption, strict POSIX paths and durable JSON writes."""
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile

APP_ID = "io.vitrallis.mediacarousel"


def safe_directory(path, private=False):
    raw = os.fspath(path)
    if not raw.startswith("/") or ".." in raw.split("/") or "\x00" in raw:
        raise ValueError("Storage paths must be absolute and contain no traversal")
    path = Path(raw)
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        info = current.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("Storage path contains a link or non-directory")
    if private:
        info = path.lstat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("App storage must be owned by this user with mode 0700")
    return path


def make_private(path):
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        make_private(path.parent)
        path.mkdir(mode=0o700)
    return safe_directory(path)


def regular_open(path, limit):
    path = Path(path)
    safe_directory(path.parent, private=True)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.getuid() or info.st_size > limit):
            raise ValueError("Unsafe or oversized data file")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def read_json(path, limit):
    with regular_open(path, limit) as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Metadata too large")
    return json.loads(raw, object_pairs_hook=unique_keys,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Invalid number")))


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, data, limit):
    path = Path(path)
    safe_directory(path.parent, private=True)
    payload = (json.dumps(data, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    if len(payload) > limit:
        raise ValueError("Metadata capacity reached")
    if path.exists() or path.is_symlink():
        with regular_open(path, limit):
            pass
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            sync_directory(path.parent)
        except OSError:
            # Rename has committed already. Callers must keep memory aligned with
            # that committed document and surface the durability warning.
            return "Saved, but directory sync failed; durability after power loss is uncertain."
        return ""
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


class Paths:
    def __init__(self, environ=None):
        env = os.environ if environ is None else environ
        home = env.get("HOME", str(Path.home()))
        safe_directory(home)
        self.config = self._root(env.get("XDG_CONFIG_HOME", home + "/.config"))
        self.data = self._root(env.get("XDG_DATA_HOME", home + "/.local/share"))
        self.cache = self._root(env.get("XDG_CACHE_HOME", home + "/.cache"))
        self.media = self.data / "media"
        self.uploads = self.data / "uploads"
        directories = (self.config, self.data, self.cache, self.media, self.uploads)
        # Validate every configured path before creating any directory.
        for path in directories:
            ancestor = path
            while not ancestor.exists() and not ancestor.is_symlink():
                ancestor = ancestor.parent
            safe_directory(ancestor, private=ancestor == path)
        for path in directories:
            make_private(path)
            safe_directory(path, private=True)

    @staticmethod
    def _root(base):
        if not base.startswith("/") or ".." in base.split("/"):
            raise ValueError("Invalid XDG storage location")
        path = Path(base) / APP_ID
        package = Path(__file__).resolve().parent
        if path == package or package in path.parents:
            raise ValueError("Storage must be outside the installed app package")
        return path


class InstanceLock:
    """One metadata owner; never truncate a lock another instance may hold."""
    def __init__(self, directory):
        safe_directory(directory, private=True)
        self.fd = os.open(Path(directory) / "instance.lock",
                          os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(self.fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
                raise ValueError("Unsafe instance lock")
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self.fd)
            self.fd = None
            raise

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
