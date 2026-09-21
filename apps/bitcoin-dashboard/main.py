#!/usr/bin/env python3
"""Pocket Bitcoin: CoinGecko CAD quote and 24-hour chart, sized for PocketCHIP."""
import json
import math
import os
import stat
import ssl
import sys
from decimal import Decimal
from http.client import HTTPException
from pathlib import Path
import queue
import tempfile
import threading
import time
try:
    import tkinter as tk
except ImportError:
    tk = None
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

# Display and HTTP user-agent version; publication metadata comes from app.toml.
VERSION = '1.2.5'
BLOCK_HIGHLIGHT_SECONDS = 10
SATOSHIS_PER_BTC = 100_000_000
MAX_SUPPLY = 21_000_000 * SATOSHIS_PER_BTC
HALVING_INTERVAL = 210_000
CARD_TITLES = ('Block height', 'Bitcoin in existence', 'Blockchain size')
# Expected failures at the untrusted JSON/HTTP boundary, including truncated HTTP.
DATA_ERRORS = (OSError, HTTPException, ValueError, KeyError, TypeError,
               OverflowError, RecursionError)
SETTINGS = Path.home() / '.config/pocket-bitcoin/settings.json'

BASE = 'https://api.coingecko.com/api/v3/'
# Session cache is in RAM, preserving the PocketCHIP's NAND flash.
RUNTIME = Path('/run/user') / str(os.getuid())
CACHE = RUNTIME / 'pocket-bitcoin.json'
CHAIN_BASE = 'https://api.blockchain.info/'
BG, PANEL, INK, MUTED = '#0c121b', '#172331', '#f1f5fa', '#a3b3c5'
ORANGE, GREEN, RED = '#f7931a', '#60d6ac', '#ff8686'


class ConfigurationError(ValueError):
    """An invalid optional environment setting, without including its contents."""


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        origin, target = urlsplit(req.full_url), urlsplit(newurl)
        if (target.scheme != 'https' or target.hostname != origin.hostname
                or (target.port or 443) != (origin.port or 443)
                or target.username is not None or target.password is not None):
            raise URLError('Unsafe API redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def number(value, positive=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError('Invalid number')
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or (positive and value <= 0):
        raise ValueError('Invalid number')
    return float(value)


def quote(data):
    row = data['bitcoin']
    if not isinstance(row, dict):
        raise ValueError('Invalid quote')
    stamp = number(row['last_updated_at'], True)
    if stamp > time.time() + 300:
        raise ValueError('Future timestamp')
    change = row.get('cad_24h_change')
    return {'price': number(row['cad'], True), 'updated': stamp,
            'change': None if change is None else number(change)}


def history(data):
    rows = data['prices']
    if not isinstance(rows, list) or not 2 <= len(rows) <= 5000:
        raise ValueError('Invalid chart')
    result = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError('Invalid chart point')
        stamp, value = number(row[0], True) / 1000, number(row[1], True)
        if stamp > time.time() + 300 or (result and stamp <= result[-1][0]):
            raise ValueError('Invalid chart time')
        result.append([stamp, value])
    return result


def timestamp(value):
    stamp = number(value, True)
    if stamp > time.time() + 300:
        raise ValueError('Future timestamp')
    return stamp


def chain_stats(data):
    count = integer(data['n_blocks_total'], 100_000_000)
    satoshis = integer(data['totalbc'], MAX_SUPPLY)
    # This endpoint counts genesis as block 1; the genesis height is 0.
    return {'height': count - 1, 'supply_sats': satoshis,
            'chain_updated': timestamp(number(data['timestamp'], True) / 1000)}


def integer(value, maximum):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not 0 < value <= maximum or int(value) != value):
        raise ValueError('Invalid integer')
    return int(value)


def format_supply(satoshis):
    return '{:,.3f}'.format(Decimal(satoshis) / SATOSHIS_PER_BTC)


def format_btc(satoshis):
    return '{:,.8f}'.format(Decimal(satoshis) / SATOSHIS_PER_BTC)


def subsidy_at_height(height):
    """Mainnet subsidy in satoshis, excluding transaction fees."""
    halvings = height // HALVING_INTERVAL
    return (50 * SATOSHIS_PER_BTC) >> halvings if halvings < 64 else 0


def compact_number(value, decimals=0, signed=False):
    """Bound dynamic labels without losing their units or drawing over neighbours."""
    if abs(value) >= 1e12 or (value != 0 and abs(value) < .01):
        return format(value, '+.2e' if signed else '.2e')
    return format(value, ('+' if signed else '') + ',.' + str(decimals) + 'f')


def chart_coordinates(points, left, right, top, bottom):
    low, high = min(p[1] for p in points), max(p[1] for p in points)
    # Normalize before subtracting or padding: finite extreme values must not
    # overflow (or underflow to a zero range) in Tk's coordinate calculation.
    floor = low / high
    pad = (1 - floor) * .12 if low != high else .01
    lo, span = floor - pad, 1 - floor + 2 * pad
    start, end = points[0][0], points[-1][0]
    buckets = {}
    for t, price in points:
        x = left + (t - start) / (end - start) * (right - left)
        bucket = int(x)
        lower, upper = buckets.get(bucket, ((t, price), (t, price)))
        buckets[bucket] = (min(lower, (t, price), key=lambda p: p[1]),
                           max(upper, (t, price), key=lambda p: p[1]))
    # Keep extrema in each pixel column plus both endpoints, preserving spikes.
    samples = {t: price for pair in buckets.values() for t, price in pair}
    samples[start], samples[end] = points[0][1], points[-1][1]
    coords = []
    for t, price in sorted(samples.items()):
        coords.extend((left + (t-start)/(end-start)*(right-left),
                       bottom - (price/high-lo)/span*(bottom-top)))
    return coords


def read_json(path, limit):
    # Nonblocking open and fstat prevent a replaced cache/settings FIFO from
    # freezing startup; never follow a final symlink or read an unbounded file.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError('Invalid data file')
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError('Data file too large')
    return json.loads(content)


def blockchain_size(data):
    if data['status'] != 'ok' or data['unit'] != 'MB':
        raise ValueError('Invalid blockchain size units')
    rows = data['values']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5000:
        raise ValueError('Invalid blockchain size history')
    values = [(timestamp(row['x']), number(row['y'], True)) for row in rows]
    stamp, mb = max(values)
    if mb > 1e12:
        raise ValueError('Invalid blockchain size')
    return {'chain_gb': mb / 1000, 'size_updated': stamp}


def fetch(endpoint, base=BASE):
    headers = {'User-Agent': 'PocketBitcoin/' + VERSION, 'Accept': 'application/json'}
    request = Request(base + endpoint, headers=headers)
    key = os.environ.get('COINGECKO_DEMO_API_KEY')
    if key and base == BASE:
        if len(key) > 512 or any(ord(char) < 33 or ord(char) > 126 for char in key):
            raise ConfigurationError('Invalid API key configuration')
        request.add_unredirected_header('x-cg-demo-api-key', key)
    deadline = time.monotonic() + 30
    with build_opener(SafeRedirectHandler()).open(request, timeout=18) as response:
        data = bytearray()
        while len(data) <= 1_000_000:
            if time.monotonic() >= deadline:
                raise TimeoutError('Slow API response')
            chunk = response.read1(min(65536, 1_000_001 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
    if len(data) > 1_000_000:
        raise ValueError('Response too large')
    return json.loads(data)


def error_label(error, source="CoinGecko"):
    if isinstance(error, ConfigurationError):
        return 'Check COINGECKO_DEMO_API_KEY'
    if isinstance(error, URLError) and isinstance(error.reason, ssl.SSLCertVerificationError):
        return 'TLS error: check clock / certificates'
    if isinstance(error, HTTPError):
        return 'Rate limited' if error.code == 429 else '%s HTTP %s' % (source, error.code)
    if isinstance(error, (URLError, OSError, HTTPException)):
        return 'Offline / connection error'
    return 'Invalid %s data' % source


def retry_delay(failures):
    return min(120 * 2 ** failures, 1800)


class App:
    def __init__(self, root):
        self.root = root
        self.data = {}
        self.busy = False
        self.events = queue.Queue()
        self.failures = 0
        self.next_fetch = 0
        self.last_start = 0
        self.message = ''
        self.chart_error = False
        self.chart_message = ''
        self.chart_failures = 0
        self.next_chart = 0
        self.chain_busy = False
        self.chain_failures = 0
        self.chain_error = False
        self.size_error = False
        self.chain_message = ''
        self.size_message = ''
        self.size_failures = 0
        self.next_size = 0
        self.next_chain = 0
        self.last_chain_start = -20
        self.last_render = None
        self.highlight_until = 0
        self.highlight_id = None
        self.highlight_enabled = self.load_settings()
        self.settings_panel = None
        self.selected_card = 0
        self.pressed_card = None
        self.detail_card = None
        self.closed = False
        self.poll_id = None
        root.title('Bitcoin CAD v' + VERSION)
        if root.tk.call('tk', 'windowingsystem') == 'x11':
            # Tk publishes _NET_WM_PID when the client hostname is set.
            root.wm_client(root.tk.call('info', 'hostname'))
        root.geometry('480x272')
        root.minsize(480, 272)
        root.configure(bg=BG)
        self.canvas = tk.Canvas(root, bg=BG, highlightthickness=0, takefocus=True)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda event: self.draw(force=True))
        self.canvas.bind('<FocusIn>', lambda event: self.draw())
        self.canvas.bind('<FocusOut>', lambda event: self.draw())
        self.canvas.bind('<Button-1>', self.press_card)
        self.canvas.bind('<ButtonRelease-1>', self.release_card)
        for key in ('<Return>', '<KP_Enter>', '<space>'):
            self.canvas.bind(key, self.activate_card)
        for key in ('<Left>', '<Right>', '<Up>', '<Down>'):
            root.bind(key, self.move_card)
        root.bind('<Escape>', self.escape)
        root.bind('<r>', lambda event: self.refresh_all(True))
        root.bind('<R>', lambda event: self.refresh_all(True))
        root.bind('<s>', lambda event: self.toggle_settings())
        root.bind('<S>', lambda event: self.toggle_settings())
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh_button = self.button(root, 'Refresh', lambda: self.refresh_all(True))
        self.refresh_button.place(relx=1, x=-234, y=6, width=80, height=36)
        self.settings_button = self.button(root, 'Settings', self.toggle_settings)
        self.settings_button.place(relx=1, x=-148, y=6, width=76, height=36)
        self.home_button = self.button(root, 'Home', self.back)
        self.home_button.place(relx=1, x=-66, y=6, width=58, height=36)
        icon = Path(__file__).resolve().with_name('icon.png')
        try:
            if icon.is_file() and icon.stat().st_size <= 1_000_000:
                self.icon = tk.PhotoImage(file=str(icon))
                root.iconphoto(True, self.icon)
        except (OSError, tk.TclError):
            pass  # Optional artwork must not prevent the dashboard from starting.
        self.load_cache()
        self.draw()
        self.refresh_all()
        self.settings_button.focus_set()
        self.poll_id = root.after(200, self.poll)

    def button(self, parent, label, command):
        button = tk.Button(parent, text=label, command=command,
            bg=PANEL, fg=INK, activebackground='#294050', activeforeground=INK,
            disabledforeground=MUTED, relief='flat', bd=0,
            highlightthickness=1, highlightbackground='#354254', highlightcolor=ORANGE,
            font=('DejaVu Sans', -12), takefocus=True)
        for key in ('<Return>', '<KP_Enter>'):
            button.bind(key, self.activate_control)
        return button

    @staticmethod
    def activate_control(event):
        event.widget.invoke()
        return 'break'

    def load_settings(self):
        self.settings_notice = 'Changes are saved automatically.'
        self.settings_warning = False
        try:
            raw = read_json(SETTINGS, 4096)
            if isinstance(raw, dict) and type(raw.get('highlight_new_blocks')) is bool:
                return raw['highlight_new_blocks']
        except FileNotFoundError:
            return True
        except (OSError, ValueError, RecursionError):
            pass
        self.settings_warning = True
        self.settings_notice = 'Settings unreadable; defaults used. Toggle to save.'
        return True

    def save_settings(self):
        name = None
        try:
            SETTINGS.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = SETTINGS.parent.lstat()
            if (not SETTINGS.parent.is_dir() or SETTINGS.parent.is_symlink()
                    or info.st_uid != os.getuid() or info.st_mode & 0o077):
                raise OSError('Unsafe settings directory')
            fd, name = tempfile.mkstemp(prefix='.settings-', dir=SETTINGS.parent)
            with os.fdopen(fd, 'w') as stream:
                json.dump({'highlight_new_blocks': self.highlight_enabled}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, SETTINGS)
            return True
        except OSError:
            return False
        finally:
            if name:
                try:
                    os.unlink(name)
                except OSError:
                    pass

    def escape(self, event=None):
        if self.settings_panel is not None:
            self.toggle_settings()
        else:
            self.back()

    def back(self):
        if self.detail_card is None:
            self.close()
            return
        if self.settings_panel is not None:
            self.toggle_settings()
        self.detail_card = None
        self.home_button.configure(text='Home')
        self.canvas.configure(takefocus=True)
        self.canvas.focus_set()
        self.draw()

    def card_bounds(self):
        width = max(self.canvas.winfo_width(), 480)
        return ((8, 142, 128, 231), (136, 142, 308, 231), (316, 142, width-8, 231))

    def card_at(self, x, y):
        if self.detail_card is not None or self.settings_panel is not None:
            return None
        for index, (x1, y1, x2, y2) in enumerate(self.card_bounds()):
            if x1 <= x <= x2 and y1 <= y <= y2:
                return index
        return None

    def press_card(self, event):
        self.pressed_card = self.card_at(event.x, event.y)
        if self.pressed_card is not None:
            self.selected_card = self.pressed_card
            self.canvas.focus_set()
            self.draw()

    def release_card(self, event):
        pressed, self.pressed_card = self.pressed_card, None
        if pressed is not None and pressed == self.card_at(event.x, event.y):
            self.open_card(pressed)

    def move_card(self, event):
        if self.settings_panel is not None or self.detail_card is not None:
            return None
        forward = event.keysym in ('Right', 'Down')
        if self.root.focus_get() == self.canvas:
            self.selected_card = (self.selected_card + (1 if forward else -1)) % len(CARD_TITLES)
        else:
            self.selected_card = 0 if forward else len(CARD_TITLES)-1
        self.canvas.focus_set()
        self.draw()
        return 'break'

    def activate_card(self, event=None):
        if self.settings_panel is None and self.detail_card is None:
            self.open_card(self.selected_card)
        return 'break'

    def open_card(self, index):
        if self.closed or self.settings_panel is not None or self.detail_card is not None:
            return
        if index not in range(len(CARD_TITLES)):
            return
        self.selected_card = self.detail_card = index
        self.pressed_card = None
        self.home_button.configure(text='Back')
        self.canvas.configure(takefocus=False)
        # Keyboard users can return immediately with Enter, or use Escape.
        self.home_button.focus_set()
        self.draw()

    def schedule_highlight_expiry(self):
        if self.highlight_id is not None:
            self.root.after_cancel(self.highlight_id)
            self.highlight_id = None
        if self.highlight_until > time.monotonic():
            delay = max(1, math.ceil((self.highlight_until - time.monotonic()) * 1000))
            self.highlight_id = self.root.after(delay, self.expire_highlight)

    def expire_highlight(self):
        self.highlight_id = None
        self.highlight_until = 0
        if not self.closed:
            self.draw()

    def detail_rows(self):
        if self.detail_card == 0:
            height = self.data.get('height')
            subsidy = subsidy_at_height(height) if height is not None else None
            next_halving = ((height // HALVING_INTERVAL + 1) * HALVING_INTERVAL
                            if subsidy else None)
            rows = [('Reported height', '{:,}'.format(height) if height is not None else '—'),
                    ('Block subsidy (BTC)', format_btc(subsidy) if subsidy is not None else '—'),
                    ('Next halving at', '{:,}'.format(next_halving) if next_halving else
                     'None' if subsidy == 0 else '—'),
                    ('Blocks until halving', '{:,}'.format(next_halving-height) if next_halving else
                     'None' if subsidy == 0 else '—')]
            return rows, 'Subsidy excludes fees. Based on the reported height.'
        if self.detail_card == 1:
            sats = self.data.get('supply_sats')
            rows = [('Issued BTC', format_btc(sats) if sats is not None else '—'),
                    ('Issued satoshis', '{:,}'.format(sats) if sats is not None else '—'),
                    ('Share of 21M cap', '{:.4f}%'.format(Decimal(sats)*100/MAX_SUPPLY)
                     if sats is not None else '—'),
                    ('Below 21M cap (BTC)', format_btc(MAX_SUPPLY-sats) if sats is not None else '—')]
            return rows, 'Reported issuance includes coins that may be lost.'
        size = self.data.get('chain_gb')
        rows = [('Block data (GB)', compact_number(size, 3) if size is not None else '—'),
                ('Block data (MB)', compact_number(size*1000, 3) if size is not None else '—'),
                ('Includes', 'Headers + transactions'),
                ('Extra disk space', 'Chainstate + indexes')]
        return rows, 'Full nodes also need undo data and room to grow.'

    def draw_details(self, text, panel, stamp, width, stale_chain, stale_size):
        size_card = self.detail_card == 2
        key = ('height', 'supply_sats', 'chain_gb')[self.detail_card]
        timestamp_key = 'size_updated' if size_card else 'chain_updated'
        stale = stale_size if size_card else stale_chain
        if self.data.get(key) is not None:
            prefix = 'Daily sample' if size_card else 'Network sample'
            status = ('Saved ' if stale else '') + prefix + ' · ' + stamp(timestamp_key, '%d %b %Y %H:%M')
        else:
            status = 'Loading network data…' if self.chain_busy else 'Unavailable · retrying automatically'
        text(12, 55, CARD_TITLES[self.detail_card], 18, weight='bold')
        text(12, 82, status, 11, ORANGE if stale else MUTED, max_width=width-24)
        panel(8, 100, width-8, 235)
        rows, note = self.detail_rows()
        for index, (label, value) in enumerate(rows):
            y = 105 + index*27
            text(18, y+3, label, 11, MUTED, max_width=160)
            text(width-18, y, value, 16, anchor='ne', weight='bold', max_width=width-212)
        text(18, 217, note, 10, MUTED, max_width=width-36)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
            self.poll_id = None
        if self.highlight_id is not None:
            self.root.after_cancel(self.highlight_id)
            self.highlight_id = None
        self.root.destroy()

    def toggle_settings(self):
        if self.settings_panel is not None:
            self.settings_panel.destroy()
            self.settings_panel = None
            self.settings_button.focus_set()
            self.draw()
            return
        self.settings_panel = tk.Frame(self.root, bg=PANEL)
        self.settings_panel.place(x=8, y=49, relwidth=1, width=-16, relheight=1, height=-83)
        tk.Label(self.settings_panel, text='Settings', bg=PANEL, fg=INK,
                 font=('DejaVu Sans', -18, 'bold')).pack(anchor='w', padx=12, pady=(8, 4))
        self.highlight_option = tk.BooleanVar(self.root, value=self.highlight_enabled)
        self.highlight_checkbox = tk.Checkbutton(self.settings_panel,
            text='Highlight new blocks', variable=self.highlight_option,
            command=self.change_highlight, bg=PANEL, fg=INK, selectcolor=BG,
            activebackground=PANEL, activeforeground=INK,
            font=('DejaVu Sans', -14), anchor='w', height=2, takefocus=True,
            highlightthickness=1, highlightbackground=PANEL, highlightcolor=ORANGE)
        self.highlight_checkbox.pack(fill='x', padx=12)
        tk.Label(self.settings_panel,
                 text='Highlight the block-height card for %s seconds.' % BLOCK_HIGHLIGHT_SECONDS,
                 bg=PANEL, fg=MUTED, font=('DejaVu Sans', -12)).pack(anchor='w', padx=12)
        self.settings_status = tk.Label(self.settings_panel, text=self.settings_notice,
            bg=PANEL, fg=ORANGE if self.settings_warning else MUTED,
            font=('DejaVu Sans', -11), anchor='w')
        self.settings_status.pack(anchor='w', padx=12, pady=4)
        self.done_button = self.button(self.settings_panel, 'Done', self.toggle_settings)
        self.done_button.pack(anchor='e', padx=12, ipadx=12, ipady=4)
        def cycle_focus(event):
            target = self.done_button if event.widget == self.highlight_checkbox else self.highlight_checkbox
            target.focus_set()
            return 'break'
        for widget in (self.highlight_checkbox, self.done_button):
            for key in ('<Tab>', '<Shift-Tab>', '<ISO_Left_Tab>'):
                widget.bind(key, cycle_focus)
        for key in ('<Return>', '<KP_Enter>'):
            self.highlight_checkbox.bind(key, self.activate_control)
        self.highlight_checkbox.focus_set()
        self.draw()

    def change_highlight(self):
        self.highlight_enabled = self.highlight_option.get()
        if not self.highlight_enabled:
            self.highlight_until = 0
            self.schedule_highlight_expiry()
        saved = self.save_settings()
        self.settings_warning = not saved
        self.settings_notice = ('Settings saved.' if saved else
            'Applied for this session; could not save settings.')
        self.settings_status.configure(text=self.settings_notice, fg=MUTED if saved else ORANGE)
        self.draw()

    def update_chain(self, value):
        if value['chain_updated'] < self.data.get('chain_updated', 0):
            return False
        previous = self.data.get('height')
        # Initial data and delayed/out-of-order samples are not new-block events.
        if (self.highlight_enabled and previous is not None and value['height'] > previous
                and value['chain_updated'] >= self.data.get('chain_updated', 0)
                and time.time() - value['chain_updated'] <= 900):
            self.highlight_until = time.monotonic() + BLOCK_HIGHLIGHT_SECONDS
        self.data.update(value)
        self.chain_error = False
        self.chain_message = ''
        return True

    def load_cache(self):
        try:
            raw = read_json(CACHE, 1_000_000)
            if not isinstance(raw, dict):
                return
        except (OSError, ValueError, RecursionError):
            return
        # Validate sections independently: a bad chart must not hide good stats.
        sections = [
            lambda: quote({'bitcoin': {'cad': raw['price'],
                'last_updated_at': raw['updated'], 'cad_24h_change': raw.get('change')}}),
            lambda: {'points': history({'prices': [[t * 1000, p] for t, p in raw['points']]}),
                     'chart_fetched': timestamp(raw['chart_fetched'])},
            lambda: chain_stats({'n_blocks_total': number(raw['height']) + 1,
                'totalbc': raw['supply_sats'],
                'timestamp': number(raw['chain_updated']) * 1000}),
            lambda: dict(blockchain_size({'status': 'ok', 'unit': 'MB',
                'values': [{'x': raw['size_updated'], 'y': number(raw['chain_gb']) * 1000}]}),
                size_fetched=timestamp(raw['size_fetched']))]
        for section in sections:
            try:
                self.data.update(section())
            except (ValueError, KeyError, TypeError, OverflowError):
                pass

    def save_cache(self):
        name = None
        try:
            # Do not fall back to periodic writes to flash if the RAM directory is absent.
            info = CACHE.parent.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077):
                return
            fd, name = tempfile.mkstemp(prefix='.pocket-bitcoin-', dir=CACHE.parent)
            with os.fdopen(fd, 'w') as stream:
                json.dump(self.data, stream, allow_nan=False)
            os.replace(name, CACHE)
        except (OSError, ValueError, TypeError, RecursionError):
            pass
        finally:
            if name:
                try:
                    os.unlink(name)
                except OSError:
                    pass

    def refresh_all(self, manual=False):
        if self.closed:
            return
        self.refresh(manual)
        self.refresh_chain(manual)
        self.draw()

    def refresh_chain(self, manual=False):
        now = time.monotonic()
        allowed = manual and not self.chain_failures and now - self.last_chain_start >= 20
        if self.closed or self.chain_busy or (now < self.next_chain and not allowed):
            return
        self.chain_busy = True
        self.last_chain_start = now
        need_size = (now >= self.next_size and (self.size_error
            or time.time() - self.data.get('size_fetched', 0) >= 21600))
        try:
            threading.Thread(target=self.chain_worker, args=(need_size,), daemon=True).start()
        except RuntimeError:
            self.events.put(('chain_error', 'Cannot start network refresh'))
            self.events.put(('chain_done', True))

    def chain_worker(self, need_size):
        failed = False
        try:
            self.events.put(('chain', chain_stats(fetch('stats', CHAIN_BASE))))
        except DATA_ERRORS as error:
            self.events.put(('chain_error', error_label(error, 'Blockchain.com')))
            failed = True
        if need_size:
            try:
                data = blockchain_size(fetch('charts/blocks-size?timespan=3days&format=json', CHAIN_BASE))
                data['size_fetched'] = time.time()
                self.events.put(('size', data))
            except DATA_ERRORS as error:
                self.events.put(('size_error', error_label(error, 'Blockchain.com')))
        self.events.put(('chain_done', failed))

    def refresh(self, manual=False):
        now = time.monotonic()
        allowed_manual = manual and not self.failures and now - self.last_start >= 20
        if self.closed or self.busy or (now < self.next_fetch and not allowed_manual):
            return
        self.busy = True
        self.last_start = now
        self.refresh_button.configure(state='disabled')
        self.draw()
        need_chart = (now >= self.next_chart and (self.chart_error
            or time.time() - self.data.get('chart_fetched', 0) >= 600))
        try:
            threading.Thread(target=self.worker, args=(need_chart,), daemon=True).start()
        except RuntimeError:
            self.events.put(('done', 'Cannot start price refresh'))

    def worker(self, need_chart):
        try:
            q = quote(fetch('simple/price?ids=bitcoin&vs_currencies=cad&include_24hr_change=true&include_last_updated_at=true'))
            self.events.put(('quote', q))
        except DATA_ERRORS as error:
            self.events.put(('done', error_label(error)))
            return
        if need_chart:
            try:
                points = history(fetch('coins/bitcoin/market_chart?vs_currency=cad&days=1'))
                self.events.put(('chart', points))
            except DATA_ERRORS as error:
                self.events.put(('chart_error', error_label(error)))
        self.events.put(('done', None))

    def poll(self):
        if self.closed:
            return
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
            self.poll_id = None
        changed = False
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'quote':
                    if value['updated'] >= self.data.get('updated', 0):
                        self.data.update(value)
                        changed = True
                elif kind == 'chart':
                    if not self.data.get('points') or value[-1][0] >= self.data['points'][-1][0]:
                        self.data.update(points=value, chart_fetched=time.time())
                        changed = True
                    self.chart_error = False
                    self.chart_message = ''
                    self.chart_failures = 0
                    self.next_chart = 0
                elif kind == 'chart_error':
                    self.chart_error = True
                    self.chart_message = value
                    self.chart_failures = min(self.chart_failures + 1, 5)
                    self.next_chart = time.monotonic() + retry_delay(self.chart_failures)
                elif kind in ('chain', 'size'):
                    if kind == 'chain':
                        previous_highlight = self.highlight_until
                        changed = self.update_chain(value) or changed
                        if self.highlight_until != previous_highlight:
                            self.schedule_highlight_expiry()
                    else:
                        if value['size_updated'] >= self.data.get('size_updated', 0):
                            self.data.update(value)
                            changed = True
                        self.size_error = False
                        self.size_message = ''
                        self.size_failures = 0
                        self.next_size = 0
                elif kind == 'chain_error':
                    self.chain_error = True
                    self.chain_message = value
                elif kind == 'size_error':
                    self.size_error = True
                    self.size_message = value
                    self.size_failures = min(self.size_failures + 1, 5)
                    self.next_size = time.monotonic() + retry_delay(self.size_failures)
                elif kind == 'chain_done':
                    self.chain_busy = False
                    self.chain_failures = min(self.chain_failures + 1, 5) if value else 0
                    self.next_chain = time.monotonic() + retry_delay(self.chain_failures)
                elif kind == 'done':
                    self.busy = False
                    self.failures = min(self.failures + 1, 5) if value else 0
                    delay = retry_delay(self.failures)
                    self.next_fetch = time.monotonic() + delay
                    self.message = value or ''
        except queue.Empty:
            pass
        if changed:
            self.save_cache()
        if not self.busy:
            if time.monotonic() >= self.next_fetch:
                self.refresh()
        self.refresh_chain()
        now = time.monotonic()
        price_ready = not self.busy and not self.failures and now - self.last_start >= 20
        chain_ready = not self.chain_busy and not self.chain_failures and now - self.last_chain_start >= 20
        state = 'normal' if price_ready or chain_ready else 'disabled'
        if self.refresh_button.cget('state') != state:
            self.refresh_button.configure(state=state)
        self.draw()
        self.poll_id = self.root.after(1000, self.poll)

    def draw(self, force=False):
        if self.closed:
            return
        c = self.canvas
        w, h = max(c.winfo_width(), 480), max(c.winfo_height(), 272)
        now = time.time()
        stale_price = now - self.data.get('updated', 0) > 300 or bool(self.failures)
        stale_chain = now - self.data.get('chain_updated', 0) > 900 or self.chain_error
        stale_size = now - self.data.get('size_updated', 0) > 4 * 86400 or self.size_error
        points = self.data.get('points', ())
        stale_chart = self.chart_error or (points and now - points[-1][0] > 1800)
        highlighted = self.highlight_enabled and time.monotonic() < self.highlight_until
        # No full-canvas redraw every second when the values and status are unchanged.
        signature = (w, h, self.data.get('updated'), self.data.get('chart_fetched'),
                     self.data.get('chain_updated'), self.data.get('size_fetched'),
                     self.busy, self.chain_busy, stale_price, stale_chain, stale_size,
                     bool(stale_chart), self.message, self.chart_error, highlighted, self.data.get('height'))
        signature += (self.data.get('price'), self.data.get('change'),
                      self.data.get('supply_sats'), self.data.get('chain_gb'), id(points),
                      self.chain_message, self.size_message, self.chart_message,
                      self.settings_panel is not None, self.detail_card,
                      self.selected_card, self.root.focus_get() == self.canvas)
        if not force and signature == self.last_render:
            return
        self.last_render = signature
        c.delete('all')
        def text(x, y, value, size=12, color=INK, anchor='nw', weight='normal', max_width=None):
            item = c.create_text(x, y, text=value, fill=color, anchor=anchor,
                                 font=('DejaVu Sans', -size, weight))
            if max_width:
                while size > 10 and c.bbox(item)[2] - c.bbox(item)[0] > max_width:
                    size -= 1
                    c.itemconfigure(item, font=('DejaVu Sans', -size, weight))
            return item
        def panel(x1, y1, x2, y2):
            c.create_rectangle(x1, y1, x2, y2, fill=PANEL, outline='')
        def stamp(key, pattern='%H:%M'):
            value = self.data.get(key)
            return time.strftime(pattern, time.localtime(value)) if value else '--'
        c.create_oval(10, 9, 38, 37, fill=ORANGE, outline='')
        text(24, 23, '₿', 24, anchor='center', weight='bold')
        text(47, 7, 'BITCOIN', 16, weight='bold')
        text(48, 29, 'CANADIAN DOLLAR', 10, MUTED)
        c.create_line(10, 47, w-10, 47, fill='#293545')

        if self.detail_card is not None:
            self.draw_details(text, panel, stamp, w, stale_chain, stale_size)
        else:
            # Price and chart share the hero row, leaving readable space for the network.
            value = self.data.get('price')
            text(12, 54, '1 BTC / CAD', 10, MUTED)
            text(10, 69, 'C$' + compact_number(value, 2) if value else 'C$ —',
                 31, weight='bold', max_width=224)
            change = self.data.get('change')
            color = GREEN if change is not None and change >= 0 else RED
            change_text = (('{:+.2e}'.format(change) if abs(change) >= 1000 else
                            compact_number(change, 2, signed=True)) + '%'
                           if change is not None else '—')
            text(12, 110, change_text, 13,
                 color if change is not None else MUTED, weight='bold', max_width=94)
            text(111, 112, '24h', 10, MUTED)
            price_stamp = (('SAVED ' if stale_price else '') + stamp('updated') if value
                           else 'Loading…' if self.busy else 'Unavailable')
            text(228, 112, price_stamp, 10,
                 ORANGE if stale_price else MUTED, anchor='ne')
            left, right, top, bottom = 249, w-13, 75, 115
            text(left, 55, '24H PRICE', 10, MUTED)
            text(right, 55, 'SAVED' if points and stale_chart else 'CAD', 10,
                 ORANGE if points and stale_chart else MUTED, anchor='ne')
            if points:
                low, high = min(p[1] for p in points), max(p[1] for p in points)
                for yy in (top, bottom):
                    c.create_line(left, yy, right, yy, fill='#263444')
                coords = chart_coordinates(points, left, right, top, bottom)
                c.create_polygon([left, bottom] + coords + [right, bottom], fill='#23302f', outline='')
                c.create_line(*coords, fill=ORANGE, width=2)
                x, y = coords[-2:]
                c.create_oval(x-2, y-2, x+2, y+2, fill=ORANGE, outline='')
                text(left, 119, 'L ' + compact_number(low), 10, MUTED, max_width=(right-left)/2-4)
                text(right, 119, 'H ' + compact_number(high), 10, MUTED,
                     anchor='ne', max_width=(right-left)/2-4)
            else:
                text((left+right)/2, 96, 'Loading chart…' if self.busy else 'Chart unavailable',
                     12, MUTED, anchor='center')

            a, b = 132, 312
            panel(8, 142, a-4, 231)
            panel(a+4, 142, b-4, 231)
            panel(b+4, 142, w-8, 231)
            for x1, x2 in ((8, a-4), (a+4, b-4), (b+4, w-8)):
                c.create_line(x1, 142, x2, 142, fill='#354254')
            if highlighted:
                c.create_rectangle(8, 142, a-4, 231, fill='#304236', outline=GREEN,
                                   width=2, tags='block-highlight')
            if self.root.focus_get() == self.canvas:
                x1, y1, x2, y2 = self.card_bounds()[self.selected_card]
                c.create_rectangle(x1+1, y1+1, x2-1, y2-1, outline=ORANGE, width=2,
                                   tags='card-selection')
            text(18, 151, 'NEW BLOCK' if highlighted else 'BLOCK HEIGHT', 10,
                 GREEN if highlighted else MUTED, weight='bold')
            height = self.data.get('height')
            text(18, 170, '{:,}'.format(height) if height is not None else '—', 24, weight='bold', max_width=104)
            chain_stamp = (('Saved · ' if stale_chain else 'As of ') + stamp('chain_updated')
                           if height is not None else 'Loading…' if self.chain_busy else 'Unavailable')
            text(18, 203, chain_stamp,
                 11, ORANGE if stale_chain else MUTED)
            text(146, 151, 'BITCOIN IN EXISTENCE', 10, MUTED, weight='bold')
            supply = self.data.get('supply_sats')
            text(146, 173, format_supply(supply) if supply else '—', 18, weight='bold', max_width=152)
            text(146, 200, 'Saved BTC / 21M cap' if supply and stale_chain else 'BTC  /  21 million cap',
                 10, ORANGE if supply and stale_chain else MUTED)
            c.create_rectangle(146, 219, 298, 222, fill='#344152', outline='')
            if supply:
                c.create_rectangle(146, 219, 146+152*min(supply/MAX_SUPPLY, 1), 222, fill=ORANGE, outline='')
            size = self.data.get('chain_gb')
            text(326, 151, 'BLOCKCHAIN SIZE', 10, MUTED, weight='bold')
            text(326, 170, compact_number(size, 1) + ' GB' if size else '—',
                 23, weight='bold', max_width=w-338)
            size_stamp = (('Saved · ' if stale_size else 'Blocks · ') + stamp('size_updated', '%d %b')
                          if size else 'Loading…' if self.chain_busy else 'Unavailable')
            text(326, 200, size_stamp, 10,
                 ORANGE if stale_size else MUTED)
            text(326, 214, '+ node overhead', 10, MUTED)

        error = self.message or self.chain_message or self.chart_message or self.size_message
        if self.busy or self.chain_busy:
            status, dot = 'Updating…', ORANGE
        elif error:
            status, dot = error + ' · auto retry', ORANGE
        elif stale_price or stale_chain or stale_size or stale_chart:
            status, dot = 'Some data saved / delayed', ORANGE
        else:
            status, dot = 'Auto refresh · 2 min', GREEN
        c.create_oval(12, h-28, 18, h-22, fill=dot, outline='')
        text(24, h-31, status, 10, MUTED, max_width=w-38)
        if not error:
            text(w-12, h-31, 'CoinGecko + Blockchain.com', 10, MUTED, anchor='ne')
        text(12, h-16, 'Back to overview' if self.detail_card is not None else
             '←/→ Cards · Enter Open', 10, MUTED)
        text(w/2, h-16, 'app version ' + VERSION, 10, MUTED, anchor='n')
        text(w-12, h-16, 'Esc  Back' if self.settings_panel is not None or self.detail_card is not None else 'Esc  Home',
             10, MUTED, anchor='ne')


def main():
    if tk is None:
        print('Bitcoin CAD needs Tkinter. On Debian, install python3-tk and try again.',
              file=sys.stderr)
        return 1
    try:
        root = tk.Tk()
    except tk.TclError:
        print('Bitcoin CAD needs a graphical desktop. Run it from the PocketCHIP desktop.',
              file=sys.stderr)
        return 1
    App(root)
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
