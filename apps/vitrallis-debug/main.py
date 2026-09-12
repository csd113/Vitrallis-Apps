#!/usr/bin/env python3
"""Vitrallis Debug launcher; importing this module has no runtime side effects."""
from __future__ import annotations

import sys

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
    root.geometry("480x272")
    root.minsize(400, 240)
    try:
        from ui import Dashboard
        collector = None
        if args == ["--demo"]:
            from demo import DemoCollector
            collector = DemoCollector()
        Dashboard(root, tk, collector, demo=args == ["--demo"])
        root.mainloop()
    except Exception as error:
        try: root.destroy()
        except tk.TclError: pass
        print(f"Vitrallis Debug could not start: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
