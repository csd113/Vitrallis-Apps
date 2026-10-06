#!/usr/bin/env python3
"""Music: keyboard-first native controls with one foreground-owned decoder."""
import sys
sys.dont_write_bytecode = True
import io
from pathlib import Path
import queue
import signal
import threading
import tkinter as tk
from PIL import Image, ImageTk
from player import Player, Probe, metadata, next_index, scan
from storage import Paths, directory, read_state, validate_path, write_state

APP_ID = 'io.vitrallis.music'
BG, PANEL, TEXT, MUTED, ACCENT = '#101820', '#1c2936', '#eff5fa', '#a9bacb', '#64d9bb'


def stamp(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 60}:{seconds % 60:02}'


class App:
    def __init__(self, root, paths=None, player=None):
        self.root, self.paths, self.player = root, paths or Paths(APP_ID), player or Player()
        self.closed, self.jobs, self.cancel = False, set(), threading.Event()
        self.worker, self.pending = None, queue.Queue(maxsize=2)
        self.probe = Probe()
        self.tracks, self.index, self.current_index = [], 0, None
        self.shuffle, self.repeat, self.view = False, 'off', 'library'
        self.photo, self.track, self.status = None, None, ''
        self.folder = self.paths.documents
        state = read_state(self.paths.state / 'settings.json')
        self.player.volume = state.get('volume', 70) if type(state.get('volume')) is int and 0 <= state['volume'] <= 100 else 70
        self.shuffle = state.get('shuffle') is True
        self.repeat = state.get('repeat') if state.get('repeat') in ('off', 'all', 'one') else 'off'
        self.last_path = state.get('track', '') if isinstance(state.get('track', ''), str) else ''
        try:
            saved = validate_path(state.get('folder', str(self.folder)))
            if saved == self.paths.documents or self.paths.documents in saved.parents:
                self.folder = saved
        except ValueError:
            pass
        root.title('Music')
        root.geometry('480x272')
        root.minsize(480, 272)
        root.configure(bg=BG)
        if root.tk.call('tk', 'windowingsystem') == 'x11':
            root.wm_client(root.tk.call('info', 'hostname'))
        self.header = tk.Label(root, text='Music', bg=BG, fg=TEXT, anchor='w', font=('DejaVu Sans', -19, 'bold'))
        self.header.place(x=10, y=4, width=126, height=28)
        self.button('Vol [V]', self.volume).place(x=142, y=4, width=74, height=28)
        self.button('Library [L]', self.library).place(x=224, y=4, width=100, height=28)
        self.button('Folders [F]', self.folders).place(x=330, y=4, width=140, height=28)
        self.listbox = tk.Listbox(root, bg=PANEL, fg=TEXT, selectbackground='#30576a', selectforeground=TEXT,
                                 activestyle='none', highlightthickness=2, highlightcolor=ACCENT,
                                 font=('DejaVu Sans', -14), bd=0, exportselection=False)
        self.listbox.place(x=10, y=38, width=460, height=130)
        self.listbox.bind('<<ListboxSelect>>', self.selected)
        self.listbox.bind('<Double-Button-1>', lambda e: self.activate())
        self.now = tk.Canvas(root, bg=PANEL, highlightthickness=0)
        self.volume_panel = tk.Frame(root, bg=PANEL)
        tk.Label(self.volume_panel, text='Volume · arrows or + / − · Esc back', bg=PANEL, fg=TEXT,
                 font=('DejaVu Sans', -15)).place(x=10, y=10, width=440, height=30)
        self.volume_scale = tk.Scale(self.volume_panel, from_=0, to=100, orient='horizontal',
                                    bg=PANEL, fg=TEXT, troughcolor=BG, highlightthickness=0,
                                    sliderlength=28, font=('DejaVu Sans', -14), takefocus=True)
        self.volume_scale.place(x=16, y=48, width=428, height=66)
        self.volume_scale.bind('<ButtonRelease-1>', lambda e: self.player.set_volume(self.volume_scale.get()))
        self.time = tk.Label(root, bg=BG, fg=MUTED, anchor='w', font=('DejaVu Sans', -12))
        self.time.place(x=10, y=173, width=460, height=22)
        self.seekbar = tk.Scale(root, from_=0, to=100, orient='horizontal', showvalue=False,
                                bg=BG, fg=TEXT, troughcolor=PANEL, highlightthickness=0, bd=0,
                                command=self.slider, sliderlength=20, takefocus=True)
        self.seekbar.place(x=10, y=194, width=460, height=20)
        for i, (name, command) in enumerate((('Prev', lambda: self.advance(-1)), ('Play', self.activate),
                 ('Next', lambda: self.advance(1)), ('Shuffle', self.toggle_shuffle), ('Repeat', self.toggle_repeat), ('Exit', self.close))):
            button = self.button(name, command)
            button.place(x=10+i*77, y=218, width=71, height=29)
            if i == 1:
                self.play_button = button
        self.footer = tk.Label(root, text='Space play/pause · ←/→ seek · +/− volume · ? help', bg=BG, fg=MUTED, font=('DejaVu Sans', -11))
        self.footer.place(x=10, y=251, width=460, height=19)
        root.bind('<Key>', self.key)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.listbox.focus_set()
        self.refresh()
        self.schedule(250, self.tick)

    def button(self, text, command):
        b = tk.Button(self.root, text=text, command=command, bg=PANEL,
                      fg=BG if self.root.tk.call('tk', 'windowingsystem') == 'aqua' else TEXT,
                      relief='flat', bd=0, highlightcolor=ACCENT, highlightthickness=2,
                      font=('DejaVu Sans', -12), takefocus=True)
        b.bind('<Return>', lambda e: (command(), 'break')[1])
        return b

    def schedule(self, delay, callback):
        holder = []
        def run():
            self.jobs.discard(holder[0])
            if not self.closed:
                callback()
        holder.append(self.root.after(delay, run))
        self.jobs.add(holder[0])

    def work(self, kind, function):
        if self.worker and self.worker.is_alive():
            self.status = 'Working… please wait'
            return False
        def run():
            try:
                value = function()
            except (OSError, ValueError) as error:
                value = str(error)
            if not self.cancel.is_set():
                try:
                    self.pending.put_nowait((kind, value))
                except queue.Full:
                    pass
        self.worker = threading.Thread(target=run, daemon=True, name='music-library')
        self.worker.start()
        return True

    def refresh(self):
        try:
            directory(self.paths.documents)
        except (OSError, ValueError):
            self.status = 'Music Documents folder is not writable'
            return
        self.status = 'Scanning…'
        self.work('scan', lambda: scan(self.folder, self.cancel.is_set))

    def library(self):
        self.view = 'library'
        self.volume_panel.place_forget()
        self.now.place_forget()
        self.listbox.place(x=10, y=38, width=460, height=130)
        self.fill()

    def fill(self):
        self.listbox.delete(0, 'end')
        if self.view == 'folders':
            for p in self.folder_choices:
                self.listbox.insert('end', '↑ Documents' if p == self.paths.documents else p.name)
        else:
            for p in self.tracks:
                self.listbox.insert('end', p.stem[:60])
            if not self.tracks:
                self.listbox.insert('end', 'No tracks · put music in Documents, then R')
        self.listbox.selection_set(self.index)
        self.listbox.see(self.index)

    def folders(self):
        self.view = 'folders'
        self.volume_panel.place_forget()
        self.now.place_forget()
        self.listbox.place(x=10, y=38, width=460, height=130)
        self.folder_choices = [self.paths.documents]
        try:
            self.folder_choices += sorted([p for p in self.paths.documents.iterdir() if not p.is_symlink() and p.is_dir()], key=lambda p: p.name.casefold())[:200]
        except OSError:
            self.status = 'Documents folder is empty or unavailable'
        self.index = 0
        self.fill()

    def selected(self, event=None):
        if self.listbox.curselection():
            self.index = self.listbox.curselection()[0]

    def activate(self):
        if self.view == 'folders':
            self.folder = self.folder_choices[self.index]
            self.library()
            self.refresh()
            return
        if self.player.process and (self.view == 'now' or self.index == self.current_index):
            self.player.pause()
        elif self.tracks:
            index = min(self.index, len(self.tracks)-1)
            path = self.tracks[index]
            if self.work('track', lambda: (index, metadata(path, self.probe))):
                self.status = 'Opening track…'

    def show_track(self):
        self.view = 'now'
        self.volume_panel.place_forget()
        self.listbox.place_forget()
        self.now.place(x=10, y=38, width=460, height=130)
        self.now.delete('all')
        self.now.create_rectangle(8, 8, 120, 120, fill='#294252', outline='')
        self.now.create_text(64, 64, text='♪', fill=ACCENT, font=('DejaVu Sans', -48))
        if self.track.art:
            try:
                image = Image.open(io.BytesIO(self.track.art))
                image.thumbnail((112,112))
                self.photo = ImageTk.PhotoImage(image)
                self.now.create_image(64, 64, image=self.photo)
            except (OSError, ValueError):
                self.photo = None
        for y, text, size, color in ((14, self.track.title, 16, TEXT), (52, self.track.artist, 13, ACCENT), (86, self.track.album, 12, MUTED)):
            from tkinter.font import Font
            font = Font(root=self.root, font=('DejaVu Sans', -size))
            while font.measure(text) > 312 and len(text) > 2:
                text = text[:-2] + '…'
            self.now.create_text(134, y, text=text, anchor='nw', fill=color, font=('DejaVu Sans', -size))

    def volume(self):
        self.view = 'volume'
        self.now.place_forget()
        self.listbox.place_forget()
        self.volume_scale.set(self.player.volume)
        self.volume_panel.place(x=10, y=38, width=460, height=130)
        self.volume_scale.focus_set()

    def advance(self, direction=1, automatic=False):
        i = next_index(self.current_index if self.current_index is not None else self.index, len(self.tracks), direction,
                       self.shuffle, self.repeat if automatic else ('all' if self.repeat == 'all' else 'off'))
        if i is not None:
            self.index = i
            path = self.tracks[i]
            self.work('track', lambda: (i, metadata(path, self.probe)))

    def slider(self, value):
        # Ignore programmatic updates; seeking happens on explicit release/keyboard.
        pass

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle

    def toggle_repeat(self):
        self.repeat = {'off':'all', 'all':'one', 'one':'off'}[self.repeat]

    def key(self, event):
        key, char = event.keysym, event.char.lower()
        if key == 'space' and isinstance(self.root.focus_get(), tk.Button):
            return None
        if key == 'Escape':
            if self.view == 'volume':
                self.show_track() if self.track else self.library()
            elif self.view in ('now', 'folders'):
                self.library()
            else:
                self.close()
        elif key == 'space': self.activate()
        elif key in ('Return', 'KP_Enter') and self.root.focus_get() is self.listbox: self.activate()
        elif key in ('Left','Right'):
            if self.view == 'volume':
                self.player.set_volume(self.player.volume + (-5 if key=='Left' else 5))
                self.volume_scale.set(self.player.volume)
            else:
                self.player.seek(self.player.position() + (-5 if key=='Left' else 5))
        elif char in ('+', '-', '='): self.player.set_volume(self.player.volume + (-5 if char == '-' else 5))
        elif char == 'l': self.library()
        elif char == 'f': self.folders()
        elif char == 'v': self.volume()
        elif char == 'r': self.refresh()
        elif char == 's': self.toggle_shuffle()
        elif char == 't': self.toggle_repeat()
        elif char == 'n': self.advance(1)
        elif char == 'p': self.advance(-1)
        elif char == '?': self.footer.configure(text='L library · F folders · R refresh · N/P next/prev · S/T modes')
        else: return None
        return 'break'

    def tick(self):
        while not self.pending.empty():
            kind, value = self.pending.get_nowait()
            if kind == 'scan' and isinstance(value, tuple):
                self.tracks, self.status = value
                self.index = next((i for i,p in enumerate(self.tracks) if str(p) == self.last_path), 0)
                if self.track:
                    self.current_index = next((i for i,p in enumerate(self.tracks) if p == self.track.path), None)
                self.library()
            elif kind == 'track' and isinstance(value, tuple):
                self.current_index, self.track = value
                self.status = ''
                self.player.play(self.track)
                self.show_track()
            else:
                self.status = str(value)[:70]
        if self.player.finished():
            self.advance(automatic=True)
        message = self.player.error or self.status
        if self.track and not message:
            message = f'{stamp(self.player.position())} / {stamp(self.track.duration)}'
        modes = f'Vol {self.player.volume}% · Shuffle {"on" if self.shuffle else "off"} · Repeat {self.repeat}'
        text = message if self.player.error or self.status else message + ' · ' + modes
        from tkinter.font import Font
        font = Font(root=self.root, font=self.time.cget('font'))
        while font.measure(text) > 450 and len(text) > 2:
            text = text[:-2] + '…'
        self.time.configure(text=text)
        self.header.configure(text='Music')
        self.play_button.configure(text='Resume' if self.player.paused else 'Pause' if self.player.process else 'Play')
        if self.track and self.track.duration:
            self.seekbar.set(100*self.player.position()/self.track.duration)
        self.seekbar.bind('<ButtonRelease-1>', lambda e: self.player.seek(self.track.duration * self.seekbar.get()/100) if self.track else None)
        self.schedule(500, self.tick)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.cancel.set()
        self.probe.close()
        self.player.stop()
        try:
            write_state(self.paths.state / 'settings.json', {'volume':self.player.volume, 'shuffle':self.shuffle,
                        'repeat':self.repeat, 'folder':str(self.folder), 'track':str(self.track.path) if self.track else self.last_path})
        except (OSError, ValueError):
            pass
        for job in self.jobs:
            self.root.after_cancel(job)
        self.root.destroy()


def main():
    try:
        root = tk.Tk()
        app = App(root)
    except (tk.TclError, OSError, ValueError) as error:
        print(f'Music could not start: {error}', file=sys.stderr)
        return 1
    previous = {s: signal.signal(s, lambda *_: app.close()) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        root.mainloop()
    finally:
        app.close()
        for s, handler in previous.items(): signal.signal(s, handler)
    return 0


if __name__ == '__main__':
    sys.exit(main())
