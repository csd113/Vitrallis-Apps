"""One background, explicitly requested multimedia installation at a time."""
import os
from pathlib import Path
import stat
import subprocess
import threading

from multimedia import capabilities

HELPER = Path('/usr/local/libexec/vitrallis-carousel-install-media')


def helper_ready():
    try:
        for path in (HELPER, *HELPER.parents):
            info = path.lstat()
            if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
                return False
        return HELPER.is_file() and os.access(HELPER, os.X_OK)
    except OSError:
        return False


def run_installer():
    # Drain continuously while retaining only a bounded diagnostic tail. Waiting
    # for this explicitly requested package action must never kill dpkg mid-write.
    with subprocess.Popen(['/usr/bin/sudo', '-n', str(HELPER)],
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE, start_new_session=True) as process:
        tail = b''
        while True:
            chunk = process.stderr.read(4096)
            if not chunk:
                break
            tail = (tail + chunk)[-2000:]
        return process.wait(), tail.decode('utf-8', 'replace').strip()


class Installation:
    def __init__(self):
        self.lock = threading.Lock()
        self.thread = None
        self.state = {'status': 'idle', 'message': ''}

    def snapshot(self):
        with self.lock:
            return dict(self.state, available=helper_ready())

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return dict(self.state)
            if capabilities()['ready']:
                self.state = {'status': 'ready', 'message': 'Compatible FFmpeg is already ready.'}
                return dict(self.state)
            if not helper_ready():
                raise ValueError('The platform multimedia installer is not configured. Run the documented administrator setup.')
            self.state = {'status': 'running', 'message': 'Rechecking decoders before installing Debian FFmpeg…'}
            self.thread = threading.Thread(target=self._run, name='carousel-install-media', daemon=False)
            self.thread.start()
            return dict(self.state)

    def _run(self):
        try:
            # The helper has no arguments and cannot execute package/user commands.
            # Never terminate dpkg halfway through installation when the UI closes.
            # A cold or busy system may time out its first probe. Recheck before
            # any package mutation, even when the previous cached result failed.
            if capabilities(refresh=True)['ready']:
                with self.lock:
                    self.state = {'status': 'ready', 'message': 'Compatible FFmpeg is ready; no packages changed.'}
                return
            returncode, diagnostic = run_installer()
            ready = capabilities(refresh=True)
            if returncode:
                state = {'status': 'failed', 'message': diagnostic or f'Package installation failed ({returncode}).'}
            elif not ready['ready']:
                state = {'status': 'failed', 'message': ready['webm_note']}
            else:
                state = {'status': 'ready', 'message': 'Installed and verified VP8/VP9 WebM and static WebP decoding.'}
        except (OSError, subprocess.SubprocessError) as error:
            state = {'status': 'failed', 'message': str(error)[:2000]}
        with self.lock:
            self.state = state
