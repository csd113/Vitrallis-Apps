"""480×272 native UI. All widget/image operations stay on the Tk main thread."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import queue
import time
import tkinter as tk
from tkinter import ttk

from PIL import ImageTk
from library import Library
from media import capabilities
from player import Decoder, PlaybackClock, Playlist
from settings import Settings
from storage import InstanceLock, Paths
from web_server import WebServer

BG, PANEL, INK, MUTED, ACCENT = "#10191a", "#223232", "#f1f3e8", "#adbbb3", "#d4f48a"


class Services:
    def __init__(self, paths=None, host="0.0.0.0", port=8765):
        self.instance = self.server = self.decoder = None
        self.paths = paths or Paths()
        try:
            self.instance = InstanceLock(self.paths.data)
            self.library = Library(self.paths)
            self.settings = Settings(self.paths.config)
            self.server = WebServer(self.library, self.settings, host, port)
            try:
                self.server.start()
            except OSError as error:
                self.server.state = "Server unavailable: " + str(error)
            self.decoder = Decoder(self.library)
        except BaseException:
            self.close()
            raise

    def close(self):
        errors = []
        for resource in (self.server, self.decoder, self.instance):
            if resource is not None:
                try:
                    resource.close()
                except Exception as error:
                    errors.append(str(error))
        if errors:
            raise RuntimeError("; ".join(errors))


class App:
    def __init__(self, root, service_factory=Services):
        self.root = root
        self.services = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="carousel-control")
        self.pending = None
        self.pending_action = "startup"
        self.closing = self.finished = False
        self.shutdown_requested = False
        self.close_error = ""
        self.page = 0
        self.revision = -1
        self.screen = "home"
        self.playlist = None
        self.photo = None
        self.poll_id = None
        self.overlay_until = 0
        self.last_error = ""
        self.home_notice = "Starting local services…"
        self.root.title("Vitrallis Media Carousel")
        self.root.geometry("480x272")
        self.root.minsize(400, 240)
        self.root.configure(bg=BG)
        self.root.option_add("*Font", "{DejaVu Sans} -14")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", self.escape)
        self.root.bind("<Left>", lambda event: self.navigate(-1))
        self.root.bind("<Right>", lambda event: self.navigate(1))
        self.root.bind("<Up>", lambda event: self.move_focus(-1))
        self.root.bind("<Down>", lambda event: self.move_focus(1))
        self.root.bind("<space>", self.space)
        self.root.bind("<Tab>", self.tab, add="+")
        self.root.bind("<ISO_Left_Tab>", self.tab, add="+")
        self.root.bind("<Shift-Tab>", self.tab, add="+")
        self.frame = tk.Frame(root, bg=BG)
        self.frame.pack(fill="both", expand=True)
        try:
            self.icon = tk.PhotoImage(file=str(Path(__file__).resolve().with_name("icon.png")))
            root.iconphoto(True, self.icon)
        except tk.TclError:
            self.home_notice += " Icon unavailable."
        self.home()
        self.root.update_idletasks()
        self.pending = self.executor.submit(service_factory)
        self.schedule()

    def button(self, parent, text, command, **kwargs):
        button = tk.Button(parent, text=text, command=command, bg=PANEL, fg=INK,
                           activebackground=ACCENT, activeforeground=BG,
                           disabledforeground=MUTED, relief="flat", bd=0,
                           highlightthickness=2, highlightbackground=PANEL,
                           highlightcolor=ACCENT, takefocus=True, **kwargs)
        for key in ("<Return>", "<KP_Enter>"):
            button.bind(key, lambda event: (event.widget.invoke(), "break")[-1])
        return button

    def label(self, parent, text, **kwargs):
        return tk.Label(parent, text=text, bg=BG, fg=INK, anchor="w", **kwargs)

    def clear(self):
        for child in self.frame.winfo_children():
            child.destroy()
        self.photo = None

    def header(self, title, settings=False):
        header = tk.Frame(self.frame, bg=BG, height=38)
        header.pack(fill="x", padx=8, pady=(4, 0))
        header.pack_propagate(False)
        self.button(header, "Home / Exit" if self.screen == "home" else "Back", self.escape).pack(side="right", fill="y")
        if settings:
            self.button(header, "Settings", self.settings_screen).pack(side="right", fill="y", padx=4)
        self.label(header, title, font=("DejaVu Sans", -15, "bold")).pack(side="left", fill="both", expand=True)

    def home(self, message=None):
        if self.closing:
            return
        if self.services:
            self.services.decoder.stop()
        self.screen = "home"
        self.playlist = None
        if message is not None:
            self.home_notice = message
        self.clear()
        self.header("Media Carousel", settings=True)
        server = self.services.server if self.services else None
        address = server.urls[0] if server and server.urls else "Management address pending…"
        self.url_label = self.label(self.frame, address, font=("DejaVu Sans", -16, "bold"))
        self.url_label.pack(fill="x", padx=10)
        code = "Access code: " + server.token if server else "A new access code will appear here."
        self.label(self.frame, code, font=("DejaVu Sans Mono", -14)).pack(fill="x", padx=10)
        self.status_label = self.label(self.frame, self.home_notice, font=("DejaVu Sans", -12))
        self.status_label.pack(fill="x", padx=10, pady=(1, 2))
        footer = tk.Frame(self.frame, bg=BG, height=34)
        footer.pack(side="bottom", fill="x", padx=8, pady=4)
        footer.pack_propagate(False)
        self.button(footer, "‹", lambda: self.change_page(-1), width=3).pack(side="left", fill="y")
        self.page_label = self.label(footer, "Collections", font=("DejaVu Sans", -12))
        self.page_label.pack(side="left", padx=10)
        self.button(footer, "›", lambda: self.change_page(1), width=3).pack(side="right", fill="y")
        self.folder_frame = tk.Frame(self.frame, bg=BG)
        self.folder_frame.pack(fill="both", expand=True, padx=8)
        self.draw_folders()

    def draw_folders(self):
        for child in self.folder_frame.winfo_children():
            child.destroy()
        self.folder_buttons = []
        if not self.services:
            self.label(self.folder_frame, "Upload from your phone or computer\nwhen the server is ready.", justify="left").pack(anchor="w", pady=8)
            return
        collections = self.services.library.snapshot()
        self.revision = self.services.library.revision
        self.page = min(self.page, max(0, (len(collections) - 1) // 2))
        self.page_label.configure(text=f"Collections {self.page + 1}/{(len(collections) + 1) // 2} · Enter to play")
        for index, row in enumerate(collections[self.page * 2:self.page * 2 + 2]):
            label = row["name"] if len(row["name"]) <= 33 else row["name"][:30] + "…"
            button = self.button(self.folder_frame, f"{label}   ·   {len(row['items'])} items",
                                 lambda cid=row["id"]: self.play(cid), anchor="w", padx=10)
            button.place(relx=0, rely=index * 0.5, relwidth=1, relheight=0.5, height=-3)
            self.folder_buttons.append(button)
        if self.folder_buttons:
            self.folder_buttons[0].focus_set()

    def change_page(self, direction):
        if not self.services or self.screen != "home":
            return
        maximum = (len(self.services.library.snapshot()) - 1) // 2
        self.page = max(0, min(maximum, self.page + direction))
        self.draw_folders()

    def move_focus(self, direction):
        if self.screen != "home" or not self.folder_buttons:
            return None
        focused = self.root.focus_get()
        if focused in self.folder_buttons:
            index = self.folder_buttons.index(focused) + direction
            if not 0 <= index < len(self.folder_buttons):
                self.change_page(direction)
                index = 0 if direction > 0 else len(self.folder_buttons) - 1
        else:
            index = 0
        self.folder_buttons[index].focus_set()
        return "break"

    def settings_screen(self):
        if not self.services or self.pending is not None or self.closing:
            return
        self.screen = "settings"
        self.clear()
        self.header("Playback settings")
        config = self.services.settings.snapshot()
        form = tk.Frame(self.frame, bg=BG)
        form.pack(fill="both", expand=True, padx=12, pady=4)
        form.columnconfigure(0, weight=1)
        self.seconds = tk.StringVar(value=str(config["image_seconds"]))
        self.repeats = tk.StringVar(value=str(config["repeats"]))
        self.order = tk.StringVar(value="In Order" if config["order"] == "ordered" else "Shuffle")
        self.loop = tk.StringVar(value="Loop Folder" if config["loop"] else "Return to Main Menu")
        controls = []
        for row, (label, variable, maximum) in enumerate((("Still image seconds", self.seconds, 3600),
                                                        ("Animated/video repeats", self.repeats, 100))):
            self.label(form, label).grid(row=row, column=0, sticky="w")
            control = tk.Spinbox(form, from_=1, to=maximum, textvariable=variable,
                                 width=8, bg=PANEL, fg=INK, buttonbackground=PANEL, insertbackground=INK)
            control.grid(row=row, column=1, sticky="ew", ipady=5, pady=2)
            controls.append(control)
        for row, label, variable, values in ((2, "Playback order", self.order, ("In Order", "Shuffle")),
                                             (3, "End of folder", self.loop, ("Loop Folder", "Return to Main Menu"))):
            self.label(form, label).grid(row=row, column=0, sticky="w")
            ttk.Combobox(form, textvariable=variable, values=values, state="readonly", width=20).grid(
                row=row, column=1, sticky="ew", ipady=4, pady=2)
        self.settings_message = self.label(self.frame, "Applies when you start a collection.", font=("DejaVu Sans", -12))
        self.settings_message.pack(fill="x", padx=10)
        self.save_button = self.button(self.frame, "Save settings", self.save_settings)
        self.save_button.pack(fill="x", padx=8, pady=(2, 6), ipady=3)
        controls[0].focus_set()

    def save_settings(self):
        if self.pending is not None:
            return
        try:
            data = {"image_seconds": int(self.seconds.get()), "repeats": int(self.repeats.get()),
                    "order": "ordered" if self.order.get() == "In Order" else "shuffle",
                    "loop": self.loop.get() == "Loop Folder"}
            from settings import validate
            validate(data)
        except ValueError as error:
            self.settings_message.configure(text=str(error)[:70])
            return
        self.save_button.configure(state="disabled")
        self.pending = self.executor.submit(self.services.settings.save, data)
        self.pending_action = "settings"

    def play(self, cid):
        if not self.services or self.closing:
            return
        try:
            items = self.services.library.playlist(cid)
        except (KeyError, ValueError):
            self.home("Collection changed. Choose another collection.")
            return
        if not items:
            self.home("Empty collection. Open the address above to upload media.")
            return
        self.screen = "playback"
        self.clear()
        self.last_error = ""
        self.playlist = Playlist(items, self.services.settings.snapshot())
        self.canvas = tk.Canvas(self.frame, bg="black", highlightthickness=0, takefocus=True)
        self.canvas.pack(fill="both", expand=True)
        self.image_id = self.canvas.create_image(0, 0, anchor="center")
        self.canvas.bind("<ButtonRelease-1>", lambda event: self.show_controls())
        self.canvas.bind("<Configure>", self.center_frame)
        self.overlay = tk.Frame(self.frame, bg=PANEL)
        self.button(self.overlay, "‹ Previous", lambda: self.advance(-1)).pack(side="left", fill="both", expand=True)
        self.pause_button = self.button(self.overlay, "Pause", self.pause)
        self.pause_button.pack(side="left", fill="both", expand=True)
        self.button(self.overlay, "Next ›", self.advance).pack(side="left", fill="both", expand=True)
        self.button(self.overlay, "Back", self.escape).pack(side="left", fill="both", expand=True)
        self.canvas.focus_set()
        self.root.update_idletasks()
        self.advance()
        self.show_controls()

    def center_frame(self, event=None):
        if self.screen == "playback":
            self.canvas.coords(self.image_id, self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2)

    def load_item(self, item):
        if item is None:
            message = self.last_error or "Collection finished."
            if self.playlist and len(self.playlist.bad) == len(self.playlist.items):
                message = "No playable media. " + (self.last_error or "Upload supported files.")
            self.home(message)
            return
        self.clock = PlaybackClock()
        self.canvas.delete("error")
        self.canvas.itemconfigure(self.image_id, image="")
        self.photo = None
        self.generation = self.services.decoder.request(item,
            (self.canvas.winfo_width(), self.canvas.winfo_height()), self.playlist.settings)
        self.pause_button.configure(text="Pause")

    def advance(self, direction=1):
        if self.screen == "playback":
            self.load_item(self.playlist.previous() if direction < 0 else self.playlist.next())

    def navigate(self, direction):
        if self.screen == "playback":
            self.advance(direction)
            return "break"
        if self.screen == "home":
            self.change_page(direction)
            return "break"
        return None

    def pause(self):
        if self.screen == "playback":
            self.clock.toggle()
            self.pause_button.configure(text="Resume" if self.clock.paused else "Pause")
            self.show_controls()

    def space(self, event):
        if self.screen == "playback" and event.widget == self.canvas:
            self.pause()
            return "break"
        return None

    def tab(self, event):
        if self.screen == "playback":
            self.show_controls()

    def show_controls(self):
        if self.screen == "playback":
            self.overlay.place(relx=0, rely=1, anchor="sw", relwidth=1, height=42)
            self.overlay_until = time.monotonic() + 3

    def playback_tick(self):
        if (time.monotonic() > self.overlay_until and not self.clock.paused
                and self.root.focus_get() not in self.overlay.winfo_children()):
            self.overlay.place_forget()
        if not self.clock.ready():
            return
        try:
            generation, kind, value, seconds = self.services.decoder.events.get_nowait()
        except queue.Empty:
            return
        if generation != self.generation:
            return
        if kind == "frame":
            self.photo = ImageTk.PhotoImage(value, master=self.root)
            self.canvas.itemconfigure(self.image_id, image=self.photo)
            self.center_frame()
            self.clock.arm(seconds)
        elif kind == "done":
            self.advance()
        elif kind == "error":
            self.last_error = value
            self.load_item(self.playlist.failed())
            if self.screen == "playback":
                self.show_controls()
                self.canvas.delete("error")
                self.canvas.create_text(8, 8, text="Skipped: " + value, anchor="nw", width=max(100, self.canvas.winfo_width()-16),
                                        fill="#ffb7a8", font=("DejaVu Sans", -12), tags="error")

    def schedule(self):
        if not self.finished:
            self.poll_id = self.root.after(20 if self.screen == "playback" else 200, self.poll)

    def poll(self):
        self.poll_id = None
        if self.shutdown_requested:
            self.close()
        if self.pending is not None and self.pending.done():
            action, future = self.pending_action, self.pending
            self.pending = None
            try:
                result = future.result()
                if action == "startup":
                    self.services = result
                    if not self.closing:
                        note = result.library.warning or result.settings.warning or result.server.state
                        if not capabilities()["webm"]:
                            note += " · WebM needs ffmpeg/ffprobe"
                        self.home(note)
                elif action == "settings" and not self.closing and self.screen == "settings":
                    self.settings_message.configure(text=self.services.settings.warning or "Saved. Start a collection to apply.")
                    self.save_button.configure(state="normal")
                elif action == "close":
                    self.destroy()
                    return
            except Exception as error:
                if action == "close":
                    self.close_error = str(error)
                    self.destroy()
                    return
                if not self.closing:
                    if self.screen == "settings":
                        self.settings_message.configure(text=str(error)[:70])
                        self.save_button.configure(state="normal")
                    else:
                        self.home("Cannot start: " + str(error)[:95])
        if self.closing:
            if self.pending is None:
                self.pending_action = "close"
                self.pending = self.executor.submit(self.services.close if self.services else lambda: None)
        elif self.screen == "playback":
            self.playback_tick()
        elif self.screen == "home" and self.services and self.revision != self.services.library.revision:
            self.draw_folders()
        self.schedule()

    def escape(self, event=None):
        if self.screen != "home" and not self.closing:
            self.home(self.last_error or "Ready · select a collection to play")
        else:
            self.close()
        return "break"

    def close(self):
        if self.closing or self.finished:
            return
        self.closing = True
        if self.services:
            self.services.decoder.stop()
        self.screen = "closing"
        self.clear()
        self.label(self.frame, "Stopping uploads and playback…").pack(expand=True)

    def destroy(self):
        self.finished = True
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
            self.poll_id = None
        self.root.destroy()

    def finish(self):
        # Handles an external mainloop quit as well as normal Home/WM close.
        if not self.finished:
            if self.pending is not None:
                result = self.pending.result(timeout=45)
                if self.pending_action == "startup":
                    self.services = result
            if self.services:
                self.services.close()
            self.finished = True
        self.executor.shutdown(wait=True)
        if self.close_error:
            raise RuntimeError(self.close_error)
