#!/usr/bin/env python3
"""Native manifest-v1 entry point. Imports do not start services or write files."""
import sys
import signal

NAME = "Vitrallis Media Carousel"
VERSION = "0.4.1"


def install_shutdown_handlers(app):
    """The shell can send TERM; defer cleanup to the regular Tk event loop."""
    previous = {}
    def request_shutdown(signum, frame):
        app.shutdown_requested = True
    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.signal(signum, request_shutdown)
    return previous


def main():
    sys.dont_write_bytecode = True
    try:
        import tkinter as tk
        from ui import App
    except ImportError as error:
        print("Vitrallis Media Carousel needs Python 3.9+, Tk 8.6 and Pillow: " + str(error), file=sys.stderr)
        return 1
    try:
        root = tk.Tk()
    except tk.TclError:
        print("Vitrallis Media Carousel needs a graphical session with Tk 8.6.", file=sys.stderr)
        return 1
    app = App(root)
    previous = install_shutdown_handlers(app)
    try:
        root.mainloop()
    finally:
        try:
            app.finish()
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
