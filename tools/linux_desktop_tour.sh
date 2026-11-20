#!/usr/bin/env bash
# The app's tour on a Linux desktop's own window manager (polyglotic-hq 550),
# for what a person sees there: inside a session from tools/linux_session.sh
# with LINUX_SESSION_SCREEN=gnome or kde, a full-screen Wayland window is
# shown and focused (a video or a game beneath), the window manager's picture
# taker answers the tour's requests, and the app from source captions what
# the PC plays and the mic over it (tools/app_tour.py --real-capture).
#
#   bash tools/linux_desktop_tour.sh gnome|kde OUT
#
# Pictures: OUT/tour/*.png by each window's own grab(), and OUT/desk/*.png by
# the window manager - its virtual screen, never a person's.
set -uo pipefail
if [ "${GITHUB_ACTIONS:-}" != true ] || [ "$(uname -s)" != Linux ]; then
  echo "550: this runs only on GitHub's Linux runners"; exit 2
fi
desktop="${1:?gnome or kde}"; out="$(realpath -m "${2:?OUT}")"
export POLYGLOTIC_DESK_PICTURES="$out/desk"
mkdir -p "$POLYGLOTIC_DESK_PICTURES"
QT_QPA_PLATFORM=wayland uv run --no-sync python -m tools.linux_desktop_pictures fullscreen \
  > "$out/fullscreen.log" 2>&1 & beneath=$!
uv run --no-sync python -m tools.linux_desktop_pictures serve "$POLYGLOTIC_DESK_PICTURES" "$desktop" \
  > "$out/pictures.log" 2>&1 & taker=$!
sleep 4
QT_QPA_PLATFORM=xcb uv run --no-sync python -m tools.app_tour "$out/tour" --limit 300 \
  --real-capture --mic-sink "$POLYGLOTIC_MIC_SINK"
code=$?
touch "$POLYGLOTIC_DESK_PICTURES/stop"
sleep 1
kill "$beneath" "$taker" 2>/dev/null
exit "$code"
