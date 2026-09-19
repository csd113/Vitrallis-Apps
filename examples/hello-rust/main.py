#!/usr/bin/env python3
"""Experimental native payload supervisor for the existing manifest v1 launcher."""
import os
from pathlib import Path
import platform
import signal
import stat
import struct
import subprocess
import sys

# Closed deployment targets, not user-controlled paths or shell fragments.
TARGETS = {
    ('Linux', 'armv7l'): ('armv7-unknown-linux-gnueabihf', 1, 40),
    ('Linux', 'aarch64'): ('aarch64-unknown-linux-gnu', 2, 183),
    ('Linux', 'x86_64'): ('x86_64-unknown-linux-gnu', 2, 62),
}


def executable(package, system=None, machine=None):
    target = TARGETS.get((system or platform.system(), machine or platform.machine()))
    if target is None:
        raise ValueError('No experimental Rust build supports this operating system/architecture')
    triple, elf_class, elf_machine = target
    path = package / 'bin' / triple / 'app'
    for component in (package, package / 'bin', path.parent, path):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError('Native payload paths must not contain symlinks')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o111:
            raise ValueError('Native payload must be a regular executable (publish Git mode 100755)')
        header = stream.read(52)
    if (len(header) != 52 or header[:4] != b'\x7fELF' or header[4] != elf_class
            or header[5:7] != b'\x01\x01' or struct.unpack_from('<H', header, 18)[0] != elf_machine):
        raise ValueError('Native payload has the wrong ELF architecture')
    if elf_machine == 40 and not struct.unpack_from('<I', header, 36)[0] & 0x400:
        raise ValueError('PocketCHIP payload must use the ARM hard-float ABI')
    return path


def supervise(path, arguments):
    # Keep this Python process visible to App Center's existing running-app
    # detection. Forward shutdown and reap the child before allowing an update.
    child = None
    pending_signal = None
    handlers = {}
    def forward(signum, _frame):
        nonlocal pending_signal
        pending_signal = signum
        if child is not None and child.poll() is None:
            try:
                os.killpg(child.pid, signum)
            except ProcessLookupError:
                pass
    try:
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            handlers[signum] = signal.signal(signum, forward)
        child = subprocess.Popen([str(path), *arguments], start_new_session=True)
        if pending_signal is not None:
            forward(pending_signal, None)
        code = child.wait()
        return code if code >= 0 else 128 - code
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def main(arguments=None):
    try:
        path = executable(Path(__file__).resolve().parent)
        return supervise(path, sys.argv[1:] if arguments is None else arguments)
    except (OSError, ValueError) as error:
        print(f'Cannot launch experimental Rust app: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
