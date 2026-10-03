"""Validate persistent storage before reading or creating user files."""
import os
from pathlib import Path
import stat


def private_parent(path, create=True):
    path = Path(path)
    raw = os.fspath(path)
    if (not path.is_absolute() or '..' in path.parts
            or any(ord(char) < 32 or ord(char) == 127 for char in raw)):
        raise OSError('Invalid application data path')
    package = Path(__file__).resolve().parent
    if path == package or package in path.parents:
        raise OSError('Application data must be outside its package')
    # Validate the complete existing path before any directory creation.
    for parent in path.parents:
        try:
            info = parent.lstat()
        except FileNotFoundError:
            continue
        if (not stat.S_ISDIR(info.st_mode)
                or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX)):
            raise OSError('Unsafe application data directory')
    try:
        info = path.lstat()
    except FileNotFoundError:
        pass
    else:
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.getuid()):
            raise OSError('Unsafe application data file')
    missing = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    if missing and not create:
        raise FileNotFoundError('Application data directory does not exist')
    for parent in reversed(missing):
        parent.mkdir(mode=0o700)
    info = path.parent.lstat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise OSError('Application data directory must be private to this user')
    return path.parent
