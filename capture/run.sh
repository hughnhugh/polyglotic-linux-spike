#!/usr/bin/env bash
# 547 capture: start PipeWire, WirePlumber and pipewire-pulse by hand (no
# systemd user session on the runner), in a runtime folder of our own, then
# run the libpulse probe. Run inside dbus-run-session.
#   dbus-run-session -- bash capture/run.sh OUT_DIR
set -uo pipefail
if [ "${GITHUB_ACTIONS:-}" != true ] || [ "$(uname -s)" != Linux ]; then
  echo "547: this runs only on GitHub's Ubuntu runners"; exit 2
fi
out="$(realpath -m "${1:-out}")"; mkdir -p "$out"
here="$(cd "$(dirname "$0")" && pwd)"
XDG_RUNTIME_DIR="$(mktemp -d)"; export XDG_RUNTIME_DIR; chmod 700 "$XDG_RUNTIME_DIR"
{
  echo "== pipewire --version"; pipewire --version
  echo "== wireplumber --version"; wireplumber --version
  echo "== packages"
  dpkg-query -W -f='${Package} ${Version}\n' pipewire pipewire-bin pipewire-pulse wireplumber \
    libpulse0 'libpipewire-0.3-0*' 'libwireplumber-0.4-0*' pulseaudio pulseaudio-utils 2>/dev/null
  echo "== os"; . /etc/os-release; echo "$PRETTY_NAME"; uname -r
} > "$out/versions.txt" 2>&1
cat "$out/versions.txt"
pipewire > "$out/pipewire.log" 2>&1 & pw=$!
sleep 1
wireplumber > "$out/wireplumber.log" 2>&1 & wp=$!
pipewire-pulse > "$out/pipewire-pulse.log" 2>&1 & pp=$!
for _ in $(seq 50); do [ -S "$XDG_RUNTIME_DIR/pulse/native" ] && break; sleep 0.2; done
sleep 2  # WirePlumber settles
ls -la "$XDG_RUNTIME_DIR" "$XDG_RUNTIME_DIR/pulse" || true
rc=0
python3 -I "$here/probe.py" "$out" || rc=$?
# a cross-check from the stock tool (setup only, not the probe's route)
pactl info > "$out/pactl-info.txt" 2>&1 || true
pw-dump > "$out/pw-dump-end.json" 2>/dev/null || true
kill "$pp" "$wp" "$pw" 2>/dev/null || true
echo "probe exit $rc"
exit "$rc"
