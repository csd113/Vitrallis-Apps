"""Canvas presentation and interaction model for Vitrallis Debug."""
from __future__ import annotations

from dataclasses import dataclass
import math
import queue
import threading
import time
from typing import Callable, Optional

from diagnostics import History, Snapshot, SystemCollector


PANELS = ("Network", "CPU", "Temperature", "Memory")
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
    duration: float = 2.0

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
        self.focus = 6
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
        row, column = divmod(min(self.focus, 3), 2)
        if direction == "left": column = max(0, column - 1)
        elif direction == "right": column = min(1, column + 1)
        elif direction == "up": row = max(0, row - 1)
        elif direction == "down": row = min(1, row + 1)
        self.focus = row * 2 + column if self.focus < 4 else self.focus

    def press(self, target: str) -> None:
        self.pressed = target

    def release(self, target: str) -> bool:
        match = self.pressed == target
        self.pressed = None
        return match


class Dashboard:
    def __init__(self, root, tk, collector: Optional[SystemCollector] = None,
                 clock: Callable[[], float] = time.monotonic, demo: bool = False) -> None:
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
        self.pulse_items: list[int] = []
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

    def _schedule(self, delay: int, callback) -> None:
        if not self.closed:
            holder: list[str] = []
            def run() -> None:
                if holder:
                    self.after_ids.discard(holder[0])
                callback()
            ident = self.root.after(delay, run)
            holder.append(ident)
            self.after_ids.add(ident)

    def _tick(self) -> None:
        if self.closed:
            return
        self._drain_results()
        if self.worker is None or not self.worker.is_alive():
            self.worker = threading.Thread(target=self._collect_once, name="vitrallis-metrics", daemon=True)
            self.worker.start()
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

    def _drain_results(self) -> None:
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
            self.memory_history.add(newest.memory.percent if newest.memory else None)
            self._render()

    def _bounds(self) -> dict[str, tuple[float, float, float, float]]:
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        pad, gap, controls = 10, 8, 42
        content_top, content_bottom = pad, height - controls - pad
        card_w, card_h = (width - 2 * pad - gap) / 2, (content_bottom - content_top - gap) / 2
        bounds = {"exit": (pad, height - controls, 100, height - 8),
                  "pulse": (width - 110, height - controls, width - pad, height - 8)}
        for index, name in enumerate(PANELS):
            row, col = divmod(index, 2)
            x = pad + col * (card_w + gap); y = content_top + row * (card_h + gap)
            bounds[name] = (x, y, x + card_w, y + card_h)
        return bounds

    @staticmethod
    def _inside(box, x, y) -> bool:
        return box[0] <= x <= box[2] and box[1] <= y <= box[3]

    def _target(self, x, y) -> Optional[str]:
        bounds = self._bounds()
        if self.model.expanded is not None:
            return "back" if self._inside((10, 8, 90, 42), x, y) else "exit" if self._inside(bounds["exit"], x, y) else "pulse" if self._inside(bounds["pulse"], x, y) else None
        for name in (*PANELS, "exit", "pulse"):
            if self._inside(bounds[name], x, y): return name
        return None

    def _press(self, event) -> None:
        target = self._target(event.x, event.y)
        if target: self.model.press(target)

    def _release(self, event) -> None:
        target = self._target(event.x, event.y)
        if target and self.model.release(target): self._activate(target)
        else: self.model.pressed = None

    def _activate(self, target: str) -> None:
        if target in PANELS: self.model.open(PANELS.index(target))
        elif target == "back": self.model.close()
        elif target == "exit": self.close()
        elif target == "pulse" and self.model.pulse.start(self.clock()): self._begin_pulse()
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
        if key == "Tab":
            if self.model.expanded is None:
                self.model.focus = (self.model.focus + (-1 if event.state & 1 else 1)) % 6
                self._render()
            return "break"
        if key in ("Return", "KP_Enter", "space"):
            if self.model.expanded is not None: self._activate("back" if self.model.focus == 6 else "pulse")
            elif self.model.focus < 4: self._activate(PANELS[self.model.focus])
            elif self.model.focus == 4: self._activate("pulse")
            else: self._activate("exit")
            return "break"
        return None

    def _wheel(self, event) -> None:
        self._scroll(-36 if event.delta > 0 else 36)

    def _scroll(self, amount: int) -> None:
        if self.model.expanded is not None:
            self.model.scroll = max(0, self.model.scroll + amount); self._render()

    def _button(self, box, label, focused=False, enabled=True) -> None:
        fill = CARD_FOCUS if focused else "#263342"
        if not enabled: fill = "#29313b"
        self.canvas.create_rectangle(*box, tags="dashboard", fill=fill, outline=ACCENT if focused else "#405164", width=2 if focused else 1)
        self.canvas.create_text((box[0]+box[2])/2, (box[1]+box[3])/2, tags="dashboard", text=label, fill=TEXT, font=("TkDefaultFont", 12, "bold"))

    def _render(self) -> None:
        if self.closed: return
        self.canvas.delete("dashboard")
        if self.model.expanded is None: self._overview()
        else: self._details()
        self._draw_controls()
        if self.model.pulse.active and self.pulse_items: self._update_pulse()

    def _draw_controls(self) -> None:
        bounds = self._bounds()
        self._button(bounds["exit"], "Home / Exit", self.model.focus == 5)
        self._button(bounds["pulse"], "Pulse" if not self.model.pulse.active else "Pulsing…", self.model.focus == 4, not self.model.pulse.active)

    def _overview(self) -> None:
        if self.demo:
            self.canvas.create_text(self.canvas.winfo_width() / 2, 5, tags="dashboard", anchor="n", text="DEMO DATA — not live diagnostics", fill=WARN, font=("TkDefaultFont", 9, "bold"))
        for index, name in enumerate(PANELS):
            box = self._bounds()[name]
            self.canvas.create_rectangle(*box, tags="dashboard", fill=CARD_FOCUS if self.model.focus == index else CARD, outline=ACCENT if self.model.focus == index else "#304152", width=2 if self.model.focus == index else 1)
            self.canvas.create_text(box[0]+12, box[1]+13, tags="dashboard", anchor="w", text=name.upper(), fill=ACCENT, font=("TkDefaultFont", 10, "bold"))
            value, detail = self._panel_summary(name)
            self.canvas.create_text(box[0]+12, box[1]+41, tags="dashboard", anchor="w", text=value, fill=TEXT, font=("TkDefaultFont", 17, "bold"))
            self.canvas.create_text(box[0]+12, box[1]+69, tags="dashboard", anchor="w", width=max(80, box[2]-box[0]-24), text=detail, fill=MUTED, font=("TkDefaultFont", 10))
            self._sparkline(box[0]+12, box[3]-24, box[2]-12, box[3]-9, self._history(name), ACCENT)

    def _panel_summary(self, name: str) -> tuple[str, str]:
        sample = self.snapshot
        stale = "" if self.last_snapshot_at is None or self.clock() - self.last_snapshot_at < 3 else " • STALE"
        if not sample: return "Collecting…", "Initial data collection" + stale
        if name == "Network":
            item = sample.network.primary if sample.network else None
            if not item: return "Unavailable", sample.errors.get("network", "No usable non-loopback address") + stale
            address = (item.addresses_v4 + item.addresses_v6)[0]
            return address, f"{item.name} • {item.state}" + stale + (" • STALE" if "network" in self.stale_categories else "")
        if name == "CPU":
            usage = "Collecting…" if sample.cpu_percent is None else f"{sample.cpu_percent:.1f}%"
            freq = f"{sample.frequency.mhz:.0f} MHz" if sample.frequency else "Clock unavailable"
            return usage, f"{sample.cpu_model[:28]} • {freq}" + stale
        if name == "Temperature":
            sensor = next((item for item in sample.sensors if item.selected), None)
            return (f"{sensor.celsius:.1f} °C", f"{sensor.label} • {sensor.kind}" + stale) if sensor else ("Unavailable", "No identified local sensor" + stale)
        memory = sample.memory
        return (f"{memory.used_kib / 1024:.0f} / {memory.total_kib / 1024:.0f} MiB", f"{memory.percent:.1f}% used" + (" • estimated" if memory.estimated else "") + stale + (" • STALE" if "memory" in self.stale_categories else "")) if memory else ("Unavailable", sample.errors.get("memory", "Memory data unavailable") + stale)

    def _history(self, name: str) -> tuple[float, ...]:
        return {"CPU": self.cpu_history.items(), "Temperature": self.temp_history.items(), "Memory": self.memory_history.items()}.get(name, ())

    def _sparkline(self, x1, y1, x2, y2, values, color) -> None:
        if len(values) < 2: return
        low, high = min(values), max(values)
        span = max(1.0, high-low)
        points = []
        for index, value in enumerate(values):
            points.extend((x1+(x2-x1)*index/(len(values)-1), y2-(y2-y1)*(value-low)/span))
        self.canvas.create_line(*points, tags="dashboard", fill=color, width=2, smooth=True)

    def _details(self) -> None:
        name = PANELS[self.model.expanded or 0]
        self.canvas.create_text(102, 24, tags="dashboard", anchor="w", text=f"{name} details", fill=TEXT, font=("TkDefaultFont", 17, "bold"))
        self._button((10, 8, 90, 42), "Back", True)
        lines = self._detail_lines(name)
        y = 58 - self.model.scroll
        width = max(100, self.canvas.winfo_width()-28)
        for heading, content in lines:
            if y > 40 and y < self.canvas.winfo_height()-52:
                self.canvas.create_text(14, y, tags="dashboard", anchor="nw", text=heading, fill=ACCENT, font=("TkDefaultFont", 11, "bold"))
                self.canvas.create_text(14, y+17, tags="dashboard", anchor="nw", width=width, text=content, fill=TEXT, font=("TkDefaultFont", 11), justify="left")
            y += 44 + min(56, 12 * (len(content) // max(16, int(width/7))))
        if self.model.scroll: self.canvas.create_text(self.canvas.winfo_width()-12, 48, tags="dashboard", anchor="ne", text="↑/↓ scroll", fill=MUTED, font=("TkDefaultFont", 9))

    def _detail_lines(self, name: str) -> list[tuple[str, str]]:
        sample = self.snapshot
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
        if name == "CPU":
            lines = [("Model", sample.cpu_model), ("Architecture / logical CPUs", f"{sample.architecture or 'unavailable'} • {sample.cpu_count} logical CPUs"),
                     ("Utilization", "Collecting initial delta" if sample.cpu_percent is None else f"{sample.cpu_percent:.1f}%"),
                     ("Live frequency", "Unavailable" if not sample.frequency else f"{sample.frequency.mhz:.1f} MHz ({sample.frequency.source}, {sample.frequency.path})"),
                     ("Per-core utilization", ", ".join(f"{key}: {'—' if value is None else f'{value:.1f}%'}" for key, value in sample.per_core.items()) or "Unavailable"),
                     ("Governor", ", ".join(sample.governors) or "Unavailable"),
                     ("Load / uptime", (f"load {sample.load_averages[0]:.2f}, {sample.load_averages[1]:.2f}, {sample.load_averages[2]:.2f}" if sample.load_averages else "load unavailable") + (f" • uptime {sample.uptime_seconds/3600:.1f} h" if sample.uptime_seconds is not None else ""))]
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
        self._clear_pulse()
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        cx, cy = width / 2, height / 2
        for _ in range(3): self.pulse_items.append(self.canvas.create_oval(cx, cy, cx, cy, outline=ACCENT, width=2))
        for _ in range(10): self.pulse_items.append(self.canvas.create_oval(cx, cy, cx+3, cy+3, fill=ACCENT, outline=""))
        self._pulse_frame()

    def _pulse_frame(self) -> None:
        if self.closed or not self.model.pulse.active: return
        if self.model.pulse.progress(self.clock()) >= 1.0:
            self.model.pulse.cancel(); self._clear_pulse(); self._render(); return
        self._update_pulse(); self._schedule(42, self._pulse_frame)

    def _update_pulse(self) -> None:
        if not self.pulse_items: return
        progress = self.model.pulse.progress(self.clock()); width, height = self.canvas.winfo_width(), self.canvas.winfo_height(); cx, cy = width/2, height/2
        max_radius = max(width, height) * .55
        for index, item in enumerate(self.pulse_items[:3]):
            radius = max_radius * max(0.0, progress - index*.14)
            self.canvas.coords(item, cx-radius, cy-radius, cx+radius, cy+radius)
            self.canvas.itemconfigure(item, outline=ACCENT if progress < .72 else "#3c756f")
        for index, item in enumerate(self.pulse_items[3:]):
            angle = index * math.tau / 10 + progress * 4
            radius = 24 + progress * max_radius * (0.35 + (index % 3) * .1)
            x, y = cx + math.cos(angle)*radius, cy + math.sin(angle)*radius
            self.canvas.coords(item, x-2, y-2, x+2, y+2)

    def _clear_pulse(self) -> None:
        for item in self.pulse_items: self.canvas.delete(item)
        self.pulse_items.clear()

    def close(self) -> None:
        if self.closed: return
        self.closed, self.accept_results = True, False
        self.model.pulse.cancel(); self._clear_pulse()
        for ident in tuple(self.after_ids):
            try: self.root.after_cancel(ident)
            except Exception: pass
        self.after_ids.clear()
        self.root.destroy()
