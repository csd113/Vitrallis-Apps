"""Validated launcher Documents/AppData and XDG caches; no package-local writes."""
import json
import os
from pathlib import Path
import stat
import tempfile


def validate_path(value, package=None):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Storage requires an absolute path without traversal')
    package = Path(__file__).resolve().parent if package is None else Path(package).resolve()
    if path == package or package in path.parents:
        raise ValueError('Storage must be outside the installed package')
    for part in reversed((path, *path.parents)):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ValueError('Symbolic links are not writable storage')
        if part != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError('Storage ancestor is not a directory')
    return path


def directory(path):
    path = validate_path(path)
    missing = []
    ancestor = path
    while not ancestor.exists():
        missing.append(ancestor)
        ancestor = ancestor.parent
    for component in reversed(missing):
        try:
            component.mkdir(mode=0o700)
        except FileExistsError:
            validate_path(component)
            if not component.is_dir():
                raise ValueError('Storage is not a directory')
    if not path.is_dir():
        raise ValueError('Storage is not a directory')
    return path


class Paths:
    def __init__(self, app_id, env=None):
        env = os.environ if env is None else env
        home = env.get('HOME', str(Path.home()))
        exported_id = env.get('VITRALLIS_APP_ID')
        if exported_id and exported_id != app_id:
            raise ValueError('Launcher identity does not match this app')
        self.data = validate_path(env.get('VITRALLIS_APP_DATA_DIR', home + '/Documents/Vitrallis/AppData/' + app_id))
        self.documents = validate_path(env.get('VITRALLIS_DOCUMENTS_DIR', str(self.data / 'Documents')))
        self.state = self.data / 'config'
        self.cache = validate_path(env.get('XDG_CACHE_HOME', home + '/.cache')) / app_id
        for path in (self.data, self.documents, self.state, self.cache):
            validate_path(path)
        # Construction has no filesystem side effects. Create only when needed.


def atomic_write(path, writer):
    path = validate_path(path)
    directory(path.parent)
    if path.exists() and not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Output must be a regular file')
    fd, name = tempfile.mkstemp(prefix='.saving-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        try:
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError:
            # The rename has committed. Report its uncertain durability instead
            # of claiming the old content survived a failed save.
            return 'Saved; power-loss durability is uncertain'
        return ''
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_state(path):
    try:
        path = validate_path(path)
        if path.stat().st_size > 16384 or not path.is_file():
            return {}
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(path, state):
    return atomic_write(path, lambda stream: stream.write(json.dumps(state, allow_nan=False).encode()))
