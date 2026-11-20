#!/usr/bin/env bash
# 547: on the ubuntu-24.04 runner, with libfuse2 removed: install 1.0.0's
# AppImage (copy, chmod +x, run), then update it in place from a local feed
# (the releases folder) and check that 1.0.1 restarted itself from the same
# path. Under Xvfb, Qt on xcb.
set -uo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo "runs only on GitHub's runners"; exit 2; }
log=out/round_trip.log
exec > >(tee -a "$log") 2>&1
fail=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; fail=1; fi; }

echo "== FUSE on the runner, before"
dpkg -l | grep -i fuse || true
for p in libfuse2t64 libfuse2; do
  if dpkg -s "$p" > /dev/null 2>&1; then
    echo "removing $p"; sudo apt-get remove -y -qq "$p" > /dev/null 2>&1 || true
  fi
done
echo "== FUSE on the runner, after"
dpkg -l | grep -i fuse || true
ldconfig -p | grep -i libfuse || echo "(no libfuse in ldconfig)"
ls -l /dev/fuse 2>&1; command -v fusermount fusermount3 || true
check "libfuse2 absent" "! ldconfig -p | grep -q 'libfuse.so.2'"

echo "== Qt's xcb needs on the host (as a desktop has them)"
sudo apt-get install -y -qq xvfb libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-render-util0 libxcb-shape0 libxcb-randr0 libxcb-xfixes0 libxcb-xkb1 libegl1 libgl1 \
  libfontconfig1 libdbus-1-3 > /dev/null 2>&1
dpkg -s libxcb-cursor0 > /dev/null 2>&1 && echo "host has libxcb-cursor0" || echo "host lacks libxcb-cursor0"
Xvfb :99 -screen 0 1280x720x24 > /dev/null 2>&1 &
xvfb=$!
export DISPLAY=:99 QT_QPA_PLATFORM=xcb
sleep 2

export TOY547_MARKER="$HOME/toy547/marker.jsonl"
rm -f "$TOY547_MARKER"
stamp="$(mktemp)"
app="$HOME/Applications/Toy547.AppImage"
mkdir -p "$HOME/Applications"
src="$(ls installers/*-1.0.0.AppImage | head -1)"
cp "$src" "$app"
chmod +x "$app"
echo "== install: $app"
before="$(sha256sum "$app" | cut -c1-16) inode $(stat -c %i "$app") $(stat -c '%s bytes %A' "$app")"
echo "before: $before"

echo "== run 1.0.0"
timeout 60 "$app"; echo "exit $?"
check "1.0.0 ran from the AppImage" "grep -q '\"version\": \"1.0.0\", \"event\": \"window\"' '$TOY547_MARKER'"

echo "== the feed"
mkdir -p feed && cp releases/* feed/ && ls -la feed

echo "== update 1.0.0 -> 1.0.1 in place"
timeout 120 "$app" --update "$PWD/feed"; echo "exit $?"
for _ in $(seq 1 90); do
  grep -q '"version": "1.0.1", "event": "window"' "$TOY547_MARKER" && break
  sleep 1
done
sleep 3
echo "== processes left"
ps -eo pid,ppid,args | grep -i -E 'toy547|Update|AppImage' | grep -v grep || echo "(none)"
echo "== the marker"
cat "$TOY547_MARKER"
check "1.0.1 restarted by itself" "grep -q '\"version\": \"1.0.1\", \"event\": \"start\"' '$TOY547_MARKER'"
after="$(sha256sum "$app" | cut -c1-16) inode $(stat -c %i "$app") $(stat -c '%s bytes %A' "$app")"
echo "after: $after"
check "the same path, new contents" "[ -x '$app' ] && [ '${before%% *}' != '${after%% *}' ]"
ls -la "$HOME/Applications"

echo "== run again (as a learner would)"
n="$(grep -c '"version": "1.0.1", "event": "window"' "$TOY547_MARKER")"
timeout 60 "$app"; echo "exit $?"
check "1.0.1 starts from the same path" "[ \$(grep -c '\"version\": \"1.0.1\", \"event\": \"window\"' '$TOY547_MARKER') -gt $n ]"

echo "== what Velopack wrote and logged"
find "$HOME" /tmp /var/tmp -xdev -newer "$stamp" -type f 2>/dev/null \
  | grep -v -E '/(\.dotnet|\.nuget|work|runners?|\.cache/pip)/|/proc/' | grep -v -E '\.pyc$' | head -40
for f in $(find "$HOME" /tmp /var/tmp -xdev -newer "$stamp" -type f -iname '*velopack*' 2>/dev/null | head -5); do
  echo "--- $f"; tail -n 80 "$f"
done
cp "$TOY547_MARKER" out/marker.jsonl
kill "$xvfb" 2>/dev/null || true
exit $fail
