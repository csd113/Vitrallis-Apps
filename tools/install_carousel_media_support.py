#!/usr/bin/env python3
"""Administrator setup for Carousel's fixed, no-argument multimedia action.

Run during device/platform installation, never from an unprivileged app startup.
"""
import argparse
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import tempfile

HELPER = b'''#!/bin/sh
# Managed by Vitrallis Media Carousel platform setup.
set -eu
[ "$#" -eq 0 ] || exit 64
[ "$(/usr/bin/id -u)" -eq 0 ] || exit 77
[ -f /etc/debian_version ] || exit 69
exec /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C DEBIAN_FRONTEND=noninteractive /usr/bin/apt-get --no-install-recommends --no-remove -y install ffmpeg
'''


def policy(username):
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', username):
        raise ValueError('Invalid local account name')
    return (f'# Managed by Vitrallis Media Carousel platform setup.\n'
            f'{username} ALL=(root) NOPASSWD: /usr/local/libexec/vitrallis-carousel-install-media ""\n').encode()


def secure(path, directory=False):
    for parent in reversed((path, *path.parents)):
        info = parent.lstat()
        if (info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode)
                or (parent != path or directory) and not stat.S_ISDIR(info.st_mode)):
            raise ValueError(f'Unsafe root-owned setup path: {parent}')


def replace(path, data, mode):
    secure(path.parent, True)
    if path.exists() or path.is_symlink():
        secure(path)
        if not path.is_file():
            raise ValueError(f'Expected regular managed file: {path}')
        if b'# Managed by Vitrallis Media Carousel platform setup.' not in path.read_bytes()[:200]:
            raise ValueError(f'Refusing to replace an unmanaged file: {path}')
    fd, temporary = tempfile.mkstemp(prefix='.carousel-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install(username):
    rules = policy(username)
    account = pwd.getpwnam(username)
    if account.pw_uid < 1000 or os.geteuid() != 0:
        raise ValueError('Run as root for a normal desktop account')
    if not Path('/etc/debian_version').is_file():
        raise ValueError('Multimedia setup supports Debian-based systems')
    helper = Path('/usr/local/libexec/vitrallis-carousel-install-media')
    sudoers = Path('/etc/sudoers.d') / ('vitrallis-carousel-media-' + username)
    for directory in (helper.parent, sudoers.parent):
        if not directory.exists():
            secure(directory.parent, True)
            directory.mkdir(mode=0o755)
        secure(directory, True)
    with tempfile.NamedTemporaryFile(prefix='.carousel-check-', dir=sudoers.parent) as check:
        check.write(rules); check.flush()
        subprocess.run(['/usr/sbin/visudo', '-cf', check.name], check=True)
    # Validate both destination files before mutation. Install the fixed helper
    # before enabling its rule; a failed rule write grants no new privilege.
    for path in (helper, sudoers):
        if path.exists() or path.is_symlink():
            secure(path)
            if not path.is_file() or b'# Managed by Vitrallis Media Carousel platform setup.' not in path.read_bytes()[:200]:
                raise ValueError(f'Refusing unmanaged destination: {path}')
    replace(helper, HELPER, 0o755)
    replace(sudoers, rules, 0o440)
    print('Carousel multimedia installation enabled for ' + username)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user', required=True)
    args = parser.parse_args()
    try:
        install(args.user)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + '\n')
