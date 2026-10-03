"""Exec an owned local child with Linux parent-death cleanup; imports are inert."""
import ctypes
import os
import signal
import shutil
import sys


def command(arguments):
    if sys.platform == 'linux':
        executable = shutil.which(arguments[0])
        if executable is None:
            return arguments  # Preserve the caller's normal missing-tool error.
        return [sys.executable, '-I', '-B', os.path.abspath(__file__), str(os.getpid()),
                os.path.abspath(executable), *arguments[1:]]
    return arguments


def starting(process):
    """The Linux helper must arm parent-death cleanup before it can be stopped.

    Popen returns after the first exec into Python. This helper then arms prctl
    before the second exec, which removes its path from the process arguments.
    Reading only this owned child's arguments avoids waiting on the UI thread.
    """
    if sys.platform != 'linux':
        return False
    try:
        with open(f'/proc/{process.pid}/cmdline', 'rb') as stream:
            arguments = stream.read(8192).split(b'\0')
    except OSError:
        return True
    return os.fsencode(os.path.abspath(__file__)) in arguments


def main():
    if len(sys.argv) < 3:
        return 2
    parent = int(sys.argv[1])
    if sys.platform == 'linux':
        library = ctypes.CDLL(None, use_errno=True)
        library.prctl.argtypes = (ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong)
        library.prctl.restype = ctypes.c_int
        # SIGKILL also closes a paused decoder. The setting survives this exec.
        if library.prctl(1, int(signal.SIGKILL), 0, 0, 0) != 0:
            return 1
        if os.getppid() != parent:
            return 1
    os.execv(sys.argv[2], sys.argv[2:])
    return 1


if __name__ == '__main__':
    sys.exit(main())
