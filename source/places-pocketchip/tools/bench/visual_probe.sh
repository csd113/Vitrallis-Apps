#!/bin/sh
# Report the window geometry/depth of a running Places instance and the visual
# the GL context landed on. Pass-3 diagnostic for the X11 presentation audit.
#
#   visual_probe.sh <binary> <env assignments...>
cd "$HOME/places-dev" || exit 1
BIN=${1:-./places}
if [ $# -gt 0 ]; then shift; fi

cat > /tmp/winchk.py <<'PY'
import ctypes
class Attr(ctypes.Structure):
    _fields_=[("x",ctypes.c_int),("y",ctypes.c_int),("width",ctypes.c_int),("height",ctypes.c_int),
              ("border_width",ctypes.c_int),("depth",ctypes.c_int),("visual",ctypes.c_void_p),
              ("root",ctypes.c_ulong),("class_",ctypes.c_int),("bit_gravity",ctypes.c_int),
              ("win_gravity",ctypes.c_int),("backing_store",ctypes.c_int),("backing_planes",ctypes.c_ulong),
              ("backing_pixel",ctypes.c_ulong),("save_under",ctypes.c_int),("colormap",ctypes.c_ulong),
              ("map_installed",ctypes.c_int),("map_state",ctypes.c_int),("all_event_masks",ctypes.c_long),
              ("your_event_mask",ctypes.c_long),("do_not_propagate_mask",ctypes.c_long),
              ("override_redirect",ctypes.c_int),("screen",ctypes.c_void_p)]
x=ctypes.CDLL("libX11.so.6"); x.XOpenDisplay.restype=ctypes.c_void_p
d=x.XOpenDisplay(b":0"); x.XDefaultRootWindow.restype=ctypes.c_ulong
root=x.XDefaultRootWindow(ctypes.c_void_p(d))
r=ctypes.c_ulong(); p=ctypes.c_ulong(); kids=ctypes.POINTER(ctypes.c_ulong)(); n=ctypes.c_uint()
x.XQueryTree(ctypes.c_void_p(d), ctypes.c_ulong(root), ctypes.byref(r), ctypes.byref(p),
             ctypes.byref(kids), ctypes.byref(n))
for i in range(n.value):
    w=kids[i]; a=Attr()
    x.XGetWindowAttributes(ctypes.c_void_p(d), ctypes.c_ulong(w), ctypes.byref(a))
    if a.map_state==2 and a.width>100:
        print("WIN %s %dx%d depth=%d override=%d" % (hex(w), a.width, a.height, a.depth, a.override_redirect))
PY

DISPLAY=:0 LIMINAL_LEVEL=places_demo LIMINAL_VERBOSE=1 LIMINAL_BENCH=1 \
    LIMINAL_BENCH_FRAMES=100000 LIMINAL_VSYNC=off LIMINAL_SPAWN="2,5.6,74" \
    LIMINAL_STATE_ROOT=/home/chip/p2-state/linear \
    env "$@" "$BIN" > /tmp/v.log 2>&1 &
PID=$!
sleep 9
DISPLAY=:0 python3 /tmp/winchk.py
echo "   gl: $(grep -m1 -iE 'renderer|vendor' /tmp/v.log | head -c 120)"
kill $PID 2>/dev/null
sleep 1
# (the caller kills any stray game instance; matching on the binary name from
# inside this script would also match the shell that launched it)
exit 0
