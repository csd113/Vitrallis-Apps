"""Small event-driven network/watch pages; one bounded background refresh."""
from decimal import Decimal
import queue
import os
import ssl
from http.client import HTTPException
import threading
import time
import tkinter as tk
from urllib.error import HTTPError, URLError
from monitor import API, balances, load_watch, network_snapshot, save_watch, transactions, validate_watch

BG, PANEL, INK, MUTED, ACCENT = '#0c121b', '#172331', '#f1f5fa', '#a3b3c5', '#60d6ac'


def btc(value):
    return format(Decimal(value) / 100_000_000, '.8f') + ' BTC'


def request_snapshot(fetch, watch, cancel):
    network = watched = None
    error = None
    deadline = time.monotonic() + 60
    def bounded_fetch(endpoint, base):
        if cancel.is_set() or time.monotonic() >= deadline:
            raise TimeoutError('Refresh budget expired')
        return fetch(endpoint, base)
    try:
        network = network_snapshot(bounded_fetch)
        if watch:
            addr = watch['address']
            balance = balances(bounded_fetch('address/'+addr, API))
            activity = transactions(bounded_fetch('address/'+addr+'/txs', API), addr)
            watched = dict(balance, transactions=activity, address=addr, updated=time.time())
    except (OSError, HTTPException, ValueError, KeyError, TypeError, OverflowError, RecursionError) as failure:
        if isinstance(failure, URLError) and isinstance(failure.reason, ssl.SSLCertVerificationError):
            error = 'TLS error · check clock / certificates'
        elif isinstance(failure, HTTPError) and failure.code == 429:
            error = 'Rate limited; retry later'
        else:
            error = 'Offline / invalid data · cached values retained'
    if error and 'VITRALLIS_TOR_API' in os.environ and not error.startswith(('Rate limited', 'TLS error')):
        error = 'Shell Tor / API error · cached values retained'
    return network, watched, error



def refresh_worker(fetch, watch, events, cancel):
    result = request_snapshot(fetch, watch, cancel)
    if not cancel.is_set():
        events.put_nowait(result)


class Monitor:
    def __init__(self, app, fetch):
        self.app, self.root, self.fetch = app, app.root, fetch
        self.visible = True
        self.page = 'network'
        self.selected = 0
        self.busy = False
        self.closed = False
        self.cancel = threading.Event()
        self.events = queue.Queue(maxsize=1)
        self.cache = {}
        self.network = None
        self.next_refresh = 0
        self.last_start = -20
        self.failures = 0
        self.notice = 'Loading mempool.space…'
        self.form = False
        self.delete_pending = False
        try:
            self.watches = load_watch()
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            self.watches = []
            self.notice = 'Watch list unreadable; original file preserved.'
            self.storage_error = True
        else:
            self.storage_error = False
        self.frame = tk.Frame(self.root, bg=BG)
        self.frame.place(x=0, y=0, relwidth=1, relheight=1)
        for index, (label, action) in enumerate((('Network', lambda: self.show('network')),
                ('Watch', lambda: self.show('watch')), ('CAD chart', self.hide),
                ('Refresh', lambda: self.refresh(True)), ('Exit', self.app.close))):
            self.button(self.frame, label, action).place(x=8+index*94, y=5, width=88, height=30)
        self.content = tk.Frame(self.frame, bg=BG)
        self.content.place(x=8, y=41, width=464, height=190)
        self.status = tk.Label(self.frame, bg=BG, fg=MUTED, anchor='w', font=('DejaVu Sans', -10))
        self.status.place(x=8, y=235, width=464, height=17)
        tk.Label(self.frame, text='N: network  W: watch  R: refresh  Tab: focus  Esc: chart',
                 bg=BG, fg=MUTED, font=('DejaVu Sans', -10)).place(x=8, y=254, width=464, height=17)
        self.draw()
        self.frame.winfo_children()[0].focus_set()
        self.poll_id = self.root.after(200, self.poll)

    def button(self, parent, label, action):
        widget = tk.Button(parent, text=label, command=action, bg=PANEL,
                           fg=BG if self.root.tk.call('tk', 'windowingsystem') == 'aqua' else INK,
                           activebackground='#294050', activeforeground=INK, relief='flat', bd=0,
                           highlightthickness=2, highlightbackground=PANEL, highlightcolor=ACCENT,
                           font=('DejaVu Sans', -11), takefocus=True)
        for key in ('<Return>', '<KP_Enter>'):
            widget.bind(key, lambda event: (event.widget.invoke(), 'break')[1])
        return widget

    def label(self, text, x, y, width=300, color=INK, size=12):
        from tkinter.font import Font
        font = Font(root=self.root, family='DejaVu Sans', size=-size)
        if font.measure(text) > width - 4:
            while text and font.measure(text + '…') > width - 4:
                text = text[:-1]
            text += '…'
        widget = tk.Label(self.content, text=text, bg=BG, fg=color, anchor='w', font=font)
        widget._display_font = font
        widget.place(x=x, y=y, width=width, height=23)
        return widget

    def show(self, page):
        self.visible, self.page, self.form = True, page, False
        self.delete_pending = False
        self.frame.place(x=0, y=0, relwidth=1, relheight=1)
        self.frame.lift()
        self.draw()
        self.frame.winfo_children()[0 if page == 'network' else 1].focus_set()

    def hide(self):
        self.visible = False
        self.frame.place_forget()
        self.app.canvas.focus_set()
        self.app.refresh_all()

    def draw(self):
        if not self.visible or self.form:
            return
        focused = self.root.focus_get()
        in_content = focused is not None and str(focused).startswith(str(self.content)+'.')
        for child in self.content.winfo_children():
            child.destroy()
        if self.page == 'network':
            self.label('Bitcoin · mainnet', 0, 0, 464, ACCENT, 18)
            row = self.network
            if row is None:
                self.label('Waiting for a successful network refresh.', 0, 46, 464, MUTED)
            else:
                self.label('Block ' + format(row['height'], ','), 0, 34, 464, size=26)
                self.label(f"{row['transactions']:,} transactions · {row['size']/1_000_000:.2f} MB", 0, 68, 464)
                fees = row['fees']
                self.label(f"Fees (sat/vB)  Fast {fees['fastestFee']} · 30m {fees['halfHourFee']} · 1h {fees['hourFee']}", 0, 102, 464)
                self.label(f"Economy {fees['economyFee']} · Minimum {fees['minimumFee']}", 0, 127, 464, MUTED)
                self.label(f"Mempool {row['mempool_count']:,} tx · {row['mempool_vsize']/1_000_000:.1f} MvB", 0, 161, 464)
        else:
            self.listbox = tk.Listbox(self.content, bg=PANEL, fg=INK, selectbackground='#294050',
                                     selectforeground=INK, highlightthickness=2, highlightcolor=ACCENT,
                                     relief='flat', exportselection=False, font=('DejaVu Sans', -12))
            self.listbox.place(x=0, y=0, width=142, height=145)
            for watch in self.watches:
                from tkinter.font import Font
                font = Font(root=self.root, font=self.listbox.cget('font'))
                label = watch['label']
                if font.measure(label) > 130:
                    while label and font.measure(label+'…') > 130:
                        label = label[:-1]
                    label += '…'
                self.listbox.insert('end', label)
            if self.watches:
                self.selected = min(self.selected, len(self.watches)-1)
                self.listbox.selection_set(self.selected)
            self.listbox.bind('<<ListboxSelect>>', self.select)
            self.button(self.content, 'Add', lambda: self.edit(False)).place(x=0, y=151, width=44, height=30)
            self.button(self.content, 'Edit', lambda: self.edit(True)).place(x=49, y=151, width=44, height=30)
            self.button(self.content, 'Delete' if not self.delete_pending else 'Sure?', self.remove).place(x=98, y=151, width=44, height=30)
            if not self.watches:
                self.label('Add a public Bitcoin address.', 152, 15, 310)
                self.label('Watch-only. Never enter a seed or key.', 152, 44, 310, MUTED, 11)
            else:
                watch = self.watches[self.selected]
                addr = watch['address']
                self.label(addr[:17]+'…'+addr[-12:], 152, 0, 310, MUTED, 11)
                cached = self.cache.get(addr)
                if cached:
                    self.label('Confirmed   ' + btc(cached['confirmed']), 152, 27, 310)
                    self.label('Pending      ' + btc(cached['unconfirmed']), 152, 52, 310)
                    self.label('Updated '+time.strftime('%H:%M:%S', time.localtime(cached['updated'])), 152, 77, 310, MUTED, 10)
                    for index, transaction in enumerate(cached['transactions'][:3]):
                        state = '✓' if transaction['confirmed'] else '…'
                        self.label(state+' '+transaction['txid'][:8]+'  '+btc(transaction['net']), 152, 102+index*25, 310, size=11)
                    if not cached['transactions']:
                        self.label('No recent activity', 152, 102, 310, MUTED)
                else:
                    self.label('Not refreshed yet · press R', 152, 43, 310, MUTED)
            if in_content:
                self.listbox.focus_set()
        self.status.configure(text=self.notice[:86])

    def select(self, event):
        chosen = self.listbox.curselection()
        if chosen and chosen[0] != self.selected:
            self.selected = chosen[0]
            self.delete_pending = False
            self.draw()
            self.refresh(True)

    def edit(self, existing):
        if self.storage_error:
            self.notice = 'Repair unreadable watch.json before editing; file preserved.'
            self.draw()
            return
        if existing and not self.watches:
            return
        self.form = True
        for child in self.content.winfo_children(): child.destroy()
        self.label('Edit watch' if existing else 'Add watch · public address only', 0, 0, 464, ACCENT)
        self.label('Label', 0, 35, 65)
        self.label('Address', 0, 74, 65)
        label, addr = tk.Entry(self.content), tk.Entry(self.content)
        for widget, y in ((label, 35), (addr, 74)):
            widget.configure(bg=PANEL, fg=INK, insertbackground=INK, font=('DejaVu Sans', -13),
                             highlightthickness=2, highlightcolor=ACCENT, relief='flat')
            widget.place(x=70, y=y, width=394, height=30)
        if existing:
            watch = self.watches[self.selected]
            label.insert(0, watch['label']); addr.insert(0, watch['address'])
        def save():
            candidate = list(self.watches)
            row = {'label': label.get().strip(), 'address': addr.get().strip()}
            try:
                if existing: candidate[self.selected] = row
                else: candidate.append(row)
                candidate = validate_watch(candidate)
                save_watch(candidate)
            except (OSError, ValueError, TypeError, KeyError) as error:
                self.status.configure(text=str(error)[:86])
                return
            self.watches = candidate
            self.selected = self.selected if existing else len(candidate)-1
            self.notice = 'Saved locally · press R to refresh'
            self.show('watch')
            self.refresh(True)
        self.button(self.content, 'Save', save).place(x=280, y=127, width=88, height=32)
        self.button(self.content, 'Cancel', lambda: self.show('watch')).place(x=376, y=127, width=88, height=32)
        self.label('No private keys, seeds or wallet passwords.', 0, 162, 464, MUTED, 11)
        label.focus_set()

    def remove(self):
        if not self.watches or self.storage_error: return
        if not self.delete_pending:
            self.delete_pending = True
            self.notice = 'Press Sure? to remove the selected watch (no funds move).'
            self.draw()
            return
        candidate = self.watches[:self.selected]+self.watches[self.selected+1:]
        try:
            save_watch(candidate)
        except (OSError, ValueError):
            self.notice = 'Could not save; watch retained.'
        else:
            self.watches = candidate
            self.delete_pending = False
            self.notice = 'Watch removed locally.'
        self.draw()

    def refresh(self, manual=False):
        now = time.monotonic()
        if self.closed or self.busy or now-self.last_start < 20:
            return
        if now < self.next_refresh and (not manual or self.failures):
            return
        self.busy = True
        self.last_start = now
        watch = dict(self.watches[self.selected]) if self.watches else None
        self.notice = 'Loading via Shell Tor…' if 'VITRALLIS_TOR_API' in os.environ else 'Loading via HTTPS…'
        self.status.configure(text=self.notice)
        try:
            threading.Thread(target=refresh_worker, args=(self.fetch, watch, self.events, self.cancel),
                             name='bitcoin-monitor', daemon=True).start()
        except RuntimeError:
            self.events.put_nowait((None, None, 'Cannot start network refresh'))

    def worker(self, watch):
        """Synchronous entry for deterministic fixture tests; never starts Tk work."""
        refresh_worker(self.fetch, watch, self.events, self.cancel)

    def poll(self):
        if self.closed: return
        try:
            network, watch, error = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            if network is not None: self.network = network
            if watch is not None: self.cache[watch['address']] = watch
            active = {row['address'] for row in self.watches}
            self.cache = {address: value for address, value in self.cache.items() if address in active}
            self.busy = False
            self.failures = min(self.failures+1, 4) if error else 0
            self.next_refresh = time.monotonic() + (min(300*2**self.failures, 1800) if error else 300)
            route = 'Shell Tor' if 'VITRALLIS_TOR_API' in os.environ else 'HTTPS'
            self.notice = error or f'mempool.space · {route} · refreshed '+time.strftime('%H:%M:%S')
            self.draw()
        if self.visible: self.refresh()
        self.poll_id = self.root.after(200 if self.busy else 1000, self.poll)

    def close(self):
        self.closed = True
        self.cancel.set()
        self.root.after_cancel(self.poll_id)
