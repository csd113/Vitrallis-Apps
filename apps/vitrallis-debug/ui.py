"""Canvas presentation and interaction model for Vitrallis Debug."""
from __future__ import annotations

from dataclasses import dataclass
import tkinter.font as tkfont
import queue
import threading
import time
from typing import Callable, Optional

from diagnostics import History, Snapshot, SystemCollector
from gpu import GpuUnavailable, PulseRenderer


PANELS = ("Network", "CPU", "Temperature", "Memory", "GPU")
PULSE_FOCUS, EXIT_FOCUS, BACK_FOCUS = 5, 6, 7
COLORS = {"Network": "#7ea9ef", "CPU": "#63d5c5", "GPU": "#a69aee",
          "Temperature": "#e2b75a", "Memory": "#6fb8e9"}
BACKGROUND = "#11161d"
CARD = "#1b2430"
CARD_FOCUS = "#24405b"
TEXT = "#eff5fa"
MUTED = "#aebdcb"
ACCENT = "#63d5c5"
WARN = "#e2b75a"
ERROR = "#d97979"


@dataclass
class PulseState:
    active: bool = False
    started: float = 0.0
    duration: float = 8.0

    def start(self, now: float) -> bool:
        if self.active:
            return False
        self.active, self.started = True, now
        return True

    def progress(self, now: float) -> float:
        return min(1.0, max(0.0, (now - self.started) / self.duration)) if self.active else 1.0

    def cancel(self) -> bool:
        was_active = self.active
        self.active = False
        return was_active


class InteractionModel:
    """Pure focus, gesture, scrolling and detail-view state for tests and UI."""
    def __init__(self) -> None:
        self.focus = 0
        self.expanded: Optional[int] = None
        self.origin_focus = 0
        self.pressed: Optional[str] = None
        self.scroll = 0
        self.pulse = PulseState()

    def open(self, index: int) -> None:
        self.origin_focus = index
        self.focus = BACK_FOCUS
        self.expanded = index
        self.scroll = 0

    def close(self) -> bool:
        if self.expanded is None:
            return False
        self.focus, self.expanded, self.scroll = self.origin_focus, None, 0
        return True

    def move(self, direction: str) -> None:
        if self.expanded is not None:
            if direction == "up": self.scroll = max(0, self.scroll - 36)
            if direction == "down": self.scroll += 36
            return
        neighbors = {
            0: {"down": 1},
            1: {"up": 0, "right": 4, "down": 2},
            4: {"up": 0, "left": 1, "down": 3},
            2: {"up": 1, "right": 3},
            3: {"up": 4, "left": 2},
        }
        self.focus = neighbors.get(self.focus, {}).get(direction, self.focus)

    def press(self, target: str) -> None:
        self.pressed = target

    def release(self, target: str) -> bool:
        match = self.pressed == target
        self.pressed = None
        return match


class Dashboard:
    def __init__(self, root, tk, collector: Optional[SystemCollector] = None,
                 clock: Callable[[], float] = time.monotonic, demo: bool = False,
                 renderer_factory=PulseRenderer) -> None:
        self.root, self.tk, self.collector, self.clock = root, tk, collector or SystemCollector(), clock
        self.canvas = tk.Canvas(root, background=BACKGROUND, highlightthickness=0, takefocus=True)
        self.canvas.pack(fill="both", expand=True)
        self.model = InteractionModel()
        self.snapshot: Optional[Snapshot] = None
        self.last_snapshot_at: Optional[float] = None
        self.cpu_history, self.temp_history, self.memory_history = History(), History(), History()
        self.temp_min: Optional[float] = None
        self.temp_max: Optional[float] = None
        self.temp_last_valid_at: Optional[float] = None
        self.stale_categories: set[str] = set()
        self.results: queue.Queue[Snapshot] = queue.Queue(maxsize=1)
        self.worker: Optional[threading.Thread] = None
        self.accept_results = True
        self.closed = False
        self.after_ids: set[str] = set()
        self.renderer_factory = renderer_factory
        self.renderer = None
        self.pulse_after = None
        self.pulse_error = ""
        self.renderer_name = "Not checked — select Pulse"
        self.renderer_api = "Not checked — select Pulse"
        self.gpu_history = History()
        self.gpu_source = None
        self.fonts = {}
        self.detail_canvas = tk.Canvas(root, background=BACKGROUND, highlightthickness=0)
        self.detail_canvas.bind("<MouseWheel>", self._wheel)
        self.detail_canvas.bind("<Button-4>", lambda event: self._scroll(-36))
        self.detail_canvas.bind("<Button-5>", lambda event: self._scroll(36))
        self.detail_canvas.bind("<Button-1>", lambda event: self.canvas.focus_set())
        self.pulse_layer = tk.Frame(root, background=BACKGROUND)
        self.pulse_surface = tk.Frame(self.pulse_layer, background=BACKGROUND)
        self.pulse_surface.pack(fill="both", expand=True)
        self.pulse_caption = tk.Label(self.pulse_layer, background=BACKGROUND, foreground=MUTED,
                                     font=("TkDefaultFont", -11))
        self.pulse_caption.pack(fill="x", pady=(6, 0))
        self.demo = demo
        self._bind()
        self._render()
        self._schedule(0, self._tick)

    def _bind(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.canvas.bind("<Configure>", lambda event: self._render())
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda event: self._scroll(-36))
        self.canvas.bind("<Button-5>", lambda event: self._scroll(36))
        self.canvas.bind("<Key>", self._key)
        self.canvas.focus_set()
        self.root.bind("<Unmap>", self._hidden, add="+")

    def _hidden(self, event) -> None:
        if event.widget == self.root and self.model.pulse.cancel():
            self._clear_pulse()

    def _schedule(self, delay: int, callback) -> Optional[str]:
        if not self.closed:
            holder: list[str] = []
            def run() -> None:
                if holder:
                    self.after_ids.discard(holder[0])
                callback()
            ident = self.root.after(delay, run)
            holder.append(ident)
            self.after_ids.add(ident)
            return ident

    def _tick(self) -> None:
        if self.closed:
            return
        if not self._drain_results() and self.snapshot is not None:
            for history in (self.cpu_history, self.gpu_history, self.temp_history, self.memory_history):
                history.add(None)
        if self.worker is None or not self.worker.is_alive():
            self.worker = threading.Thread(target=self._collect_once, name="vitrallis-metrics", daemon=True)
            self.worker.start()
        self._render()
        self._schedule(1000, self._tick)

    def _collect_once(self) -> None:
        try:
            sample = self.collector.collect()
            if self.accept_results:
                try:
                    self.results.put_nowait(sample)
                except queue.Full:
                    try: self.results.get_nowait()
                    except queue.Empty: pass
                    try: self.results.put_nowait(sample)
                    except queue.Full: pass
        except Exception:  # A category failure must never take down the display.
            pass

    def _drain_results(self) -> bool:
        newest = None
        while True:
            try: newest = self.results.get_nowait()
            except queue.Empty: break
        if newest is not None:
            if self.snapshot is not None:
                if newest.memory is None and self.snapshot.memory is not None:
                    newest.memory = self.snapshot.memory
                    self.stale_categories.add("memory")
                else:
                    self.stale_categories.discard("memory")
                if newest.network is None and self.snapshot.network is not None:
                    newest.network = self.snapshot.network
                    self.stale_categories.add("network")
                else:
                    self.stale_categories.discard("network")
            self.snapshot, self.last_snapshot_at = newest, self.clock()
            self.cpu_history.add(newest.cpu_percent)
            current_temp = next((item.celsius for item in newest.sensors if item.selected), None)
            self.temp_history.add(current_temp)
            if current_temp is not None:
                self.temp_min = current_temp if self.temp_min is None else min(self.temp_min, current_temp)
                self.temp_max = current_temp if self.temp_max is None else max(self.temp_max, current_temp)
                self.temp_last_valid_at = self.clock()
            self.memory_history.add(newest.memory.percent if newest.memory and "memory" not in self.stale_categories else None)
            source = (newest.gpu.name, newest.gpu.source) if newest.gpu else self.gpu_source
            if source != self.gpu_source:
                self.gpu_history = History()
                self.gpu_source = source
            self.gpu_history.add(newest.gpu.percent if newest.gpu else None)
        return newest is not None

    def _bounds(self) -> dict[str, tuple[float, float, float, float]]:
        width, height = max(400, self.canvas.winfo_width()), max(240, self.canvas.winfo_height())
        pad, gap = 10, 8
        bottom = height - 50
        network_h = 42
        top = 34 + network_h + gap
        card_w, card_h = (width - 2 * pad - gap) / 2, (bottom - top - gap) / 2
        bounds = {"exit": (pad, height - 42, 112, height - 6),
                  "pulse": (width - 116, height - 42, width - pad, height - 6),
                  "Network": (pad, 34, width - pad, 34 + network_h)}
        for index, name in enumerate(("CPU", "GPU", "Temperature", "Memory")):
            row, col = divmod(index, 2)
            x, y = pad + col * (card_w + gap), top + row * (card_h + gap)
            bounds[name] = (x, y, x + card_w, y + card_h)
        return bounds

    @staticmethod
    def _inside(box, x, y) -> bool:
        return box[0] <= x <= box[2] and box[1] <= y <= box[3]

    def _target(self, x, y) -> Optional[str]:
        bounds = self._bounds()
        if self.model.pulse.active:
            return next((name for name in ("exit", "pulse") if self._inside(bounds[name], x, y)), None)
        if self.model.expanded is not None:
            return "back" if self._inside((10, 8, 90, 42), x, y) else "exit" if self._inside(bounds["exit"], x, y) else "pulse" if self._inside(bounds["pulse"], x, y) else None
        for name in (*PANELS, "exit", "pulse"):
            if self._inside(bounds[name], x, y): return name
        return None

    def _press(self, event) -> None:
        target = self._target(event.x, event.y)
        self.canvas.focus_set()
        if target: self.model.press(target)

    def _release(self, event) -> None:
        target = self._target(event.x, event.y)
        if target and self.model.release(target): self._activate(target)
        else: self.model.pressed = None

    def _activate(self, target: str) -> None:
        if target in PANELS: self.model.open(PANELS.index(target))
        elif target == "back": self.model.close()
        elif target == "exit": self.close()
        elif target == "pulse":
            if self.model.pulse.cancel():
                self._clear_pulse()
            elif self.model.pulse.start(self.clock()):
                self._begin_pulse()
        self._render()

    def _key(self, event) -> str | None:
        key = event.keysym
        if key == "Escape":
            if self.model.pulse.cancel(): self._clear_pulse(); self._render()
            elif self.model.close(): self._render()
            else: self.close()
            return "break"
        if key in ("Up", "Down", "Left", "Right"):
            self.model.move(key.lower()); self._render(); return "break"
        if key in ("Prior",): self._scroll(-108); return "break"
        if key in ("Next",): self._scroll(108); return "break"
        if key in ("Tab", "ISO_Left_Tab"):
            choices = ([PULSE_FOCUS, EXIT_FOCUS] if self.model.pulse.active else
                       [BACK_FOCUS, PULSE_FOCUS, EXIT_FOCUS] if self.model.expanded is not None else
                       [0, 1, 4, 2, 3, PULSE_FOCUS, EXIT_FOCUS])
            index = choices.index(self.model.focus) if self.model.focus in choices else 0
            self.model.focus = choices[(index + (-1 if event.state & 1 or key == "ISO_Left_Tab" else 1)) % len(choices)]
            self._render()
            return "break"
        if key in ("Return", "KP_Enter", "space"):
            if self.model.focus == EXIT_FOCUS: self._activate("exit")
            elif self.model.focus == PULSE_FOCUS: self._activate("pulse")
            elif self.model.pulse.active: return "break"
            elif self.model.expanded is not None: self._activate("back")
            elif self.model.focus < len(PANELS): self._activate(PANELS[self.model.focus])
            return "break"
        return None

    def _wheel(self, event) -> None:
        self._scroll(-36 if event.delta > 0 else 36)

    def _scroll(self, amount: int) -> None:
        if self.model.expanded is not None:
            self.model.scroll = max(0, self.model.scroll + amount); self._render()

    def _font(self, size, bold=False):
        key = size, bold
        if key not in self.fonts:
            self.fonts[key] = tkfont.Font(root=self.root, family="DejaVu Sans", size=-size,
                                          weight="bold" if bold else "normal")
        return self.fonts[key]

    def _text(self, x, y, text, width, size=12, color=TEXT, bold=False, anchor="nw", canvas=None):
        target = canvas if canvas is not None else self.canvas
        font = self._font(size, bold)
        text = " ".join(str(text).split())
        if font.measure(text) > width:
            low, high = 0, len(text)
            while low < high:
                middle = (low + high + 1) // 2
                if font.measure(text[:middle] + "…") <= width: low = middle
                else: high = middle - 1
            text = text[:low] + "…"
        return target.create_text(x, y, tags="dashboard", text=text, font=font,
                                  fill=color, anchor=anchor)

    def _button(self, box, label, focused=False) -> None:
        self.canvas.create_rectangle(*box, tags="dashboard", fill=CARD_FOCUS if focused else CARD,
                                     outline=ACCENT if focused else "#344253", width=2 if focused else 1)
        self._text((box[0]+box[2])/2, (box[1]+box[3])/2, label, box[2]-box[0]-12,
                   size=12, bold=True, anchor="center")

    def _render(self) -> None:
        if self.closed: return
        self.canvas.delete("dashboard")
        if self.model.pulse.active:
            self.detail_canvas.place_forget()
            self._text(10, 10, "GPU PULSE", 200, size=13, color=ACCENT, bold=True)
            self._text(self.canvas.winfo_width()-10, 10, "DEMO" if self.demo else "HARDWARE", 120,
                       size=10, color=WARN if self.demo else MUTED, anchor="ne")
            self.pulse_layer.place(x=10, y=34, width=max(1, self.canvas.winfo_width()-20),
                                   height=max(1, self.canvas.winfo_height()-84))
            self.pulse_layer.lift()
        elif self.model.expanded is None:
            self.detail_canvas.place_forget()
            self._overview()
        else:
            self._details()
        self._draw_controls()

    def _draw_controls(self) -> None:
        bounds = self._bounds()
        self._button(bounds["exit"], "Home / Exit", self.model.focus == EXIT_FOCUS)
        self._button(bounds["pulse"], "Stop Pulse" if self.model.pulse.active else "GPU Pulse",
                     self.model.focus == PULSE_FOCUS)
        status = "8 s · Esc to stop" if self.model.pulse.active else "↑ / ↓ to scroll" if self.model.expanded is not None else "Select a card for details"
        if self.pulse_error: status = "Pulse unavailable"
        self._text(self.canvas.winfo_width()/2, self.canvas.winfo_height()-24, status,
                   self.canvas.winfo_width()-250, size=11, color=MUTED, anchor="center")

    def _overview(self) -> None:
        width = max(400, self.canvas.winfo_width())
        self._text(10, 9, "VITRALLIS  /  DEBUG", width-175, size=13, bold=True)
        stale = self.last_snapshot_at is not None and self.clock()-self.last_snapshot_at >= 3
        status = "DEMO · FIXTURE DATA" if self.demo else "STALE" if stale else "LOCAL · LIVE" if self.snapshot else "COLLECTING"
        self._text(width-10, 10, status, 155, size=10, color=WARN if self.demo or stale else ACCENT, anchor="ne")
        for index, name in enumerate(PANELS):
            x1, y1, x2, y2 = self._bounds()[name]
            color = COLORS[name]
            self.canvas.create_rectangle(x1, y1, x2, y2, tags="dashboard",
                                         fill=CARD_FOCUS if self.model.focus == index else CARD,
                                         outline=color if self.model.focus == index else "#2c3949",
                                         width=2 if self.model.focus == index else 1)
            value, detail = self._panel_summary(name)
            if name.lower() in self.stale_categories:
                detail = "STALE · " + detail.replace(" • STALE", "")
            if name == "Network":
                self._text(x1+12, y1+14, "NETWORK", 78, size=10, color=color, bold=True)
                self._text(x1+102, y1+5, value, x2-x1-122, size=14, bold=True)
                self._text(x1+102, y1+24, detail, x2-x1-122, size=10, color=MUTED)
                continue
            compact = y2-y1 < 80
            tiny = y2-y1 < 60
            graph_w = min(150, (x2-x1)*.34)
            value_w = x2-x1-graph_w-36
            self._text(x1+12, y1+(4 if tiny else 7), name.upper(), x2-x1-40, size=9 if tiny else 10, color=color, bold=True)
            self._text(x2-10, y1+6, "›", 12, size=14, color=MUTED, anchor="ne")
            self._text(x1+12, y1+(17 if tiny else 22), value, value_w, size=16 if tiny else 20 if compact else 26, bold=True)
            self._text(x1+12, y2-(12 if tiny else 17), detail, x2-x1-24, size=9 if tiny else 10 if compact else 12, color=MUTED)
            self._sparkline(x2-graph_w-12, y1+(21 if tiny else 25), x2-12, y2-(18 if tiny else 24),
                            self._history(name), color, percent=name != "Temperature")

    def _panel_summary(self, name: str) -> tuple[str, str]:
        sample = self.snapshot
        stale = "" if self.last_snapshot_at is None or self.clock() - self.last_snapshot_at < 3 else " • STALE"
        if not sample: return "Collecting…", "Initial data collection" + stale
        if name == "Network":
            item = sample.network.primary if sample.network else None
            if not item: return "No local address", "Open details for network status" + stale
            address = (item.addresses_v4 + item.addresses_v6)[0]
            return address, f"{item.name} • {item.state}" + stale + (" • STALE" if "network" in self.stale_categories else "")
        if name == "CPU":
            usage = ("—" if "cpu" in sample.errors else "Collecting…") if sample.cpu_percent is None else f"{sample.cpu_percent:.1f}%"
            return usage, sample.cpu_model + stale
        if name == "GPU":
            model = sample.hardware.gpu_name(sample.gpu.name if sample.gpu else None)
            return (f"{sample.gpu.percent:.1f}%" if sample.gpu else "—", model + stale)
        if name == "Temperature":
            sensor = next((item for item in sample.sensors if item.selected), None)
            return (f"{sensor.celsius:.1f} °C", sensor.label + stale) if sensor else ("—", "No readable sensor" + stale)
        memory = sample.memory
        return (f"{memory.percent:.1f}%", f"{memory.used_kib/1024:.0f} / {memory.total_kib/1024:.0f} MiB" + (" • estimated" if memory.estimated else "") + stale + (" • STALE" if "memory" in self.stale_categories else "")) if memory else ("—", sample.errors.get("memory", "Memory data unavailable") + stale)

    def _history(self, name: str) -> tuple[Optional[float], ...]:
        return {"GPU": self.gpu_history.items(), "CPU": self.cpu_history.items(), "Temperature": self.temp_history.items(), "Memory": self.memory_history.items()}.get(name, ())

    def _sparkline(self, x1, y1, x2, y2, values, color, percent=True, canvas=None) -> None:
        target = canvas if canvas is not None else self.canvas
        for fraction in (0, .5, 1):
            y = y2 - (y2-y1)*fraction
            target.create_line(x1, y, x2, y, fill="#2e3e4f", tags="dashboard")
        valid = [value for value in values if value is not None]
        if not valid: return
        low, high = (0, 100) if percent else (min(valid)-1, max(valid)+1)
        points = []
        for index, value in enumerate(values):
            if value is None:
                if len(points) >= 4: target.create_line(*points, fill=color, width=2, tags="dashboard")
                points = []
                continue
            # Fixed 60-sample window, newest at the right; gaps retain their place.
            x = x2 - (x2-x1)*(len(values)-1-index)/59
            y = y2 - (y2-y1)*(max(low, min(high, value))-low)/(high-low)
            points.extend((x, y))
            if index == len(values)-1:
                target.create_oval(x-2, y-2, x+2, y+2, fill=color, outline="", tags="dashboard")
        if len(points) >= 4: target.create_line(*points, fill=color, width=2, tags="dashboard")

    def _details(self) -> None:
        name = PANELS[self.model.expanded or 0]
        self._button((10, 8, 90, 42), "‹ Back", self.model.focus == BACK_FOCUS)
        self._text(104, 17, name, self.canvas.winfo_width()-240, size=18, bold=True)
        self._text(self.canvas.winfo_width()-12, 22, "DEMO" if self.demo else "DETAILS", 100,
                   size=10, color=WARN if self.demo else MUTED, anchor="e")
        width, height = max(360, self.canvas.winfo_width()-20), max(120, self.canvas.winfo_height()-102)
        target = self.detail_canvas
        target.place(x=10, y=48, width=width, height=height)
        target.delete("all")
        y = 8
        if name in ("CPU", "GPU", "Memory", "Temperature") and not (name == "GPU" and self.pulse_error):
            self._text(10, y, "RECENT UTILIZATION · 0–100%" if name != "Temperature" else "RECENT TEMPERATURE · °C",
                       width-24, size=10, color=COLORS[name], bold=True, canvas=target)
            self._sparkline(12, y+26, width-18, y+82, self._history(name), COLORS[name],
                            percent=name != "Temperature", canvas=target)
            y += 92
            self._text(12, y, "60 samples", width/2, size=10, color=MUTED, canvas=target)
            self._text(width-18, y, "latest", width/2, size=10, color=MUTED, anchor="ne", canvas=target)
            y += 30
        lines = self._detail_lines(name)
        if name == "GPU" and self.pulse_error:
            lines.insert(0, ("Pulse unavailable", self.pulse_error))
        if name.lower() in self.stale_categories or (self.last_snapshot_at is not None and self.clock()-self.last_snapshot_at >= 3):
            lines.insert(0, ("STALE DATA", "The latest refresh failed. Values below may be out of date."))
        for heading, content in lines:
            item = target.create_text(12, y, anchor="nw", width=width-36, text=heading,
                                      fill=COLORS[name], font=self._font(12, True))
            y = target.bbox(item)[3] + 5
            item = target.create_text(12, y, anchor="nw", width=width-36, text=content,
                                      fill=TEXT, font=self._font(14), justify="left")
            y = target.bbox(item)[3] + 14
            target.create_line(12, y-5, width-18, y-5, fill="#293746")
        total = max(height, y+4)
        self.model.scroll = min(max(0, self.model.scroll), max(0, total-height))
        target.configure(scrollregion=(0, 0, width, total))
        target.yview_moveto(self.model.scroll/total)
        if total > height:
            bar_y = 48 + (height-4)*self.model.scroll/total
            self.canvas.create_rectangle(self.canvas.winfo_width()-6, bar_y,
                                         self.canvas.winfo_width()-3, bar_y+(height-4)*height/total,
                                         fill="#637c94", outline="", tags="dashboard")

    @staticmethod
    def _driver_text(driver) -> str:
        if driver is None:
            return "No readable bound driver link"
        return (f"{driver.name}\nSource: {driver.source}\nModule: {driver.module or 'not exported'}"
                f"\nModule version: {driver.version or 'not exported'}" +
                (f"\nSource version ID: {driver.srcversion}" if driver.srcversion else ""))

    def _device_lines(self, label, devices) -> list[tuple[str, str]]:
        lines = []
        for index, device in enumerate(devices, start=1):
            prefix = f"{label} {index}"
            lines.append((prefix, device.name))
            lines.append((f"{prefix} driver", self._driver_text(device.driver)))
            lines.append((f"{prefix} identity", f"Source: {device.source}\nDevice: {device.identifier or 'unavailable'}" +
                          ("\nNodes: " + ", ".join(device.aliases) if device.aliases else "") +
                          ("\nCompatible: " + ", ".join(device.compatibles) if device.compatibles else "")))
        return lines

    def _detail_lines(self, name: str) -> list[tuple[str, str]]:
        sample = self.snapshot
        if name == "GPU" and sample is None:
            return [("Pulse status", self.pulse_error or "Select GPU Pulse to check hardware acceleration."),
                    ("Utilization", "Collecting initial diagnostics")]
        if not sample: return [("Status", "Collecting initial diagnostics. Values will appear when a complete local sample is available.")]
        if name == "Network":
            network = sample.network
            if not network: return [("Status", sample.errors.get("network", "Network details unavailable"))]
            lines = [("Hostname", network.hostname), ("Default route", f"{network.default_interface or 'none'} • gateway {network.gateway or 'unavailable'}")]
            for item in network.interfaces:
                addresses = "; ".join((*item.addresses_v4, *item.addresses_v6)) or "no configured addresses"
                counts = f" • RX {item.rx_bytes} B / TX {item.tx_bytes} B" if item.rx_bytes is not None and item.tx_bytes is not None else ""
                lines.append((f"{item.name} ({item.state})", addresses + counts))
            return lines or [("Status", "No interfaces reported")]
        if name == "GPU":
            reading = sample.gpu
            identities = self._device_lines("GPU", sample.hardware.gpus)
            identities += self._device_lines("Display", sample.hardware.displays)
            modules = "\n".join(self._driver_text(item) for item in sample.hardware.graphics_modules)
            return (identities or [("GPU model", "Hardware name unavailable")]) + [
                    ("Kernel", sample.hardware.kernel_release or "Unavailable"),
                    ("Graphics modules present", (modules + "\nPresence alone does not prove a device is bound.") if modules else "No module metadata exported"),
                    ("Utilization", f"{reading.percent:.1f}%" if reading else "Unavailable — this driver has no supported utilization counter."),
                    ("Sampled device", sample.hardware.gpu_name(reading.name) if reading else "No counter selected"),
                    ("Counter source", reading.source if reading else sample.errors.get("gpu", "No readable GPU counter")),
                    ("Pulse renderer", self.renderer_name),
                    ("OpenGL ES / userspace driver", self.renderer_api),
                    ("Pulse status", self.pulse_error or "Eight-second hardware pulse. Select GPU Pulse to run; Esc or Stop Pulse cancels."),
                    ("Measurement", "The graph shows device utilization, not animation FPS. GPU acceleration and utilization counters are separate driver capabilities.")]
        if name == "CPU":
            lines = [("Model", sample.cpu_model),
                     ("Identification source", "\n".join(dict.fromkeys(device.source for device in sample.hardware.cpus)) or "Unavailable"), ("Architecture / logical CPUs", f"{sample.architecture or 'unavailable'} • {sample.cpu_count} logical CPUs"),
                     ("Utilization", "Collecting initial delta" if sample.cpu_percent is None else f"{sample.cpu_percent:.1f}%"),
                     ("Live frequency", "Unavailable" if not sample.frequency else f"{sample.frequency.mhz:.1f} MHz ({sample.frequency.source}, {sample.frequency.path})"),
                     ("Per-core utilization", ", ".join(f"{key}: {'—' if value is None else f'{value:.1f}%'}" for key, value in sample.per_core.items()) or "Unavailable"),
                     ("Governor", ", ".join(sample.governors) or "Unavailable"),
                     ("Load / uptime", (f"load {sample.load_averages[0]:.2f}, {sample.load_averages[1]:.2f}, {sample.load_averages[2]:.2f}" if sample.load_averages else "load unavailable") + (f" • uptime {sample.uptime_seconds/3600:.1f} h" if sample.uptime_seconds is not None else ""))]
            for label, device in (("Board", sample.hardware.board), ("SoC", sample.hardware.soc)):
                lines.append((label, f"{device.name}\nSource: {device.source}" +
                              ("\nCompatible: " + ", ".join(device.compatibles) if device.compatibles else "")
                              if device else "Unavailable"))
            lines.append(("Kernel", sample.hardware.kernel_release or "Unavailable"))
            lines.append(("CPU frequency driver", "\n".join(f"{item.name} ({item.source})" for item in sample.hardware.cpu_drivers) or "Unavailable"))
            lines.extend((f"{policy} limits", f"min {low if low else '—'} MHz • max {high if high else '—'} MHz") for policy, low, high in sample.frequency_limits)
            return lines
        if name == "Temperature":
            if not sample.sensors: return [("Status", "No suitable thermal or hwmon sensor is readable. This is supported and does not affect other panels.")]
            age = "unavailable" if self.temp_last_valid_at is None else f"{max(0, self.clock() - self.temp_last_valid_at):.1f}s ago"
            session = "collecting" if self.temp_min is None or self.temp_max is None else f"min {self.temp_min:.1f} °C • max {self.temp_max:.1f} °C"
            return [("Selected", next((f"{item.label}: {item.celsius:.1f} °C ({item.path})" for item in sample.sensors if item.selected), "Unavailable")), ("Session range / last valid", f"{session} • {age}")] + [(f"{item.label} / {item.kind}", f"{item.celsius:.1f} °C • source {item.path}" + (f" • critical {item.critical_celsius:.1f} °C" if item.critical_celsius is not None else "")) for item in sample.sensors]
        memory = sample.memory
        if not memory: return [("Status", sample.errors.get("memory", "Memory data unavailable"))]
        swap_used = max(0, (memory.swap_total_kib or 0) - (memory.swap_free_kib or 0))
        return [("RAM", f"used {memory.used_kib/1024:.1f} MiB • total {memory.total_kib/1024:.1f} MiB • {memory.percent:.1f}%"), ("Availability", f"available {memory.available_kib/1024:.1f} MiB" + (" (estimated fallback)" if memory.estimated else "")), ("Components", f"free {memory.free_kib or 0} KiB • buffers {memory.buffers_kib or 0} KiB • cache {memory.cache_kib or 0} KiB"), ("Swap", f"used {swap_used/1024:.1f} MiB • total {(memory.swap_total_kib or 0)/1024:.1f} MiB • free {(memory.swap_free_kib or 0)/1024:.1f} MiB")]

    def _begin_pulse(self) -> None:
        self.pulse_error = ""
        self.model.focus = PULSE_FOCUS
        self._render()
        self.root.update_idletasks()
        try:
            if self.renderer is None:
                self.renderer = self.renderer_factory(self.pulse_surface)
                self.renderer_name = self.renderer.renderer
                self.renderer_api = getattr(self.renderer, "api_version", "Not exported")
            self.model.pulse.started = self.clock()
            self.pulse_caption.configure(text="8 SECOND PULSE  ·  HARDWARE GLES2  ·  ESC TO STOP")
            self._pulse_frame()
        except GpuUnavailable as error:
            self._pulse_failed(error)

    def _pulse_failed(self, error) -> None:
        self.pulse_error = str(error)
        self.model.pulse.cancel()
        self._clear_pulse()
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
        self.model.open(PANELS.index("GPU"))
        self._render()

    def _pulse_frame(self) -> None:
        self.pulse_after = None
        if self.closed or not self.model.pulse.active: return
        if self.model.pulse.progress(self.clock()) >= 1.0:
            self.model.pulse.cancel()
            self._clear_pulse()
            self._render()
            return
        if self.root.state() == "iconic":
            self.model.pulse.cancel()
            self._clear_pulse()
            return
        try:
            if self.renderer is not None:
                self.renderer.draw(self.clock()-self.model.pulse.started,
                                   self.pulse_surface.winfo_width(), self.pulse_surface.winfo_height())
        except GpuUnavailable as error:
            self._pulse_failed(error)
            return
        # At most 30 FPS. Schedule after submission, never catch up in a busy loop.
        self.pulse_after = self._schedule(34, self._pulse_frame)

    def _clear_pulse(self) -> None:
        if self.pulse_after is not None:
            self.root.after_cancel(self.pulse_after)
            self.after_ids.discard(self.pulse_after)
            self.pulse_after = None
        self.pulse_layer.place_forget()

    def close(self) -> None:
        if self.closed: return
        self.closed, self.accept_results = True, False
        self.model.pulse.cancel(); self._clear_pulse()
        for ident in tuple(self.after_ids):
            try: self.root.after_cancel(ident)
            except Exception: pass
        self.after_ids.clear()
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
        self.root.destroy()
