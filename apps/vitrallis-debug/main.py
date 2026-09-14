#!/usr/bin/env python3
"""Vitrallis Debug launcher; importing this module has no runtime side effects."""
from __future__ import annotations

import sys
import signal

# Installed packages are read-only.  Avoid interpreter bytecode caches beside app files.
sys.dont_write_bytecode = True


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args not in ([], ["--demo"]):
        print("Usage: python3 main.py [--demo]", file=sys.stderr)
        return 2
    try:
        import tkinter as tk
    except ImportError:
        print("Vitrallis Debug requires system Tkinter.", file=sys.stderr)
        return 1
    try:
        root = tk.Tk()
    except tk.TclError:
        print("Vitrallis Debug needs a graphical desktop with Tkinter.", file=sys.stderr)
        return 1
    root.title("Vitrallis Debug")
    if root.tk.call("tk", "windowingsystem") == "x11":
        # Tk publishes _NET_WM_PID when the client hostname is set.
        root.wm_client(root.tk.call("info", "hostname"))
    root.geometry("480x272")
    root.minsize(400, 240)
    dashboard = None
    handlers = {}
    try:
        from ui import Dashboard
        collector = None
        if args == ["--demo"]:
            from demo import DemoCollector
            collector = DemoCollector()
        dashboard = Dashboard(root, tk, collector, demo=args == ["--demo"])
        for signum in (signal.SIGTERM, signal.SIGINT):
            handlers[signum] = signal.signal(signum, lambda *_: dashboard.close())
        root.mainloop()
    except Exception as error:
        try: root.destroy()
        except tk.TclError: pass
        print(f"Vitrallis Debug could not start: {error}", file=sys.stderr)
        return 1
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
        if dashboard is not None:
            close = getattr(dashboard.collector, 'close', None)
            if close:
                close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
