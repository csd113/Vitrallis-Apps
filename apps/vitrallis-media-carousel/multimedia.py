"""Cached, real decoder checks and verified video acceleration selection.

Presence of a binary proves nothing, so every capability here is established by
decoding a sample and inspecting the decoder's own log output. Hardware
acceleration is only reported as available when FFmpeg's log shows that a
hardware pixel format was actually chosen for that codec; otherwise the answer
is "software", which is always a working fallback.

Detection is cancellable: every step checks the caller's event first, so a
shutting-down application never has to wait for a slow probe thread.
"""
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import time

ASSETS = Path(__file__).resolve().parent / 'assets'
_LOCK = threading.Lock()
_LAST = None
_LAST_KEY = None
_BACKEND_CACHE = {}

# FFmpeg prints one of these while negotiating a hardware decode format.
HWACCEL_EVIDENCE = re.compile(r"requires hwaccel (\S+) initialisation")
HWACCEL_SELECTED = re.compile(
    r"Selecting decoder '(\S+)' because of requested hwaccel method (\S+)")

# One small committed fixture per codec the app accepts. A codec without a
# fixture is never claimed as accelerated.
CODEC_FIXTURE = {'vp8': 'capability-vp8.webm', 'vp9': 'capability-vp9.webm'}

# Preferred order per platform; anything not verified is simply skipped.
PLATFORM_METHODS = {
    'darwin': ('videotoolbox',),
    'linux': ('vaapi', 'v4l2m2m', 'vdpau'),
    'win32': ('d3d11va', 'dxva2', 'cuda'),
}
FALLBACK_METHODS = ('videotoolbox', 'vaapi', 'v4l2m2m', 'd3d11va', 'dxva2', 'cuda')

MISSING = {
    'method': None, 'name': 'software', 'verified': False,
    'reason': 'no verified hardware decoder for this codec',
}


class DetectionCancelled(Exception):
    """The caller withdrew its probe request before it finished."""


def _check(cancel):
    if cancel is not None and cancel.is_set():
        raise DetectionCancelled()


def executable_key(name):
    path = shutil.which(name)
    if not path:
        return None
    try:
        info = os.stat(path)
        return path, info.st_mtime_ns, info.st_size
    except OSError:
        return None


def _terminate(process):
    """Kill a probe child, tolerating an already-exited group."""
    for signal_number in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, signal_number)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            process.wait(timeout=0.5)
            return
        except subprocess.TimeoutExpired:
            continue


def _run(arguments, cancel, timeout, stdout=subprocess.PIPE, text=False):
    """One bounded probe child, killed as soon as the caller withdraws."""
    _check(cancel)
    process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=stdout,
                               stderr=subprocess.PIPE, start_new_session=True, text=text)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                out, err = process.communicate(timeout=0.1)
                return subprocess.CompletedProcess(arguments, process.returncode, out, err)
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    _terminate(process)
                    raise DetectionCancelled()
                if time.monotonic() >= deadline:
                    _terminate(process)
                    raise
    finally:
        if process.poll() is None:
            _terminate(process)


def decode_check(ffmpeg, ffprobe, path, cancel=None):
    """Require inspection and actual pixel output; binary presence proves nothing."""
    try:
        info = _run([ffprobe, '-v', 'error', '-select_streams', 'v:0',
                     '-show_entries', 'stream=width,height', '-of', 'csv=p=0', str(path)],
                    cancel, 15)
        if info.returncode or info.stdout.strip() != b'16,16':
            return False
        result = _run([ffmpeg, '-v', 'error', '-nostdin', '-threads', '1',
                       '-filter_threads', '1', '-i', str(path), '-frames:v', '1',
                       '-threads', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
                      cancel, 15)
        return result.returncode == 0 and len(result.stdout) == 16 * 16 * 3
    except (OSError, subprocess.SubprocessError):
        return False


def hardware_methods(ffmpeg, cancel=None):
    """The -hwaccel methods this exact FFmpeg build advertises."""
    if not ffmpeg:
        return ()
    try:
        result = _run([ffmpeg[0], '-hide_banner', '-hwaccels'], cancel, 15, text=True)
    except (OSError, subprocess.SubprocessError):
        return ()
    if result.returncode:
        return ()
    names = []
    for line in result.stdout.splitlines():
        token = line.strip()
        if not token or ' ' in token or token.endswith(':'):
            continue
        names.append(token)
    return tuple(names)


def _verify_method(ffmpeg, method, codec, cancel=None):
    """Decode the codec fixture with -hwaccel and confirm hardware negotiation."""
    fixture = ASSETS / CODEC_FIXTURE.get(codec, '')
    if not fixture.name or not fixture.is_file():
        return False, 'no fixture for codec ' + codec
    command = [ffmpeg[0], '-v', 'debug', '-nostdin', '-xerror', '-threads', '1',
               '-filter_threads', '1', '-hwaccel', method, '-i', str(fixture),
               '-frames:v', '1', '-f', 'null', '-']
    try:
        result = _run(command, cancel, 25, stdout=subprocess.DEVNULL, text=True)
    except (OSError, subprocess.SubprocessError) as error:
        return False, 'probe failed: ' + type(error).__name__
    if result.returncode:
        return False, 'ffmpeg rejected -hwaccel ' + method
    for name in HWACCEL_EVIDENCE.findall(result.stderr or ''):
        if name.lower().endswith(method.lower()):
            return True, name
    return False, 'decoder stayed in software'


def policy():
    """auto | off | force, from CAROUSEL_HWACCEL; unknown values mean auto."""
    value = (os.environ.get('CAROUSEL_HWACCEL') or 'auto').strip().lower()
    return value if value in ('auto', 'off', 'force') else 'auto'


def platform_candidates(methods):
    platform = 'darwin' if os.sys.platform == 'darwin' else os.sys.platform
    ordered = list(PLATFORM_METHODS.get(platform, ()))
    ordered += [name for name in FALLBACK_METHODS if name not in ordered]
    return tuple(name for name in ordered if name in methods)


def _probe_backend(ffmpeg, codec, mode, cancel):
    methods = hardware_methods(ffmpeg, cancel)
    if mode == 'off':
        return dict(MISSING, reason='CAROUSEL_HWACCEL=off')
    if not methods:
        return dict(MISSING, reason='this FFmpeg build advertises no hardware acceleration')
    notes = []
    for method in platform_candidates(methods):
        verified, detail = _verify_method(ffmpeg, method, codec, cancel)
        if verified:
            return {'method': method, 'name': detail, 'verified': True,
                    'reason': '%s decoded through %s' % (codec, detail)}
        notes.append('%s: %s' % (method, detail))
    return dict(MISSING, reason='; '.join(notes) or 'no candidate method for this platform')


def video_backend(codec, ffmpeg=None, cancel=None):
    """{'method', 'name', 'verified', 'reason'} for one codec; safe to call often."""
    ffmpeg = ffmpeg if ffmpeg is not None else executable_key('ffmpeg')
    if not ffmpeg or not codec:
        return dict(MISSING)
    mode = policy()
    key = (ffmpeg, codec, mode)
    cached = _BACKEND_CACHE.get(key)
    if cached is not None:
        return dict(cached)
    result = _probe_backend(ffmpeg, codec, mode, cancel)
    _BACKEND_CACHE[key] = result
    return dict(result)


def acceleration_report(ffmpeg=None, cancel=None):
    """What the decoder stack really offers, for logs and /api/state."""
    ffmpeg = ffmpeg if ffmpeg is not None else executable_key('ffmpeg')
    codecs = {codec: video_backend(codec, ffmpeg, cancel) for codec in sorted(CODEC_FIXTURE)}
    return {'policy': policy(), 'methods': list(hardware_methods(ffmpeg, cancel)),
            'codecs': codecs}


def _detect(ffmpeg, ffprobe, cancel=None):
    checks = {'vp8': False, 'vp9': False, 'webp': False}
    if ffmpeg and ffprobe:
        for kind, filename in (('vp8', 'capability-vp8.webm'), ('vp9', 'capability-vp9.webm'),
                               ('webp', 'capability.webp')):
            checks[kind] = decode_check(ffmpeg[0], ffprobe[0], ASSETS / filename, cancel)
    missing = []
    if not ffmpeg:
        missing.append('ffmpeg')
    if not ffprobe:
        missing.append('ffprobe')
    missing += [name for name, ready in checks.items() if not ready]
    webm = checks['vp8'] and checks['vp9']
    report = (acceleration_report(ffmpeg, cancel) if ffmpeg
              else {'policy': policy(), 'methods': [], 'codecs': {}})
    accelerated = sorted(codec for codec, backend in report['codecs'].items() if backend['verified'])
    return dict(checks, webm=webm, ready=all(checks.values()), missing=missing,
                acceleration=report, accelerated=accelerated,
                webm_note='VP8/VP9 WebM and static WebP decode verified.' if all(checks.values())
                else 'Missing or failed decode checks: ' + ', '.join(missing))


def _empty():
    return {'vp8': False, 'vp9': False, 'webp': False, 'webm': False, 'ready': False,
            'missing': [], 'accelerated': [],
            'acceleration': {'policy': policy(), 'methods': [], 'codecs': {}},
            'webm_note': 'Checking multimedia decoders…'}


def _copy(result):
    return dict(result, missing=list(result['missing']), accelerated=list(result['accelerated']),
                acceleration={'policy': result['acceleration']['policy'],
                              'methods': list(result['acceleration']['methods']),
                              'codecs': {name: dict(value)
                                         for name, value in result['acceleration']['codecs'].items()}})


def capabilities(refresh=False, blocking=True, cancel=None):
    """Cached capability report; the previous complete result wins over blocking.

    HTTP status reads return the previous complete result while an explicitly
    requested background recheck is running; never hold a browser poll on FFmpeg.
    """
    global _LAST, _LAST_KEY
    keys = (executable_key('ffmpeg'), executable_key('ffprobe'))
    if refresh:
        _BACKEND_CACHE.clear()
    elif _LAST is not None and _LAST_KEY == keys:
        return _copy(_LAST)
    if not _LOCK.acquire(blocking=blocking):
        return _copy(_LAST) if _LAST else _empty()
    try:
        keys = (executable_key('ffmpeg'), executable_key('ffprobe'))
        if not refresh and _LAST is not None and _LAST_KEY == keys:
            return _copy(_LAST)
        try:
            result = _detect(keys[0], keys[1], cancel)
        except DetectionCancelled:
            return _copy(_LAST) if _LAST else _empty()
        _LAST, _LAST_KEY = result, keys
        return _copy(result)
    finally:
        _LOCK.release()
