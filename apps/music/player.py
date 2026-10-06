"""Bounded library/metadata work and one owned streaming FFplay decoder."""
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import random
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from owned_child import command as owned_command, starting as child_starting

EXTENSIONS = frozenset(('.mp3', '.flac', '.ogg', '.oga', '.wav'))
MAX_TRACKS, MAX_ENTRIES, MAX_DEPTH = 4000, 20000, 16
# ARMv7 cold FFmpeg startup took over ten seconds in the device audit.
# Probes run off the UI thread and close() can still kill them immediately.
MEDIA_TIMEOUT_SECONDS = 20


def scan(root, cancelled=lambda: False):
    root = Path(root)
    tracks, warning, entries = [], '', 0
    if not root.exists():
        return [], 'Add music to this folder, then Refresh'
    pending = [(root, 0)]
    while pending and not cancelled():
        folder, depth = pending.pop()
        try:
            with os.scandir(folder) as children:
                for item in children:
                    entries += 1
                    if entries > MAX_ENTRIES or len(tracks) >= MAX_TRACKS:
                        warning = 'Library limit reached; choose a smaller folder'
                        pending.clear()
                        break
                    if cancelled():
                        break
                    if item.is_symlink():
                        continue
                    if item.is_dir(follow_symlinks=False) and depth < MAX_DEPTH:
                        pending.append((Path(item.path), depth + 1))
                    elif item.is_file(follow_symlinks=False) and Path(item.name).suffix.lower() in EXTENSIONS:
                        tracks.append(Path(item.path))
        except OSError:
            warning = 'Some folders could not be read'
    return sorted(tracks, key=lambda p: (str(p.relative_to(root)).casefold(), str(p))), warning


def bounded_command(arguments, limit=65536, timeout=MEDIA_TIMEOUT_SECONDS):
    # Spool untrusted decoder output outside the package, retaining only a bound.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(arguments, stdin=subprocess.DEVNULL, stdout=output,
                                stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        if result.returncode:
            raise ValueError('Media could not be decoded')
        output.seek(0)
        data = output.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Media metadata is too large')
        return data


def clean_text(value, fallback=''):
    return ''.join(c for c in str(value) if c.isprintable())[:160] or fallback


@dataclass(frozen=True)
class Track:
    path: Path
    title: str
    artist: str = 'Unknown artist'
    album: str = 'Unknown album'
    duration: float = 0.0
    art: bytes = b''
    error: str = ''


class Probe:
    """Own short-lived metadata/artwork children, including during app shutdown."""
    def __init__(self):
        self.lock = threading.Lock()
        self.closed = False
        self.children = set()

    def __call__(self, arguments, limit=65536, timeout=MEDIA_TIMEOUT_SECONDS):
        with tempfile.TemporaryFile() as output:
            with self.lock:
                if self.closed:
                    raise ValueError('Metadata scan cancelled')
                process = subprocess.Popen(owned_command(arguments), stdin=subprocess.DEVNULL, stdout=output,
                                           stderr=subprocess.DEVNULL)
                self.children.add(process)
            try:
                if process.wait(timeout=timeout):
                    raise ValueError('Media could not be decoded')
                output.seek(0)
                data = output.read(limit + 1)
                if len(data) > limit:
                    raise ValueError('Media metadata is too large')
                return data
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=2)
                with self.lock:
                    self.children.discard(process)

    def close(self):
        with self.lock:
            self.closed = True
            children = tuple(self.children)
        for process in children:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)


def metadata(path, command=None):
    path = Path(path)
    command = command or bounded_command
    try:
        tool = shutil.which('ffprobe')
        if not tool:
            return Track(path, path.stem, error='Install system FFmpeg for metadata and playback')
        data = json.loads(command([tool, '-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_entries',
                          'format=duration:format_tags=title,artist,album:stream=codec_type:stream_tags=title,artist,album:stream_disposition=attached_pic',
                          '-of', 'json', str(path)]))
        tags = {key.lower(): value for key, value in data.get('format', {}).get('tags', {}).items()}
        # Vorbis places these tags on its audio stream instead of the container.
        # Container tags retain precedence; artwork/video stream labels do not.
        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'audio':
                for key, value in stream.get('tags', {}).items():
                    tags.setdefault(key.lower(), value)
        duration = float(data.get('format', {}).get('duration', 0))
        if not math.isfinite(duration) or duration < 0:
            duration = 0
        art = b''
        ffmpeg = shutil.which('ffmpeg')
        if ffmpeg and any(s.get('disposition', {}).get('attached_pic') for s in data.get('streams', [])):
            try:
                art = command([ffmpeg, '-v', 'error', '-protocol_whitelist', 'file,pipe', '-i', str(path), '-map', '0:v:0',
                                       '-frames:v', '1', '-vf', 'scale=112:112:force_original_aspect_ratio=decrease',
                                       '-f', 'image2pipe', '-vcodec', 'png', '-threads', '1', '-'], limit=131072)
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        return Track(path, clean_text(tags.get('title', ''), path.stem), clean_text(tags.get('artist', ''), 'Unknown artist'),
                     clean_text(tags.get('album', ''), 'Unknown album'), duration, art)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return Track(path, path.stem, error='Unreadable or corrupt media')


class Player:
    def __init__(self, clock=time.monotonic, spawn=subprocess.Popen):
        self.clock, self.spawn = clock, spawn
        self.process = None
        self.track = None
        self.volume, self.paused, self.offset, self.started = 70, False, 0.0, 0.0
        self.pause_pending = False
        self.error = ''

    def position(self):
        value = self.offset + (0 if self.paused or not self.process else self.clock() - self.started)
        return min(value, self.track.duration) if self.track and self.track.duration else value

    def stop(self):
        if self.process is not None:
            if self.paused and self.process.poll() is None:
                self.process.send_signal(signal.SIGCONT)
            self.process.terminate() if self.process.poll() is None else None
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
            self.process = None
        self.paused = False
        self.pause_pending = False

    def play(self, track, offset=0.0):
        self.stop()
        self.track, self.offset, self.started = track, max(0.0, offset), self.clock()
        self.error = ''
        tool = shutil.which('ffplay')
        if not tool:
            self.error = 'Playback needs system FFmpeg / ffplay'
            return False
        if track.error:
            self.error = track.error
            return False
        try:
            self.process = self.spawn(owned_command([tool, '-nodisp', '-autoexit', '-nostats', '-loglevel', 'error',
                                       '-ss', str(self.offset), '-volume', str(self.volume),
                                       '-protocol_whitelist', 'file,pipe', '-i', str(track.path)]),
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            self.error = 'Audio backend could not start'
            return False

    def pause(self):
        if not self.process or self.process.poll() is not None:
            return
        if self.paused:
            if not self.pause_pending:
                self.process.send_signal(signal.SIGCONT)
            self.pause_pending = False
            self.started = self.clock()
            self.paused = False
        else:
            self.offset = self.position()
            self.pause_pending = child_starting(self.process)
            if not self.pause_pending:
                self.process.send_signal(signal.SIGSTOP)
            self.paused = True

    def seek(self, offset):
        if self.track and self.process:
            paused = self.paused
            limit = self.track.duration or max(0, offset)
            self.play(self.track, min(max(0, offset), limit))
            if paused:
                self.pause()

    def set_volume(self, value):
        position, paused = self.position(), self.paused
        self.volume = max(0, min(100, int(value)))
        if self.process and self.track:
            self.play(self.track, position)
            if paused:
                self.pause()

    def finished(self):
        if not self.process:
            return False
        if self.process.poll() is None:
            if self.pause_pending and not child_starting(self.process):
                self.process.send_signal(signal.SIGSTOP)
                self.pause_pending = False
            return False
        result = self.process.returncode
        self.offset = self.position()
        self.process.wait()
        self.process = None
        self.paused = self.pause_pending = False
        if result:
            self.error = 'Playback failed; check media and audio device'
        return result == 0


def next_index(index, count, direction=1, shuffle=False, repeat='off', rng=random):
    if not count:
        return None
    if repeat == 'one':
        return index
    if shuffle and count > 1:
        choices = [i for i in range(count) if i != index]
        return rng.choice(choices)
    target = index + direction
    return target % count if repeat == 'all' else target if 0 <= target < count else None
