#!/bin/sh
# Capture the prop-atlas validation views on the PocketCHIP.
#
#   atlas_views.sh <output-dir> [binary]
#
# The 25-view set in `capture_views.sh` is the general correctness gate; this
# list exists for the specific failure modes an atlas introduces, which need the
# camera much closer to a prop than that set ever gets:
#
# * `macro_*`   — a prop filling most of the frame, where a wrong UV or a
#                 half-texel inset error is obvious;
# * `oblique_*` — a long prop run seen at a grazing angle, where an atlas cell
#                 boundary in the wrong place shows as a seam;
# * `far_*`     — the same props from across the level, where the deepest mip
#                 levels are sampled and neighbours would bleed;
# * `floor_*`   — a downward look that should be unchanged by the atlas, as a
#                 control for the lighting pass.
#
# Capture the same list twice with `LIMINAL_PROP_ATLAS=0` and `=1` on one build
# and diff: the two runs differ only by the atlas.
OUT=$1
BIN=${2:-$HOME/places-dev/places}
mkdir -p "$OUT"
export DISPLAY=:0 LIMINAL_LEVEL=places_demo LIMINAL_QUALITY=low
export LIMINAL_VSYNC=off LIMINAL_NO_LIGHTMAPS=0
export LIMINAL_BENCH=1 LIMINAL_BENCH_FRAMES=6 LIMINAL_CAPTURE_FRAME=3
export LIMINAL_STATE_ROOT=${LIMINAL_STATE_ROOT:-/home/chip/p2-state/linear}
VIEWS="
macro_office_desk:3.3,5.4,90:90,-14
macro_kitchen_run:55.5,6.2,180:180,-4
macro_living_couch:59.6,6.4,90:90,-6
macro_pool_chairs:6.0,15.0,90:90,-8
oblique_pool_deck:2.0,17.0,20:20,-12
oblique_office_wall:2.0,8.6,10:10,-6
far_pool_wide:14.0,13.0,45:45,0
far_home_approach:50.8,12.6,90:90,0
floor_office:5.0,5.6,74:74,-55
floor_deck:10.0,12.0,0:0,-60
"
for view in $VIEWS; do
    NAME=${view%%:*}
    REST=${view#*:}
    SPAWN=${REST%%:*}
    CAMERA=${REST#*:}
    if [ -n "$CAMERA" ]; then
        env LIMINAL_SPAWN="$SPAWN" LIMINAL_CAMERA="$CAMERA" LIMINAL_CAPTURE="$OUT/$NAME.png" "$BIN" > "$OUT/$NAME.log" 2>&1
    else
        env LIMINAL_SPAWN="$SPAWN" LIMINAL_CAPTURE="$OUT/$NAME.png" "$BIN" > "$OUT/$NAME.log" 2>&1
    fi
    if [ -f "$OUT/$NAME.png" ]; then echo "ok   $NAME"; else echo "FAIL $NAME"; fi
done
