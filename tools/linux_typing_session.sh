#!/usr/bin/env bash
# Chinese and Japanese typed into the app on Linux (polyglotic-hq 571): on
# GitHub's Ubuntu runner, inside `dbus-run-session`, an X screen (Xvfb) and
# one input method framework - IBus (`ibus-daemon`, no panel) or Fcitx5
# (`fcitx5`, its IBus frontend on, pinyin in its profile) - then
# tools/linux_typing_check.py in it. What each said is in OUT.
#
#   dbus-run-session -- bash tools/linux_typing_session.sh ibus|fcitx5 OUT
#
# GitHub's runners only: it starts daemons a person's own session has
# already, and writes Fcitx5's profile in this HOME.
set -uo pipefail
if [ "${GITHUB_ACTIONS:-}" != true ] || [ "$(uname -s)" != Linux ]; then
  echo "571: this runs only on GitHub's Linux runners"; exit 2
fi
im="${1:?ibus or fcitx5}"; out="$(realpath -m "${2:?OUT}")"
mkdir -p "$out"
XDG_RUNTIME_DIR="$(mktemp -d)"; export XDG_RUNTIME_DIR; chmod 700 "$XDG_RUNTIME_DIR"
export GSETTINGS_BACKEND=memory
started=()
Xvfb :97 -screen 0 1600x1000x24 -nolisten tcp > "$out/xvfb.log" 2>&1 & started+=($!)
export DISPLAY=:97
for _ in $(seq 50); do [ -S /tmp/.X11-unix/X97 ] && break; sleep 0.1; done

code=0
case "$im" in
ibus)
  ibus-daemon --replace --panel=disable --xim > "$out/ibus.log" 2>&1 & started+=($!)
  for _ in $(seq 50); do ibus address > /dev/null 2>&1 && break; sleep 0.2; done
  { echo "== ibus $(ibus version 2>&1)"; ibus list-engine 2>&1 | grep -E -i "pinyin|anthy|mozc"; } \
    > "$out/engines.txt" 2>&1
  QT_IM_MODULE=ibus uv run --no-sync python -m tools.linux_typing_check "$out/ibus" ibus || code=1
  ;;
fcitx5)
  mkdir -p "$HOME/.config/fcitx5"
  cat > "$HOME/.config/fcitx5/profile" <<'PROFILE'
[Groups/0]
Name=Default
Default Layout=us
DefaultIM=pinyin

[Groups/0/Items/0]
Name=keyboard-us
Layout=

[Groups/0/Items/1]
Name=pinyin
Layout=

[GroupOrder]
0=Default
PROFILE
  fcitx5 --replace --verbose='*=3' > "$out/fcitx5.log" 2>&1 & started+=($!)
  sleep 5
  {
    echo "== fcitx5 $(fcitx5 --version 2>&1)"
    echo "== the ibus address file(s) Fcitx5 wrote:"; ls -la "$HOME/.config/ibus/bus" 2>&1
    echo "== on the bus:"; dbus-send --session --print-reply --dest=org.freedesktop.DBus \
      /org/freedesktop/DBus org.freedesktop.DBus.ListNames 2>&1 | grep -E -o '"[^"]*(IBus|Fcitx|fcitx)[^"]*"'
  } > "$out/engines.txt" 2>&1
  QT_IM_MODULE=ibus uv run --no-sync python -m tools.linux_typing_check "$out/fcitx5" fcitx5 || code=1
  # what Kubuntu's own setting gets: Qt asked for Fcitx's plugin, which the
  # app doesn't carry - a finding, not this run's failure
  QT_IM_MODULE=fcitx uv run --no-sync python -m tools.linux_typing_check \
    "$out/fcitx5-own-plugin" fcitx5-own-plugin || true
  ;;
*) echo "ibus or fcitx5"; code=2 ;;
esac

for pid in "${started[@]}"; do kill "$pid" 2>/dev/null; done
exit "$code"
