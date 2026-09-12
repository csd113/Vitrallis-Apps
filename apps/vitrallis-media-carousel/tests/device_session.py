"""Opt-in SSH/display QA session; excluded from installed packages.

Run with DISPLAY=:0 python3 -B -u tests/device_session.py. Commands on stdin:
status, play, next, previous, pause, home, settings, close. The real app remains
usable by touch/keyboard. This helper prints the temporary access code for LAN
testing over the authorized SSH connection; do not retain/share that output.
It closes after ten minutes and does not change the shell or register an app.
"""
import json
from pathlib import Path
import select
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    import tkinter as tk
    from ui import App
    from main import install_shutdown_handlers
    import signal
    root = tk.Tk()
    app = App(root)
    previous = install_shutdown_handlers(app)
    started = time.monotonic()
    announced = False
    last = None

    def observe():
        nonlocal announced, last
        if app.finished:
            return
        if app.services and not announced:
            announced = True
            print(json.dumps({"ready_seconds": round(time.monotonic()-started, 2),
                              "urls": app.services.server.urls, "code": app.services.server.token}), flush=True)
        identity = (app.screen, getattr(app, "generation", None))
        if identity != last:
            item = app.playlist.current if app.playlist else None
            print(json.dumps({"screen": app.screen, "item": item["name"] if item else None,
                              "seconds": round(time.monotonic()-started, 2)}), flush=True)
            last = identity
        if select.select([sys.stdin], [], [], 0)[0]:
            command = sys.stdin.readline(128).strip()
            if command == "play" and app.services:
                row = next((row for row in app.services.library.snapshot() if row["items"]), None)
                if row:
                    app.play(row["id"])
            elif command == "next":
                app.advance()
            elif command == "previous":
                app.advance(-1)
            elif command == "pause":
                app.pause()
            elif command == "home":
                app.home()
            elif command == "settings":
                app.settings_screen()
            elif command in ("close", ""):
                app.close()
            elif command == "status":
                print(json.dumps({"screen": app.screen, "size": [root.winfo_width(), root.winfo_height()],
                                  "image_visible": app.photo is not None,
                                  "message": app.home_notice, "error": app.last_error}), flush=True)
        if time.monotonic() - started > 600:
            app.close()
        root.after(100, observe)

    root.after(100, observe)
    try:
        root.mainloop()
    finally:
        app.finish()
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    print("QA session stopped cleanly", flush=True)


if __name__ == "__main__":
    main()
