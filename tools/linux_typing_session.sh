#!/usr/bin/env bash
# Chinese and Japanese typed into the app on Linux (polyglotic-hq 571): on
# GitHub's Ubuntu runner, in a clean `ubuntu:24.04` container (the repo
# mounted; Ubuntu's own input methods; the app's from uv.lock), each in a
# `dbus-run-session` of its own with an X screen (Xvfb) and one input method
# framework - IBus (`ibus-daemon`, no panel) or Fcitx5 (`fcitx5`, its IBus
# frontend on, pinyin in its profile) - then tools/linux_typing_check.py in
# it. What each said is in OUT.
#
#   bash tools/linux_typing_session.sh OUT
#
# GitHub's runners only: it installs packages, starts daemons a person's own
# session has already, and writes Fcitx5's profile in this HOME.
set -uo pipefail
if [ "${GITHUB_ACTIONS:-}" != true ] || [ "$(uname -s)" != Linux ]; then
  echo "571: this runs only on GitHub's Linux runners"; exit 2
fi
out="$(realpath -m "${1:?OUT}")"
if [ -z "${IN_UBUNTU_571:-}" ]; then
  mkdir -p "$out"
  root="$(cd "$(dirname "$0")/.." && pwd)"
  exec docker run --rm -e GITHUB_ACTIONS=true -e IN_UBUNTU_571=1 -e UV_PYTHON -e UV_PYTHON_PREFERENCE \
    -v "$root:/w" -v "$out:/out" -v "$(command -v uv):/usr/local/bin/uv:ro" \
    -w /w ubuntu:24.04 bash /w/tools/linux_typing_session.sh /out
fi

if [ -z "${IN_SESSION_571:-}" ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq > /dev/null
  apt-get install -y -qq --no-install-recommends \
    ca-certificates xvfb xdotool dbus dbus-bin dbus-daemon \
    ibus ibus-libpinyin ibus-mozc mozc-server \
    fcitx5 fcitx5-chinese-addons fcitx5-modules \
    libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 \
    libegl1 libgl1 libfontconfig1 libdbus-1-3 libglib2.0-0t64 fonts-noto-core fonts-noto-cjk \
    > "$out/apt.log" 2>&1 || { tail -20 "$out/apt.log"; exit 1; }
  # Anthy, where the archive has it (24.04's doesn't): Mozc is Ubuntu's own
  apt-get install -y -qq --no-install-recommends ibus-anthy >> "$out/apt.log" 2>&1 || true
  dbus-uuidgen --ensure=/etc/machine-id
  dpkg-query -W -f='${Package} ${Version}\n' ibus ibus-libpinyin ibus-anthy ibus-mozc \
    fcitx5 fcitx5-chinese-addons xdotool | tee "$out/versions.txt"
  export UV_PROJECT_ENVIRONMENT=/tmp/venv
  uv sync --locked > "$out/uv-sync.log" 2>&1 || { tail -20 "$out/uv-sync.log"; exit 1; }
  code=0
  for im in ibus fcitx5; do
    IN_SESSION_571="$im" dbus-run-session -- bash /w/tools/linux_typing_session.sh "$out/$im-session" \
      || code=1
  done
  exit "$code"
fi

im="$IN_SESSION_571"
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
  sleep 2
  { echo "== $(ibus version 2>&1)"; ibus list-engine 2>&1 | grep -E -i "pinyin|anthy|mozc"; } \
    > "$out/engines.txt" 2>&1
  QT_IM_MODULE=ibus uv run --no-sync python -m tools.linux_typing_check "$out/ibus" ibus || code=1
  # what a session that names no input method gets (Qt's own compose):
  # a finding, not this run's failure
  env -u QT_IM_MODULE -u QT_IM_MODULES uv run --no-sync python -m tools.linux_typing_check \
    "$out/ibus-unnamed" ibus-unnamed || true
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
  sleep 6
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
  # and with IBus's plugin named after Fcitx's, Qt trying each in turn
  QT_IM_MODULE=fcitx QT_IM_MODULES="fcitx;ibus" uv run --no-sync python -m tools.linux_typing_check     "$out/fcitx5-fallback" fcitx5-fallback || true
  ;;
*) echo "ibus or fcitx5"; code=2 ;;
esac

for pid in "${started[@]}"; do kill "$pid" 2>/dev/null; done
exit "$code"
