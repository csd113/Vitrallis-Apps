#!/usr/bin/env python3
"""A small offline Tk app. Importing this module performs no I/O."""
from pathlib import Path
import sys


def greeting():
    return (Path(__file__).resolve().parent / 'assets' / 'greeting.txt').read_text(
        encoding='utf-8').strip()


def build_window(root, tk):
    root.title('Hello Vitrallis')
    root.geometry('480x272')
    root.minsize(480, 272)
    root.configure(background='#152635')
    root.protocol('WM_DELETE_WINDOW', root.destroy)
    root.bind('<Escape>', lambda event: root.destroy())
    label = tk.Label(root, text=greeting(), background='#152635', foreground='#f4f8fc',
                     font=('DejaVu Sans', -24), wraplength=440)
    label.pack(expand=True, padx=20, pady=12)
    home = tk.Button(root, text='Home', command=root.destroy, font=('DejaVu Sans', -16),
                     takefocus=True)
    home.pack(padx=20, pady=(0, 20), fill='x', ipady=8)
    home.bind('<Return>', lambda event: home.invoke())
    home.bind('<KP_Enter>', lambda event: home.invoke())
    home.focus_set()
    return label, home


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args == ['--check']:
        try:
            print(greeting())
        except (OSError, UnicodeError) as error:
            print(f'Cannot read bundled greeting: {error}', file=sys.stderr)
            return 1
        return 0
    if args:
        print('Usage: python3 main.py [--check]', file=sys.stderr)
        return 2
    try:
        import tkinter as tk
    except ImportError:
        print('Install Python Tkinter through your system package manager.', file=sys.stderr)
        return 1
    try:
        root = tk.Tk()
    except tk.TclError:
        print('Hello Vitrallis needs a graphical desktop with Tkinter.', file=sys.stderr)
        return 1
    try:
        build_window(root, tk)
        root.mainloop()
    except (OSError, UnicodeError, tk.TclError) as error:
        print(f'Cannot open Hello Vitrallis: {error}', file=sys.stderr)
        return 1
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass  # The Home button or window manager already destroyed it.
    return 0


if __name__ == '__main__':
    sys.exit(main())
