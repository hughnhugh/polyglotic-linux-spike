#!/usr/bin/env bash
# 570: inside a session from tools/linux_session.sh - the window beneath,
# then the probe. OUT gets probe.json and the logs.
set -uo pipefail
out="$(realpath -m "${1:?OUT}")"; mkdir -p "$out"
export POLYGLOTIC_BENEATH_LOG="$out/beneath.log"
if [ "${LINUX_SESSION_SCREEN:-xvfb}" = xvfb ]; then plat=xcb; else plat=wayland; fi
QT_QPA_PLATFORM=$plat uv run --no-sync python probe570/beneath.py > "$out/beneath.out" 2>&1 & beneath=$!
sleep 4
QT_QPA_PLATFORM=xcb timeout 300 uv run --no-sync python probe570/probe.py "$out/probe.json" > "$out/probe.out" 2>&1
code=$?
kill "$beneath" 2>/dev/null
cat "$out/probe.json" 2>/dev/null || tail -40 "$out/probe.out"
exit $code
# run 2
