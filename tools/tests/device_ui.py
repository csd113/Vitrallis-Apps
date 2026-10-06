"""Explicit, manual UI probes for the isolated PocketCHIP hardware audit.

Run only while this worker owns the device. Evidence lives outside packages.
The events use the real X session; they do not certify physical input hardware.
"""

import argparse
import json
import re
import shlex
import subprocess
import time
from pathlib import Path

DEST = "chip@192.168.81.1"
REMOTE = "/home/chip/vitrallis-apps-hardware-2026-10-03"
LOCAL = Path(__file__).resolve().parents[2] / "target/apps-hardware-2026-10-03"
SSH = ["ssh", "-oBatchMode=yes", "-oConnectTimeout=10", DEST]


def lua(code):
    result = subprocess.run(
        SSH + ["DISPLAY=:0 " + shlex.join(["awesome-client", code])],
        check=True, capture_output=True, text=True, timeout=20,
    ).stdout.strip()
    if "Error during execution:" in result:
        raise RuntimeError(result)
    return result


def key(name):
    value = json.dumps(name)
    return lua(f'root.fake_input("key_press",{value});'
               f'root.fake_input("key_release",{value});return "key sent"')


def click(x, y):
    x, y = int(x), int(y)
    if not (0 <= x < 480 and 0 <= y < 272):
        raise ValueError("Pointer outside device display")
    return lua(f'mouse.coords({{x={x},y={y}}});root.fake_input("button_press",1);'
               'root.fake_input("button_release",1);return "click sent"')


def shot(name):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,90}", name):
        raise ValueError("Unsafe evidence name")
    LOCAL.mkdir(parents=True, exist_ok=True)
    subprocess.run(SSH + ["install -d -m 700 " + shlex.quote(REMOTE)],
                   check=True, timeout=15)
    target = REMOTE + "/" + name + ".png"
    lua('local Gdk=require("lgi").Gdk;local d=Gdk.Display.open(":0");'
        'if not d then error("Screenshot display unavailable") end;'
        'local ok,err=pcall(function() local w=d:get_default_screen():get_root_window();'
        'Gdk.pixbuf_get_from_window(w,0,0,480,272):savev('
        + json.dumps(target) + ',"png",{},{});end);'
        'd:close();collectgarbage("collect");if not ok then error(err) end;return "saved"')
    path = LOCAL / (name + ".png")
    subprocess.run(["scp", "-oBatchMode=yes", "-oConnectTimeout=10",
                    DEST + ":" + target, str(path)], check=True, timeout=20)
    return path


def chord(name, modifier="Control_L"):
    return lua('root.fake_input("key_press",' + json.dumps(modifier) + ');'
               'root.fake_input("key_press",' + json.dumps(name) + ');'
               'root.fake_input("key_release",' + json.dumps(name) + ');'
               'root.fake_input("key_release",' + json.dumps(modifier) + ');return "sent"')


def wait_window(name, timeout="45"):
    seconds = int(timeout)
    if not 1 <= seconds <= 60:
        raise ValueError("Window wait must be bounded")
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        result = lua('for _,c in ipairs(client.get()) do if c.name==' + json.dumps(name)
                     + ' and c==client.focus then return "ready" end end;return "waiting"')
        if '"ready"' in result:
            return {"window": name, "wait_seconds": time.monotonic() - started}
        time.sleep(.5)
    raise TimeoutError("Expected app window did not take focus: " + name)


def type_ascii(value):
    symbols = {" ": "space", "/": "slash", ".": "period", "-": "minus",
               "_": "minus", "!": "1", "(": "9", ")": "0", ":": "semicolon",
               "\n": "Return", "*": "8", "%": "5", "+": "equal",
               "=": "equal", "?": "slash", ",": "comma"}
    calls = []
    for char in value:
        if not char.isascii() or (not char.isprintable() and char != "\n"):
            raise ValueError("Printable ASCII input required")
        if not (char.isalnum() or char in symbols):
            raise ValueError("Unsupported ASCII key")
        shift = char in "_!():*%+?" or char.isupper()
        if shift:
            calls.append('root.fake_input("key_press","Shift_L")')
        name = json.dumps(symbols.get(char, char.lower()))
        calls.extend([f'root.fake_input("key_press",{name})',
                      f'root.fake_input("key_release",{name})'])
        if shift:
            calls.append('root.fake_input("key_release","Shift_L")')
    return lua(";".join(calls) + ';return "typed"')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["key", "click", "shot", "chord", "type", "windows", "wait"])
    parser.add_argument("args", nargs="*")
    args = parser.parse_args()
    if args.action == "windows":
        print(lua('local a={};for _,c in ipairs(client.get()) do '
                  'local g=c:geometry();a[#a+1]=string.format("%q pid=%s visible=%s focus=%s %dx%d+%d+%d",'
                  'c.name or "",tostring(c.pid),tostring(c:isvisible()),tostring(c==client.focus),'
                  'g.width,g.height,g.x,g.y);end;return table.concat(a,"\\n")'))
    elif args.action == "wait":
        print(wait_window(*args.args))
    else:
        print(globals()[args.action](*args.args))
