#!/usr/bin/env bash
# 547: builds the toy twice (1.0.0 and 1.0.1) with PyInstaller (one folder)
# inside an ubuntu:22.04 container (glibc 2.35), on uv's managed Python 3.12.
# libxcb-cursor0 is installed here, so PyInstaller can collect it.
#   docker run --rm -e GITHUB_ACTIONS -v "$PWD:/w" -w /w ubuntu:22.04 bash updates/build_in_2204.sh
set -euo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo "runs only on GitHub's runners"; exit 2; }
export DEBIAN_FRONTEND=noninteractive
log=/w/out/build.log
mkdir -p /w/out /w/build
exec > >(tee -a "$log") 2>&1
echo "== the build image"
grep -E '^(PRETTY_NAME|VERSION_ID)=' /etc/os-release
ldd --version | sed -n 1p
apt-get update -qq
apt-get install -y -qq --no-install-recommends ca-certificates curl binutils python3-pip \
  libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-render-util0 libxcb-shape0 libxcb-randr0 libxcb-xfixes0 libxcb-xkb1 \
  libegl1 libgl1 libfontconfig1 libdbus-1-3 libglib2.0-0 > /dev/null
dpkg -s libxcb-cursor0 | grep -E '^(Package|Version)'
pip3 install -q uv==0.13.5
uv --version
uv venv -q -p 3.12 --managed-python /venv
/venv/bin/python -c "import sys, sysconfig; print('python', sys.version.split()[0], sys.executable, 'shared:', sysconfig.get_config_var('Py_ENABLE_SHARED'))"
uv pip install -q -p /venv/bin/python pyside6-essentials==6.12.0 velopack==1.2.161 pyinstaller==6.22.3
uv pip list -p /venv/bin/python 2>/dev/null | grep -i -E 'pyside|velopack|pyinstaller|shiboken'
for v in 1.0.0 1.0.1; do
  echo "== build $v"
  src=/tmp/src-$v
  mkdir -p "$src"
  cp /w/updates/toy.py "$src/toy.py"
  printf 'VERSION = "%s"\n' "$v" > "$src/toy_version.py"
  /venv/bin/pyinstaller --noconfirm --log-level WARN --onedir --name toy547 \
    --distpath "/w/build/$v" --workpath "/tmp/pyi-$v" --specpath "/tmp/pyi-$v" \
    --paths "$src" "$src/toy.py"
  du -sh "/w/build/$v/toy547"
done
b=/w/build/1.0.0/toy547
echo "== libxcb-cursor in the bundle (collected by PyInstaller?)"
find "$b" -name 'libxcb-cursor*' -printf '%P %s bytes\n' || true
echo "== system libraries PyInstaller collected (outside PySide6 and Python)"
find "$b/_internal" -maxdepth 1 -name '*.so*' -printf '%f\n' | sort
echo "== the xcb platform plugin's own needs"
plugin="$(find "$b" -name libqxcb.so | head -1)"
echo "plugin: ${plugin#$b/}"
ldd "$plugin" | grep -E 'xcb-cursor|not found' || true
chmod -R a+rwX /w/build /w/out
