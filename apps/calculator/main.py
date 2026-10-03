#!/usr/bin/env python3
"""Keyboard-first PocketCHIP calculator; drawing occurs only after input."""
from pathlib import Path
import signal
import sys
sys.dont_write_bytecode = True
try:
    import tkinter as tk
except ImportError:
    tk = None
from calculation import Calculator

VERSION = '0.1.1'
BG, PANEL, INK, MUTED, ACCENT = '#0c121b', '#172331', '#f1f5fa', '#a3b3c5', '#60d6ac'
KEYS = ('C', 'Backspace', '%', '/', '7', '8', '9', '*', '4', '5', '6', '-',
        '1', '2', '3', '+', '±', '0', '.', '=')


class App:
    def __init__(self, root):
        self.root = root
        self.model = Calculator()
        self.closed = False
        root.title('Calculator')
        root.geometry('480x272')
        root.minsize(480, 272)
        root.configure(bg=BG)
        if root.tk.call('tk', 'windowingsystem') == 'x11':
            root.wm_client(root.tk.call('info', 'hostname'))
        self.expression = tk.Label(root, bg=BG, fg=MUTED, anchor='e', font=('DejaVu Sans', -13))
        self.expression.place(x=8, y=8, width=372, height=24)
        self.result = tk.Label(root, text='0', bg=BG, fg=INK, anchor='e', font=('DejaVu Sans', -30))
        self.result.place(x=8, y=34, width=464, height=39)
        self.notice = tk.Label(root, bg=BG, fg=ACCENT, anchor='w', font=('DejaVu Sans', -11))
        self.notice.place(x=8, y=76, width=464, height=20)
        self.buttons = []
        for index, key in enumerate(KEYS):
            button = self.button('⌫' if key == 'Backspace' else {'*': '×', '/': '÷'}.get(key, key), key)
            button.place(x=8 + index % 4 * 118, y=101 + index // 4 * 30, width=110, height=27)
            self.buttons.append(button)
        for index, key in enumerate(('(', ')')):
            self.button(key, key).place(x=388 + index * 44, y=6, width=40, height=27)
        tk.Label(root, text='Arrows / Tab: focus   Enter: press   =: result   Esc: exit',
                 bg=BG, fg=MUTED, font=('DejaVu Sans', -10)).place(x=8, y=253, width=464, height=17)
        root.bind('<Key>', self.keyboard)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.buttons[4].focus_set()
        try:
            self.icon = tk.PhotoImage(file=str(Path(__file__).with_name('icon.png')))
            root.iconphoto(True, self.icon)
        except tk.TclError:
            pass
        self.draw()
        self.signal_job = root.after(250, self.poll_signals)

    def poll_signals(self):
        # Linux Tk can defer Python signals while idle. Return to Python without
        # drawing or polling files so TERM is handled promptly on a static view.
        if not self.closed:
            self.signal_job = self.root.after(250, self.poll_signals)

    def button(self, label, key):
        button = tk.Button(self.root, text=label, command=lambda: self.press(key),
                           bg=PANEL, fg=BG if self.root.tk.call('tk', 'windowingsystem') == 'aqua' else INK,
                           activebackground='#294050', activeforeground=INK,
                           relief='flat', bd=0, highlightthickness=2,
                           highlightbackground=PANEL, highlightcolor=ACCENT,
                           font=('DejaVu Sans', -15), takefocus=True)
        button.bind('<Return>', lambda event: (self.press(key), 'break')[1])
        button.bind('<KP_Enter>', lambda event: (self.press(key), 'break')[1])
        return button

    def keyboard(self, event):
        if event.keysym == 'Escape':
            self.close()
        elif event.keysym in ('Left', 'Right', 'Up', 'Down'):
            focused = self.root.focus_get()
            index = self.buttons.index(focused) if focused in self.buttons else 0
            row, column = divmod(index, 4)
            if event.keysym in ('Left', 'Right'):
                column = (column + (1 if event.keysym == 'Right' else -1)) % 4
            else:
                row = (row + (1 if event.keysym == 'Down' else -1)) % 5
            self.buttons[row * 4 + column].focus_set()
        elif event.keysym in ('Return', 'KP_Enter'):
            self.press('=')
        elif event.keysym == 'BackSpace':
            self.press('Backspace')
        elif event.keysym == 'Delete' or event.char.lower() == 'c':
            self.press('C')
        elif event.char and event.char in '0123456789.eE+-*/()%=':
            self.press(event.char)
        else:
            return None
        return 'break'

    def press(self, key):
        self.model.press(key)
        self.draw()

    def draw(self):
        text = self.model.expression
        self.expression.configure(text=('…' + text[-42:]) if len(text) > 43 else text or 'Enter numbers or use the keypad')
        self.result.configure(text=self.model.result)
        self.notice.configure(text=self.model.error or ('Decimal arithmetic · % means divide by 100'))

    def close(self):
        if not self.closed:
            self.closed = True
            self.root.after_cancel(self.signal_job)
            self.root.destroy()


def main():
    if tk is None:
        print('Calculator requires Tkinter; install python3-tk.', file=sys.stderr)
        return 1
    try:
        root = tk.Tk()
    except tk.TclError:
        print('Calculator requires a graphical desktop.', file=sys.stderr)
        return 1
    app = App(root)
    previous = {}
    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.signal(signum, lambda signum, frame: root.after_idle(app.close))
    try:
        root.mainloop()
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    return 0


if __name__ == '__main__':
    sys.exit(main())
