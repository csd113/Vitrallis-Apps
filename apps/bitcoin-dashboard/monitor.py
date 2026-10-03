"""Bounded watch-only mainnet data and local watch-list storage."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time

API = 'https://mempool.space/api/'
MAX_MONEY = 21_000_000 * 100_000_000
WATCH_FILE = Path(os.environ.get('VITRALLIS_APP_DATA_DIR', str(Path.home() / 'Documents/Vitrallis/AppData/io.vitrallis.bitcoindashboard'))) / 'watch.json'
BASE58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
BECH32 = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'


def uint(value, maximum=MAX_MONEY):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('Invalid unsigned integer')
    return value


def address(value):
    if not isinstance(value, str) or not 14 <= len(value) <= 90:
        raise ValueError('Enter a mainnet Bitcoin address')
    if value.startswith(('1', '3')):
        number = 0
        for char in value:
            if char not in BASE58:
                raise ValueError('Invalid address character')
            number = number * 58 + BASE58.index(char)
        raw = b'\0' * (len(value) - len(value.lstrip('1'))) + number.to_bytes((number.bit_length()+7)//8, 'big')
        if len(raw) != 25 or raw[0] not in (0, 5) or hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4] != raw[-4:]:
            raise ValueError('Invalid address checksum')
        return value
    if value.lower() != value and value.upper() != value:
        raise ValueError('Mixed-case address')
    value = value.lower()
    if not value.startswith('bc1'):
        raise ValueError('Use a Bitcoin mainnet address')
    try:
        data = [BECH32.index(char) for char in value[3:]]
    except ValueError as error:
        raise ValueError('Invalid address character') from error
    checksum = 1
    for item in [3, 3, 0, 2, 3] + data:  # HRP expansion for "bc".
        top = checksum >> 25
        checksum = (checksum & 0x1ffffff) << 5 ^ item
        for bit, generator in enumerate((0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)):
            if top >> bit & 1:
                checksum ^= generator
    if len(data) < 7 or data[0] > 16 or checksum != (1 if data[0] == 0 else 0x2bc830a3):
        raise ValueError('Invalid witness checksum')
    accumulator = bits = 0
    program = []
    for item in data[1:-6]:
        accumulator = (accumulator << 5 | item) & 0xfff
        bits += 5
        if bits >= 8:
            bits -= 8
            program.append(accumulator >> bits & 255)
    if bits >= 5 or accumulator << (8-bits) & 255 or not 2 <= len(program) <= 40:
        raise ValueError('Invalid witness program')
    if data[0] == 0 and len(program) not in (20, 32):
        raise ValueError('Invalid witness length')
    return value


def balances(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid address statistics')
    result = {}
    for name, field in (('confirmed', 'chain_stats'), ('unconfirmed', 'mempool_stats')):
        stats = data[field]
        if not isinstance(stats, dict):
            raise ValueError('Invalid address statistics')
        # Lifetime received/spent totals may exceed supply when coins revisit
        # an address. Bound the cumulative counters separately from its balance.
        result[name] = uint(stats['funded_txo_sum'], 2**64-1) - uint(stats['spent_txo_sum'], 2**64-1)
        if abs(result[name]) > MAX_MONEY or (name == 'confirmed' and result[name] < 0):
            raise ValueError('Invalid address balance')
    return result


def transactions(rows, watched):
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError('Invalid transaction list')
    result = []
    for row in rows[:6]:
        if not isinstance(row, dict):
            raise ValueError('Invalid transaction')
        txid = row['txid']
        if not isinstance(txid, str) or not re.fullmatch('[0-9a-f]{64}', txid):
            raise ValueError('Invalid transaction ID')
        status = row['status']
        if not isinstance(status, dict) or type(status['confirmed']) is not bool:
            raise ValueError('Invalid confirmation')
        inputs, outputs = row['vin'], row['vout']
        if any(not isinstance(items, list) or len(items) > 10000 for items in (inputs, outputs)):
            raise ValueError('Invalid transaction inputs/outputs')
        incoming = outgoing = 0
        for output in outputs:
            if not isinstance(output, dict):
                raise ValueError('Invalid transaction output')
            amount = uint(output['value'])
            if output.get('scriptpubkey_address') == watched:
                incoming += amount
        for item in inputs:
            if not isinstance(item, dict):
                raise ValueError('Invalid transaction input')
            previous = item.get('prevout')
            if previous is not None:
                if not isinstance(previous, dict):
                    raise ValueError('Invalid previous output')
                amount = uint(previous['value'])
                if previous.get('scriptpubkey_address') == watched:
                    outgoing += amount
        uint(incoming)
        uint(outgoing)
        result.append({'txid': txid, 'confirmed': status['confirmed'], 'net': incoming-outgoing})
    return result


def network_snapshot(fetch):
    blocks = fetch('v1/blocks', API)
    if not isinstance(blocks, list) or not blocks or len(blocks) > 100:
        raise ValueError('Invalid blocks')
    block = blocks[0]
    if not isinstance(block, dict):
        raise ValueError('Invalid block')
    fees = fetch('v1/fees/recommended', API)
    pool = fetch('mempool', API)
    if not isinstance(fees, dict) or not isinstance(pool, dict):
        raise ValueError('Invalid network response')
    return {'height': uint(block['height'], 100_000_000),
            'block_time': uint(block['timestamp'], int(time.time())+300),
            'transactions': uint(block['tx_count'], 10_000_000),
            'size': uint(block['size'], 10_000_000),
            'fees': {name: uint(fees[name], 1_000_000) for name in
                     ('fastestFee', 'halfHourFee', 'hourFee', 'economyFee', 'minimumFee')},
            'mempool_count': uint(pool['count'], 100_000_000),
            'mempool_vsize': uint(pool['vsize'], 100_000_000_000),
            'updated': time.time()}


def validate_watch(rows):
    if not isinstance(rows, list) or len(rows) > 8:
        raise ValueError('Watch list supports up to eight addresses')
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'label', 'address'}:
            raise ValueError('Invalid watch entry')
        label = row['label']
        if not isinstance(label, str) or not 1 <= len(label) <= 24 or any(ord(char) < 32 for char in label):
            raise ValueError('Label must contain 1–24 readable characters')
        watched = address(row['address'])
        if watched in seen:
            raise ValueError('Address is already watched')
        seen.add(watched)
        result.append({'label': label, 'address': watched})
    return result


def load_watch(path=WATCH_FILE):
    try:
        from storage_paths import private_parent
        private_parent(path, create=False)
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except FileNotFoundError:
        return []
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.getuid() or info.st_size > 16384):
            raise ValueError('Invalid watch-list file')
        data = stream.read(16385)
    if len(data) > 16384:
        raise ValueError('Watch list is too large')
    return validate_watch(json.loads(data))


def save_watch(rows, path=WATCH_FILE):
    rows = validate_watch(rows)  # Validate complete replacement before mutation.
    from storage_paths import private_parent
    private_parent(path)
    info = path.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise OSError('Unsafe watch-list directory')
    descriptor, name = tempfile.mkstemp(prefix='.watch-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(rows, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
