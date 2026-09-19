"""Cached, real decoder checks for the formats offered by the management UI."""
from functools import lru_cache
import os
from pathlib import Path
import shutil
import subprocess
import threading

ASSETS = Path(__file__).resolve().parent / 'assets'
_LOCK = threading.Lock()
_LAST = None


def executable_key(name):
    path = shutil.which(name)
    if not path:
        return None
    try:
        info = os.stat(path)
        return path, info.st_mtime_ns, info.st_size
    except OSError:
        return None


def decode_check(ffmpeg, ffprobe, path):
    """Require inspection and actual pixel output; binary presence proves nothing."""
    try:
        info = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0',
                               '-show_entries', 'stream=width,height', '-of', 'csv=p=0', str(path)],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=15, check=False)
        if info.returncode or info.stdout.strip() != b'16,16':
            return False
        result = subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-threads', '1',
                                 '-filter_threads', '1', '-i', str(path), '-frames:v', '1',
                                 '-threads', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=15, check=False)
        return result.returncode == 0 and len(result.stdout) == 16 * 16 * 3
    except (OSError, subprocess.SubprocessError):
        return False


@lru_cache(maxsize=2)
def _detect(ffmpeg, ffprobe):
    checks = {'vp8': False, 'vp9': False, 'webp': False}
    if ffmpeg and ffprobe:
        for kind, filename in (('vp8', 'capability-vp8.webm'), ('vp9', 'capability-vp9.webm'),
                               ('webp', 'capability.webp')):
            checks[kind] = decode_check(ffmpeg[0], ffprobe[0], ASSETS / filename)
    missing = []
    if not ffmpeg: missing.append('ffmpeg')
    if not ffprobe: missing.append('ffprobe')
    missing += [name for name, ready in checks.items() if not ready]
    webm = checks['vp8'] and checks['vp9']
    return dict(checks, webm=webm, ready=all(checks.values()), missing=missing,
                webm_note='VP8/VP9 WebM and static WebP decode verified.' if all(checks.values())
                else 'Missing or failed decode checks: ' + ', '.join(missing))


def capabilities(refresh=False, blocking=True):
    # HTTP status reads return the previous complete result while an explicitly
    # requested background recheck is running; never hold a browser poll on FFmpeg.
    global _LAST
    if not _LOCK.acquire(blocking=blocking):
        return dict(_LAST, missing=list(_LAST['missing'])) if _LAST else {
            'vp8': False, 'vp9': False, 'webp': False, 'webm': False, 'ready': False,
            'missing': [], 'webm_note': 'Checking multimedia decoders…'}
    try:
        if refresh:
            _detect.cache_clear()
        result = _detect(executable_key('ffmpeg'), executable_key('ffprobe'))
        _LAST = dict(result, missing=list(result['missing']))
        return dict(_LAST, missing=list(_LAST['missing']))
    finally:
        _LOCK.release()
