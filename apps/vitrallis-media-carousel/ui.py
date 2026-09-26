"""480×272 native UI. All widget/image operations stay on the Tk main thread."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

from PIL import Image, ImageTk
from connection import qr_image
from convert import ConversionError, Conversions, needs_conversion
from gpu import GpuUnavailable, ImageRenderer
from library import Library
from multimedia import DetectionCancelled, capabilities
from player import Decoder, PlaybackClock, Playlist, freeze
from settings import Settings
from storage import InstanceLock, Paths
from web_server import WebServer

BG, PANEL, INK, MUTED, ACCENT = "#10191a", "#223232", "#f1f3e8", "#adbbb3", "#d4f48a"

# Bounded late-frame skipping: at most this many expired animation frames are
# discarded per tick before playback resynchronises instead of drifting.
MAX_CATCHUP = 8
# Poll interval while the decoder has not caught up with a due deadline.
STARVED_MS = 20
# Re-arm delay after a hand-driven item load so the decoded frame is presented
# immediately instead of waiting out the previous (capped) timer.
WAKE_MS = 4
# The home status band is capped so long diagnostics can never squeeze the
# collection list out of a short window.
STATUS_LINES_SMALL, STATUS_LINES_LARGE = 2, 3
SMALL_WINDOW_HEIGHT = 260
# Touch-target floor for the collection rows, kept in pixels.
MIN_FOLDER_ROW = 36
# Friendly replacement shown when startup fails, instead of raw exception text.
STARTUP_FAILURE = ("Cannot start the local library. Your files were left untouched. "
                   "See the README troubleshooting section, then repair or remove the "
                   "storage files and restart the app.")


class Services:
    """Local playback services first; the management UI starts behind them.

    The library, settings, decoder and conversion job are ready before this
    constructor returns. Binding the HTTP server, discovering LAN addresses and
    probing FFmpeg all happen on background threads, so a slow or missing
    network interface can never delay slideshow playback.
    """

    def __init__(self, paths=None, host="0.0.0.0", port=8765):
        self.instance = self.server = self.decoder = self.conversions = None
        self.capabilities = None
        self.capability_thread = None
        self.probe_cancel = threading.Event()
        self.paths = paths or Paths()
        try:
            self.instance = InstanceLock(self.paths.data)
            self.library = Library(self.paths)
            self.settings = Settings(self.paths.config)
            # Cold decoder probes never run on Tk's thread and never gate playback.
            self.decoder = Decoder(self.library)
            self.server = WebServer(self.library, self.settings, host, port)
            # One conversion job is shared by the native UI and the HTTP API.
            self.conversions = Conversions(self.library, self.server.processes)
            self.server.conversions = self.conversions
            try:
                self.server.start_async()
            except RuntimeError as error:
                self.server.detail = "Web server unavailable: " + str(error)
                self.server.state = WebServer.FAILED
            self.capability_thread = threading.Thread(target=self._probe,
                                                      name="carousel-capabilities", daemon=True)
            self.capability_thread.start()
        except BaseException:
            self.close()
            raise

    def _probe(self):
        try:
            self.capabilities = capabilities(cancel=self.probe_cancel)
            if self.capabilities is not None:
                self.report_decoders()
        except DetectionCancelled:
            pass
        except Exception as error:  # A diagnostic must never take playback down.
            print("event=decoder_probe status=failed reason=%r" % str(error), file=sys.stderr)

    def report_decoders(self):
        report = (self.capabilities or {}).get("acceleration") or {}
        for codec, backend in sorted(report.get("codecs", {}).items()):
            print("event=decoder_probe codec=%s backend=%s method=%r verified=%s reason=%r"
                  % (codec, backend.get("name"), backend.get("method"),
                     backend.get("verified"), backend.get("reason")), file=sys.stderr)

    def media_note(self):
        """A one-line decoder summary that never probes on the caller's thread."""
        if self.capabilities is None:
            return "Checking multimedia decoders…"
        note = self.capabilities.get("webm_note", "")
        accelerated = [codec for codec, backend
                       in (self.capabilities.get("acceleration") or {}).get("codecs", {}).items()
                       if backend.get("verified")]
        if accelerated:
            return note + " Hardware decode: " + ", ".join(sorted(accelerated)) + "."
        return note

    def close(self):
        errors = []
        thread, self.capability_thread = self.capability_thread, None
        self.probe_cancel.set()  # A slow probe must never delay shutdown.
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
            if thread.is_alive():
                # The probe thread is a daemon and owns nothing that needs
                # releasing, so report it rather than failing the whole shutdown.
                print("event=decoder_probe status=stopping", file=sys.stderr)
        # Conversions first: they use the process pool owned by the server.
        for resource in (self.conversions, self.server, self.decoder, self.instance):
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
        self.photo_mode = None
        self.photo_size = None
        self.starved = False
        self.gpu_renderer = None
        self.gpu_surface = None
        self.last_frame = None
        self.animated = False
        self.poll_id = None
        self.overlay_until = 0
        self.overlay_visible = False
        self.hidden = False
        self.cid = None
        self.conversion_label = None
        self.conversion_message = ""
        self.conversion_running = False
        self.conversion_last = ""
        self.conversion_poll = 0.0
        self.last_error = ""
        self.home_notice = "Starting local services…"
        self.startup_failed = ""
        self.status_text = ""
        self.status_layout = None
        self.qr_photo = None
        self.qr_limit_used = None
        self.settings_text = ""
        self.conversion_lines = 1
        self.root.title("Vitrallis Media Carousel")
        if self.root.tk.call("tk", "windowingsystem") == "x11":
            # Tk publishes _NET_WM_PID when the client hostname is set.
            self.root.wm_client(self.root.tk.call("info", "hostname"))
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
        self.root.bind("<c>", self.convert_key)
        self.root.bind("<C>", self.convert_key)
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
        return tk.Label(parent, text=text, bg=BG, fg=INK, anchor="w", bd=0, **kwargs)

    @staticmethod
    def wrap_text(text, font, width):
        """Greedy word wrap that mirrors how a Tk label wraps its text."""
        lines = []
        for paragraph in str(text).split("\n"):
            current = ""
            for word in paragraph.split(" "):
                candidate = word if not current else current + " " + word
                if current and font.measure(candidate) > width:
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            lines.append(current)
        return lines or [""]

    def clamp_text(self, text, font, width, lines):
        """Fit text to `lines` wrapped lines, marking any cut with an ellipsis."""
        wrapped = self.wrap_text(text, font, max(1, width))
        if len(wrapped) <= lines:
            return text
        wrapped = wrapped[:max(1, lines)]
        while wrapped and font.measure(wrapped[-1].strip() + " …") > width:
            head = wrapped[-1].rsplit(" ", 1)[0] if " " in wrapped[-1].strip() else ""
            if not head:
                break
            wrapped[-1] = head
        wrapped[-1] = (wrapped[-1].strip() + " …").strip()
        return "\n".join(wrapped)

    def status_lines(self):
        return (STATUS_LINES_LARGE if self.root.winfo_height() >= SMALL_WINDOW_HEIGHT
                else STATUS_LINES_SMALL)

    def clear(self):
        self.close_gpu()
        self.last_frame = None
        self.overlay_visible = False
        self.conversion_label = self.convert_button = None
        for child in self.frame.winfo_children():
            child.destroy()
        self.photo = None
        self.photo_mode = self.photo_size = None

    def header(self, title, settings=False):
        header = tk.Frame(self.frame, bg=BG, height=38)
        header.pack(fill="x", padx=8, pady=(4, 0))
        header.pack_propagate(False)
        self.button(header, "Home / Exit" if self.screen == "home" else "Back", self.escape).pack(side="right", fill="y")
        self.settings_button = None
        if settings:
            self.settings_button = self.button(header, "Settings", self.settings_screen)
            self.settings_button.pack(side="right", fill="y", padx=4)
        self.label(header, title, font=("DejaVu Sans", -15, "bold")).pack(side="left", fill="both", expand=True)

    def home(self, message=None):
        if self.closing:
            return
        if self.services:
            self.services.decoder.stop()
        self.screen = "home"
        self.playlist = None
        self.hidden = False
        self.cid = None
        if message is not None:
            self.home_notice = message
        self.clear()
        self.header("Media Carousel", settings=True)
        failed = self.services is None and bool(self.startup_failed)
        if failed and self.settings_button is not None:
            self.settings_button.configure(state="disabled", takefocus=False)
        server = self.services.server if self.services else None
        if server and server.urls:
            address = server.urls[0]
        elif failed:
            address = "Management page unavailable"
        else:
            address = "Management address pending…"
        self.connection = tk.Frame(self.frame, bg=BG)
        self.connection.pack(fill="x", padx=10)
        self.connection.bind("<Configure>", self.layout_connection)
        self.qr_label = self.label(self.connection, "")
        self.qr_label.pack(side="right", padx=(4, 0))
        self.url_label = self.label(self.connection, address, font=("DejaVu Sans", -14, "bold"))
        self.url_label.pack(fill="x", pady=(2, 0))
        if server:
            code = "Access code: " + server.token
        elif failed:
            code = "Access code unavailable"
        else:
            code = "Access code pending…"
        self.label(self.connection, code, font=("DejaVu Sans Mono", -14)).pack(fill="x")
        self.status_font = tkfont.Font(root=self.root, family="DejaVu Sans", size=-12)
        self.status_label = self.label(self.connection, "", font=self.status_font, justify="left")
        self.status_label.pack(fill="x", pady=(1, 2))
        self.status_text = ""
        self.status_layout = None
        self.qr_url = None
        self.qr_photo = None
        self.qr_limit_used = None
        self.layout_connection()
        self.update_status(force=True)
        footer = tk.Frame(self.frame, bg=BG, height=36)
        footer.pack(side="bottom", fill="x", padx=8, pady=(2, 4))
        footer.pack_propagate(False)
        self.page_back = self.button(footer, "‹", lambda: self.change_page(-1), width=3)
        self.page_back.pack(side="left", fill="y")
        self.page_label = self.label(footer, "Collections", font=("DejaVu Sans", -12))
        self.page_label.pack(side="left", padx=10)
        self.page_forward = self.button(footer, "›", lambda: self.change_page(1), width=3)
        self.page_forward.pack(side="right", fill="y")
        self.folder_frame = tk.Frame(self.frame, bg=BG)
        self.folder_frame.pack(fill="both", expand=True, padx=8)
        self.folder_frame.bind("<Configure>", self.layout_folders)
        self.draw_folders()
        self.update_address()

    def home_status(self):
        """One concise status: failure, web-server lifecycle, notice, decoder note."""
        if not self.services:
            if self.startup_failed:
                return STARTUP_FAILURE
            return self.home_notice or "Starting local services…"
        server = self.services.server
        parts = []
        if server.state == WebServer.STARTING:
            parts.append("Web server starting · playback ready.")
        elif server.state == WebServer.FAILED:
            parts.append("Web server unavailable · playback continues locally.")
        elif server.detail and server.detail != "Ready":
            parts.append(server.detail)
        if self.home_notice and self.home_notice not in parts:
            parts.append(self.home_notice)
        note = self.services.media_note()
        if note and note != "Checking multimedia decoders…" and note not in parts:
            parts.append(note)
        if not parts:
            return note
        return " · ".join(parts)

    def layout_connection(self, event=None):
        """Track the width the QR code actually takes so the status never clips."""
        if self.screen != "home" or getattr(self, "status_label", None) is None:
            return
        height = self.root.winfo_height()
        if (self.qr_photo is not None and height > 1
                and self.qr_limit_used != self.qr_limit()):
            # A short window shrinks the QR instead of the collection rows.
            self.qr_url = None
            self.update_address()
            return
        total = self.connection.winfo_width()
        if total <= 1:
            total = max(240, self.root.winfo_width() - 20)
        qr = self.qr_label.winfo_width() + 4  # QR image or its 0-width placeholder
        layout = (max(140, total - qr - 6), self.status_lines())
        if layout == self.status_layout:
            return
        self.status_layout = layout
        self.status_label.configure(wraplength=layout[0])
        self.update_status(force=True)

    def qr_limit(self):
        """Tallest QR that still leaves two 36 px collection rows on screen."""
        height = self.root.winfo_height()
        if height <= 1:
            return 48
        return max(48, height - 42 - 42 - (2 * MIN_FOLDER_ROW + 3) - 2)

    def update_status(self, force=False):
        """Refresh the home status line as the background services progress."""
        if self.screen != "home" or getattr(self, "status_label", None) is None:
            return
        text = self.home_status()
        width, lines = self.status_layout or (max(200, self.root.winfo_width() - 20),
                                              self.status_lines())
        if not force and self.status_text == text:
            return
        self.status_text = text
        display = self.clamp_text(text, self.status_font, width, lines)
        if display != self.status_label.cget("text"):
            self.status_label.configure(text=display)

    def update_address(self):
        if not self.services or not self.services.server.urls:
            return
        url = self.services.server.urls[0]
        if url == self.qr_url:
            return
        self.qr_url = url
        self.url_label.configure(text=url)
        try:
            image = qr_image(url)
        except ImportError:
            image = None
        limit = self.qr_limit()
        if image is not None and image.height > limit:
            width = max(24, int(round(image.width * limit / image.height)))
            image = image.resize((width, limit), Image.LANCZOS)
        self.qr_limit_used = limit
        self.qr_photo = ImageTk.PhotoImage(image, master=self.root) if image else None
        # Without a QR image the right-hand slot is reclaimed so the URL and
        # status lines get the full width; no dead "QR unavailable" stub stays.
        self.qr_label.configure(image=self.qr_photo or "", text="")
        self.layout_connection()

    def draw_folders(self):
        for child in self.folder_frame.winfo_children():
            child.destroy()
        self.folder_buttons = []
        self.folder_message = None
        if not self.services:
            message = STARTUP_FAILURE if self.startup_failed else "Starting the local library…"
            self.page_label.configure(text="Library unavailable" if self.startup_failed else "Starting…")
            self.show_folder_message(message)
            self.set_page_buttons(False)
            return
        collections = self.services.library.snapshot()
        self.revision = self.services.library.revision
        if not collections:
            self.page_label.configure(text="Collections 0/0")
            self.show_folder_message("Library is empty. Upload media from the management page above.")
            self.set_page_buttons(False)
            return
        self.page = min(self.page, max(0, (len(collections) - 1) // 2))
        pages = (len(collections) + 1) // 2
        self.page_label.configure(text=f"Collections {self.page + 1}/{pages} · Enter to play")
        self.set_page_buttons(pages > 1)
        for index, row in enumerate(collections[self.page * 2:self.page * 2 + 2]):
            label = row["name"] if len(row["name"]) <= 33 else row["name"][:30] + "…"
            button = self.button(self.folder_frame, f"{label}   ·   {len(row['items'])} items",
                                 lambda cid=row["id"]: self.play(cid), anchor="w", padx=10)
            button.place(relx=0, rely=index * 0.5, relwidth=1)
            self.folder_buttons.append(button)
        self.layout_folders()
        if self.folder_buttons:
            self.folder_buttons[0].focus_set()

    def show_folder_message(self, text):
        self.folder_message = self.label(self.folder_frame, text, justify="left")
        self.folder_message.pack(anchor="w", pady=8)
        self.layout_folders()

    def set_page_buttons(self, enabled):
        state = "normal" if enabled else "disabled"
        for button in (getattr(self, "page_back", None), getattr(self, "page_forward", None)):
            if button is not None:
                button.configure(state=state, takefocus=enabled)

    def layout_folders(self, event=None):
        """Keep rows as large touch targets; a long status band cannot shrink them."""
        height = self.folder_frame.winfo_height()
        if height <= 1:
            return
        message = getattr(self, "folder_message", None)
        if message is not None:
            width = max(140, self.folder_frame.winfo_width() - 12)
            if int(message.cget("wraplength") or 0) != width:
                message.configure(wraplength=width)
        buttons = getattr(self, "folder_buttons", [])
        if not buttons:
            return
        two = len(buttons) > 1
        floor = MIN_FOLDER_ROW if (not two or height >= 2 * MIN_FOLDER_ROW + 3) else 1
        row_height = min(height, max(floor, (height - 3) // 2))
        if not two:
            buttons[0].place_configure(rely=0, relheight=0, height=row_height)
        else:
            top = height - row_height
            buttons[0].place_configure(rely=0, relheight=0, height=row_height)
            buttons[1].place_configure(rely=top / height, relheight=0, height=row_height)

    def change_page(self, direction):
        if not self.services or self.screen != "home":
            return
        maximum = (len(self.services.library.snapshot()) - 1) // 2
        page = max(0, min(maximum, self.page + direction))
        if page == self.page:
            return  # Already at the boundary: keep the current focus, skip the redraw.
        self.page = page
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
            # Predictable: Down enters at the first row, Up at the last row.
            index = 0 if direction > 0 else len(self.folder_buttons) - 1
        self.folder_buttons[index].focus_set()
        return "break"

    def settings_screen(self):
        if not self.services or self.pending is not None or self.closing:
            return
        self.screen = "settings"
        self.last_error = ""  # A playback error is not a settings status.
        self.clear()
        self.header("Playback settings")
        config = self.services.settings.snapshot()
        self.message_font = tkfont.Font(root=self.root, family="DejaVu Sans", size=-12)
        # The action row is packed before the expanding form, so Save can never
        # be squeezed out of a short window. The form absorbs the remainder.
        self.settings_bottom = tk.Frame(self.frame, bg=BG)
        self.settings_bottom.pack(side="bottom", fill="x", padx=8, pady=(2, 4))
        self.save_button = self.button(self.settings_bottom, "Save settings", self.save_settings)
        self.save_button.pack(side="right", fill="y")
        self.settings_message = self.label(self.settings_bottom, "", font=self.message_font, justify="left")
        self.settings_message.pack(side="left", fill="both", expand=True)
        self.form = tk.Frame(self.frame, bg=BG)
        self.form.pack(fill="both", expand=True, padx=12, pady=(2, 2))
        self.form.columnconfigure(1, weight=1, minsize=140)
        self.seconds = tk.StringVar(value=str(config["image_seconds"]))
        self.repeats = tk.StringVar(value=str(config["repeats"]))
        self.order = tk.StringVar(value="In Order" if config["order"] == "ordered" else "Shuffle")
        self.loop = tk.StringVar(value="Loop Folder" if config["loop"] else "Return to Main Menu")
        self.convert_gifs = tk.StringVar(value="Convert to WebP" if config["convert_gifs"] else "Keep as GIF")
        self.setting_labels = []
        self.setting_controls = controls = []
        for row, (label, variable, maximum) in enumerate((("Still image seconds", self.seconds, 3600),
                                                        ("Animated/video repeats", self.repeats, 100))):
            caption = self.label(self.form, label)
            caption.grid(row=row, column=0, sticky="w", padx=(0, 8))
            self.setting_labels.append(caption)
            control = tk.Spinbox(self.form, from_=1, to=maximum, textvariable=variable,
                                 width=8, bg=PANEL, fg=INK, buttonbackground=PANEL, insertbackground=INK)
            control.grid(row=row, column=1, sticky="ew", pady=1)
            controls.append(control)
        for row, label, variable, values in ((2, "Playback order", self.order, ("In Order", "Shuffle")),
                                             (3, "End of folder", self.loop, ("Loop Folder", "Return to Main Menu")),
                                             (4, "GIF uploads", self.convert_gifs, ("Convert to WebP", "Keep as GIF"))):
            caption = self.label(self.form, label)
            caption.grid(row=row, column=0, sticky="w", padx=(0, 8))
            self.setting_labels.append(caption)
            combo = ttk.Combobox(self.form, textvariable=variable, values=values, state="readonly", width=20)
            combo.grid(row=row, column=1, sticky="ew", pady=1)
            controls.append(combo)
        self.form.bind("<Configure>", self.layout_settings)
        self.settings_bottom.bind("<Configure>", self.layout_settings)
        self.show_settings_message("Applies when you start a collection.")
        self.layout_settings()
        controls[0].focus_set()

    def layout_settings(self, event=None):
        """Wrap long captions and keep the inline message inside its slot."""
        form = getattr(self, "form", None)
        if form is not None and form.winfo_width() > 1:
            control_width = max((control.winfo_reqwidth() for control in self.setting_controls),
                                default=160)
            left = max(96, form.winfo_width() - control_width - 12)
            for caption in self.setting_labels:
                if int(caption.cget("wraplength") or 0) != left:
                    caption.configure(wraplength=left)
        self.show_settings_message(self.settings_text)

    def show_settings_message(self, text):
        self.settings_text = text or ""
        label = getattr(self, "settings_message", None)
        if label is None:
            return
        width = self.settings_bottom.winfo_width() - self.save_button.winfo_reqwidth() - 14
        if width < 80:
            width = max(180, self.root.winfo_width() - 24 - self.save_button.winfo_reqwidth())
        display = self.clamp_text(self.settings_text, self.message_font, width, 2)
        label.configure(text=display, wraplength=width)

    def save_settings(self):
        if self.pending is not None:
            return
        try:
            data = {"image_seconds": int(self.seconds.get()), "repeats": int(self.repeats.get()),
                    "order": "ordered" if self.order.get() == "In Order" else "shuffle",
                    "loop": self.loop.get() == "Loop Folder",
                    "convert_gifs": self.convert_gifs.get() == "Convert to WebP"}
            from settings import validate
            validate(data)
        except ValueError as error:
            self.show_settings_message(str(error))
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
        self.hidden = False
        self.cid = cid
        self.clear()
        self.last_error = ""
        self.playlist = Playlist(items, self.services.settings.snapshot())
        # The focus ring makes keyboard focus visible before the first Tab.
        self.canvas = tk.Canvas(self.frame, bg="black", highlightthickness=2,
                                highlightbackground="black", highlightcolor=ACCENT, takefocus=True)
        self.canvas.pack(fill="both", expand=True)
        self.image_id = self.canvas.create_image(0, 0, anchor="center")
        self.canvas.bind("<ButtonRelease-1>", lambda event: self.show_controls())
        self.canvas.bind("<Configure>", self.center_frame)
        self.overlay = tk.Frame(self.frame, bg=PANEL)
        self.conversion_font = tkfont.Font(root=self.root, family="DejaVu Sans", size=-11)
        self.conversion_label = tk.Label(self.overlay, text="", bg=PANEL, fg=INK, anchor="w",
                                         font=self.conversion_font, justify="left")
        self.conversion_label.pack(side="bottom", fill="x", padx=4)
        controls = tk.Frame(self.overlay, bg=PANEL)
        self.button(controls, "‹ Previous", lambda: self.advance(-1)).pack(side="left", fill="both", expand=True)
        self.pause_button = self.button(controls, "Pause", self.pause)
        self.pause_button.pack(side="left", fill="both", expand=True)
        self.button(controls, "Next ›", self.advance).pack(side="left", fill="both", expand=True)
        self.convert_button = self.button(controls, "To WebP", self.convert_current)
        self.convert_button.pack(side="left", fill="both", expand=True)
        self.button(controls, "Back", self.escape).pack(side="left", fill="both", expand=True)
        controls.pack(side="top", fill="both", expand=True)
        self.canvas.focus_set()
        self.root.update_idletasks()
        self.open_gpu()
        self.advance()
        self.show_controls()

    def open_gpu(self):
        self.gpu_surface = tk.Frame(self.canvas, bg="black", takefocus=False)
        self.gpu_surface.place(x=0, y=0, relwidth=1, relheight=1)
        self.gpu_surface.bind("<ButtonRelease-1>", lambda event: self.show_controls())
        self.gpu_surface.bind("<Expose>", self.center_frame)
        self.root.update_idletasks()
        try:
            self.gpu_renderer = ImageRenderer(self.gpu_surface)
            print("event=media_renderer mode=hardware renderer=%r" % self.gpu_renderer.renderer, file=sys.stderr)
        except GpuUnavailable as error:
            self.close_gpu()
            print("event=media_renderer mode=tk reason=%r" % str(error), file=sys.stderr)

    def close_gpu(self):
        if self.gpu_renderer is not None:
            self.gpu_renderer.close()
            self.gpu_renderer = None
        if self.gpu_surface is not None:
            try:
                self.gpu_surface.destroy()
            except tk.TclError:
                pass  # The toplevel may already have been destroyed externally.
            self.gpu_surface = None

    def present_frame(self, frame):
        """Compose one already-decoded frame; no resizing or channel work per frame."""
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if frame.width > width or frame.height > height:
            # Only a mid-playback window resize reaches here; the decoder already
            # bounds every frame to the size it was asked for.
            frame = freeze(frame.image(), size=(width, height), mode=frame.mode)
        self.last_frame = frame
        if self.gpu_renderer is not None:
            try:
                self.gpu_renderer.present(frame, width, height)
                return
            except GpuUnavailable as error:
                print("event=media_renderer mode=tk reason=%r" % str(error), file=sys.stderr)
                self.close_gpu()
        self.show_photo(frame)

    def show_photo(self, frame):
        """Reuse one Tk photo image; only a changed frame shape rebuilds it."""
        shape = (frame.mode, frame.size)
        if self.photo is None or (self.photo_mode, self.photo_size) != shape:
            self.photo = ImageTk.PhotoImage(frame.image(), master=self.root)
            self.photo_mode, self.photo_size = frame.mode, frame.size
            self.canvas.itemconfigure(self.image_id, image=self.photo)
            self.canvas.coords(self.image_id, self.canvas.winfo_width() / 2,
                               self.canvas.winfo_height() / 2)
            return self.photo
        self.photo.paste(frame.image())
        return self.photo

    def center_frame(self, event=None):
        if self.screen == "playback":
            if self.gpu_renderer is not None:
                try:
                    self.gpu_renderer.repaint(self.canvas.winfo_width(), self.canvas.winfo_height())
                except GpuUnavailable:
                    self.close_gpu()
                    if self.last_frame is not None:
                        self.present_frame(self.last_frame)
            else:
                self.canvas.coords(self.image_id, self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2)

    def load_item(self, item):
        if item is None:
            message = self.last_error or "Collection finished."
            if self.playlist and len(self.playlist.bad) == len(self.playlist.items):
                message = "No playable media. " + (self.last_error or "Upload supported files.")
            self.home(message)
            return
        self.clock = PlaybackClock()
        self.starved = False
        # Animated WebP is paced like GIF; metadata marks both.
        self.animated = bool(item.get("animated", item["kind"] in ("gif", "webm")))
        self.last_frame = None
        if self.gpu_renderer is not None:
            try:
                self.gpu_renderer.clear()
            except GpuUnavailable:
                self.close_gpu()
        self.canvas.delete("error")
        self.canvas.itemconfigure(self.image_id, image="")
        self.photo = None
        self.generation = self.services.decoder.request(item,
            (self.canvas.winfo_width(), self.canvas.winfo_height()), self.playlist.settings,
            gpu=self.gpu_renderer is not None, upcoming=self.playlist.upcoming())
        self.pause_button.configure(text="Pause")
        # Keep the conversion action in step with the newly selected item.
        self.refresh_conversion_ui()
        self.wake_poll()

    def wake_poll(self):
        """Present a hand-loaded item without waiting out the previous timer.

        load_item() is normally reached from a click or keypress while a poll is
        still scheduled (up to the 250 ms pacing cap or 400 ms home heartbeat).
        Cancel it and re-arm promptly so the decoded frame appears immediately.
        From inside poll(), poll_id is already None and the schedule() at the end
        of poll owns pacing; there is nothing to cancel and no second timer.
        """
        if self.poll_id is None:
            return
        self.root.after_cancel(self.poll_id)
        self.poll_id = self.root.after(WAKE_MS, self.poll)

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

    def overlay_height(self):
        """Status line(s) plus a 42 px control row; buttons stay >= 36 px targets."""
        lines = max(1, getattr(self, "conversion_lines", 1) or 1)
        return 58 + (lines - 1) * self.conversion_font.metrics("linespace")

    def show_controls(self):
        if self.screen == "playback":
            self.refresh_conversion_ui()
            self.overlay.place(relx=0, rely=1, anchor="sw", relwidth=1, height=self.overlay_height())
            self.overlay.lift()
            self.overlay_visible = True
            self.overlay_until = time.monotonic() + 3

    def overlay_has_focus(self):
        """True while focus is anywhere inside the overlay, however deep."""
        focused = self.root.focus_get()
        while focused is not None:
            if focused is self.overlay:
                return True
            focused = getattr(focused, "master", None)
        return False

    def refresh_conversion_ui(self):
        if self.screen != "playback" or self.conversion_label is None:
            return
        item = self.playlist.current if self.playlist else None
        busy = self.conversion_running
        eligible = item is not None and needs_conversion(item)
        self.convert_button.configure(state="normal" if eligible and not busy else "disabled")
        if busy:
            text = self.conversion_message or "Converting…"
        elif self.conversion_message:
            text = self.conversion_message  # Success/failure stays readable, never a dead end.
        elif item is None:
            text = "Nothing to convert"
        elif not eligible:
            text = item["kind"].upper() + " is already in its native format"
        else:
            text = ""
        width = self.conversion_label.winfo_width()
        if width <= 1:
            width = max(160, self.root.winfo_width() - 16)
        # Clamp by measured pixels, not characters: a wrapped pair of lines
        # keeps long failures readable without overflowing the overlay.
        display = self.clamp_text(text, self.conversion_font, width, 2)
        self.conversion_lines = max(1, len(self.wrap_text(display, self.conversion_font, width)))
        self.conversion_label.configure(text=display, wraplength=width)
        if self.overlay_visible:
            self.overlay.place_configure(height=self.overlay_height())

    def convert_current(self):
        if self.screen != "playback" or not self.services:
            return
        item = self.playlist.current if self.playlist else None
        if item is None or not needs_conversion(item) or self.conversion_running:
            self.refresh_conversion_ui()
            return
        try:
            self.services.conversions.start(self.cid, item["id"])
        except ConversionError as error:
            self.conversion_message = str(error)
            self.refresh_conversion_ui()
            return
        self.conversion_running = True
        self.conversion_message = "Converting " + item["name"][:33] + "…"
        self.conversion_poll = 0.0
        self.refresh_conversion_ui()

    def convert_key(self, event):
        if self.screen == "playback":
            self.show_controls()
            self.convert_current()
            return "break"
        return None

    def track_conversion(self):
        if self.screen != "playback":
            return
        now = time.monotonic()
        if now < self.conversion_poll:
            return
        # One shared job: read the snapshot at most once per second, so a
        # conversion started from the web UI appears here too.
        self.conversion_poll = now + 1
        conversions = self.services.conversions if self.services else None
        if conversions is None:
            return
        snapshot = conversions.snapshot()
        status = snapshot["status"]
        job = snapshot.get("job") or {}
        total = job.get("total", 1) or 1
        if status == "running":
            self.conversion_running = True
            if total > 1:
                done = job.get("completed", 0) + job.get("failed", 0)
                self.conversion_message = "Converting %d/%d · %s" % (
                    done, total, (snapshot["name"] or "media")[:22])
            else:
                self.conversion_message = "Converting " + (snapshot["name"] or "media")[:33] + "…"
            self.refresh_conversion_ui()
            return
        self.conversion_running = False
        if status not in ("ready", "failed"):
            return
        signature = "%s:%s:%s:%s" % (status, job.get("id", 0), snapshot["item"],
                                     snapshot["replacement"])
        if signature == self.conversion_last:
            return
        self.conversion_last = signature
        self.conversion_finished(snapshot)
        if self.overlay_visible:
            self.refresh_conversion_ui()
        else:
            self.show_controls()  # Surface the finished message once.

    def conversion_finished(self, snapshot):
        job = snapshot.get("job") or {}
        if (job.get("total") or 1) > 1:
            # A batch reports totals; it does not move the slideshow position.
            self.conversion_message = (job.get("message") or snapshot["message"]
                                       or "Conversion finished")
            return
        current = self.playlist.current if self.playlist else None
        if snapshot["status"] != "ready":
            self.conversion_message = snapshot["message"] or "Conversion failed"
            return
        # The snapshot name is the already-renamed target; name the item the
        # user still sees when it matches, otherwise stay generic.
        if current is not None and snapshot["item"] == current["id"]:
            self.conversion_message = "Converted " + current["name"][:33] + " to WebP"
        else:
            self.conversion_message = "Converted to WebP"
        if (current is None or snapshot["item"] != current["id"] or self.cid is None
                or snapshot["collection"] != self.cid):
            return
        try:
            items = self.services.library.playlist(self.cid)
        except (KeyError, ValueError):
            return
        settings = self.services.settings.snapshot()
        playlist = Playlist(items, settings, rng=self.playlist.rng)
        target, item = snapshot["replacement"], None
        for _ in range(len(items) + 1):
            item = playlist.next()
            if item is None or item["id"] == target:
                break
        if item is None or item["id"] != target:
            # The replacement vanished; restart the collection at the first item.
            playlist = Playlist(items, settings, rng=self.playlist.rng)
            item = playlist.next()
        self.playlist = playlist
        self.load_item(item)

    def playback_tick(self):
        now = time.monotonic()
        # Focus queries stay off the hot path until the overlay is actually shown.
        if (self.overlay_visible and now > self.overlay_until and not self.clock.paused
                and not self.overlay_has_focus()):
            self.overlay.place_forget()
            self.overlay_visible = False
        if not self.clock.ready():
            self.starved = False
            return
        dropped = 0
        while True:
            try:
                generation, kind, value, seconds = self.services.decoder.events.get_nowait()
            except queue.Empty:
                # The deadline is due but the decoder has not caught up. Back the
                # poll off so the decode worker keeps the CPU it needs.
                self.starved = True
                return
            if generation != self.generation:
                continue
            if kind == "frame":
                if not self.animated:
                    self.starved = False
                    self.present_frame(value)
                    self.clock.arm(seconds)
                    return
                # Deadlines advance by the media's own durations, never by how
                # long decode or upload took, so playback cannot drift slower.
                self.clock.arm(seconds, continuous=True)
                if self.clock.late():
                    # This frame's whole display window has already passed: drop it
                    # and keep time, bounded so catch-up can never run away.
                    if dropped < MAX_CATCHUP:
                        dropped += 1
                        continue
                    self.clock.resync()
                self.starved = False
                self.present_frame(value)
                return
            if kind == "done":
                self.starved = False
                self.advance()
                return
            self.starved = False
            if kind == "error":
                self.last_error = value
                self.load_item(self.playlist.failed())
                if self.screen == "playback":
                    self.close_gpu()
                    self.show_controls()
                    self.canvas.delete("error")
                    self.canvas.create_text(8, 8, text="Skipped: " + value, anchor="nw",
                                            width=max(100, self.canvas.winfo_width() - 16),
                                            fill="#ffb7a8", font=("DejaVu Sans", -12),
                                            tags="error")
                return

    def schedule(self):
        if not self.finished:
            if self.screen == "playback":
                if self.hidden:
                    delay = 500  # Nothing visible: heartbeat only, no decode.
                else:
                    # Wait for the next frame deadline, then let the Tk timer land
                    # as close to it as the platform allows.
                    delay = max(4, self.clock.delay_ms())
                    if self.starved:
                        delay = max(delay, STARVED_MS)
            else:
                # Home/settings change slowly; closing still checks its job promptly.
                delay = 50 if self.screen == "closing" else 400
            self.poll_id = self.root.after(delay, self.poll)

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
                        self.home(result.library.warning or result.settings.warning
                                  or "Ready · select a collection to play")
                elif action == "settings" and not self.closing and self.screen == "settings":
                    self.show_settings_message(self.services.settings.warning
                                               or "Saved. Start a collection to apply.")
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
                        self.show_settings_message(str(error))
                        self.save_button.configure(state="normal")
                    else:
                        if action == "startup":
                            # Detail goes to the console; the UI stays friendly.
                            self.startup_failed = str(error)
                            print("event=startup status=failed reason=%r" % str(error), file=sys.stderr)
                        self.home()
        if self.closing:
            if self.pending is None:
                self.pending_action = "close"
                self.pending = self.executor.submit(self.services.close if self.services else lambda: None)
        elif self.screen == "playback":
            if not self.root.winfo_viewable():
                # Hidden/iconified playback must not decode or present; stop the
                # decoder once and idle at a slow heartbeat until shown again.
                if not self.hidden:
                    self.hidden = True
                    if self.services:
                        self.services.decoder.stop()
            else:
                if self.hidden:
                    self.hidden = False
                    self.load_item(self.playlist.current)
                if self.screen == "playback":  # load_item(None) returns home.
                    self.track_conversion()
                    self.playback_tick()
        elif self.screen == "home" and self.services:
            self.update_address()
            self.update_status()
            if self.revision != self.services.library.revision:
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
        # Release Tcl image handles on the UI thread before the interpreter dies.
        self.photo = self.qr_photo = self.icon = None
        self.root.destroy()

    def finish(self):
        self.close_gpu()
        # Handles an external mainloop quit as well as normal Home/WM close.
        error = self.close_error
        if not self.finished:
            if self.pending is not None:
                try:
                    result = self.pending.result(timeout=100)
                except Exception as failure:
                    error = error or str(failure)
                else:
                    if self.pending_action == "startup":
                        self.services = result
            if self.services is not None:
                try:
                    self.services.close()
                except Exception as failure:
                    # A failed startup or close must still release every other
                    # resource and let the process exit instead of leaking threads.
                    error = error or str(failure)
            self.finished = True
        try:
            self.executor.shutdown(wait=True)
        except Exception as failure:
            error = error or str(failure)
        if error:
            raise RuntimeError(error)
