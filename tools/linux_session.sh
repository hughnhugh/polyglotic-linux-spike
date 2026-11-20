#!/usr/bin/env bash
# A Linux desktop session, as the Linux checks need one (polyglotic-hq 550):
# on GitHub's Ubuntu runner, inside `dbus-run-session`, start
# - the sound server: PipeWire, WirePlumber and pipewire-pulse (no systemd
#   user session there), with an output "Speakers" made the default and a
#   microphone "Microphone" made the default input - a real input, fed by
#   whatever is played into the sink named in $POLYGLOTIC_MIC_SINK
#   (547's arrangement: a null sink and a source remapped from its monitor);
# - the keyring: gnome-keyring's Secret Service, unlocked with a password
#   made for the run and never kept;
# - a screen: Xvfb at 1920x1080, as $DISPLAY, unless one is set already;
# then run COMMAND in it, and stop them all. What each said is in OUT.
#
#   dbus-run-session -- bash tools/linux_session.sh OUT -- COMMAND...
#
# GitHub's runners only: it starts daemons and loads sound modules that a
# person's own session has already.
set -uo pipefail
if [ "${GITHUB_ACTIONS:-}" != true ] || [ "$(uname -s)" != Linux ]; then
  echo "550: this runs only on GitHub's Linux runners"; exit 2
fi
out="$(realpath -m "${1:?OUT}")"; shift
[ "${1:-}" = -- ] && shift
mkdir -p "$out"
XDG_RUNTIME_DIR="$(mktemp -d)"; export XDG_RUNTIME_DIR; chmod 700 "$XDG_RUNTIME_DIR"
started=()

pipewire > "$out/pipewire.log" 2>&1 & started+=($!)
sleep 1
wireplumber > "$out/wireplumber.log" 2>&1 & started+=($!)
pipewire-pulse > "$out/pipewire-pulse.log" 2>&1 & started+=($!)
for _ in $(seq 50); do [ -S "$XDG_RUNTIME_DIR/pulse/native" ] && break; sleep 0.2; done
sleep 2  # WirePlumber settles
pactl load-module module-null-sink sink_name=session_speakers \
  sink_properties=device.description=Speakers > /dev/null
pactl set-default-sink session_speakers
POLYGLOTIC_MIC_SINK=session_mic_feed; export POLYGLOTIC_MIC_SINK
pactl load-module module-null-sink sink_name="$POLYGLOTIC_MIC_SINK" \
  sink_properties=device.description=MicFeed > /dev/null
pactl load-module module-remap-source master="$POLYGLOTIC_MIC_SINK.monitor" \
  source_name=session_mic source_properties=device.description=Microphone > /dev/null
pactl set-default-source session_mic
{
  echo "== the sound server"; pactl info
  echo "== outputs"; pactl list short sinks
  echo "== inputs"; pactl list short sources
} > "$out/sound.txt" 2>&1

password="$(head -c 18 /dev/urandom | base64)"
eval "$(printf '%s' "$password" | gnome-keyring-daemon --unlock --components=secrets)"
unset password
export GNOME_KEYRING_CONTROL

if [ -z "${DISPLAY:-}" ]; then
  Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp > "$out/xvfb.log" 2>&1 & started+=($!)
  export DISPLAY=:99
  for _ in $(seq 50); do [ -S /tmp/.X11-unix/X99 ] && break; sleep 0.1; done
fi

"$@"; code=$?

# the keyring ends with the session's bus (dbus-run-session's)
for pid in "${started[@]}"; do kill "$pid" 2>/dev/null; done
exit "$code"
