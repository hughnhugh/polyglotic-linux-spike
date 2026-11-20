#!/usr/bin/env bash
# 547: packs the two toy builds with vpk 1.2.161 (exact) into one output
# folder, as a release would: 1.0.0 first, then 1.0.1 (with its delta).
# Keeps 1.0.0's AppImage aside (the second pack writes the same name).
set -euo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo "runs only on GitHub's runners"; exit 2; }
log=out/pack.log
exec > >(tee -a "$log") 2>&1
dotnet --version
dotnet tool install -g vpk --version 1.2.161 > /dev/null
export PATH="$PATH:$HOME/.dotnet/tools"
vpk --version 2>/dev/null | head -2 || true
echo "== mksquashfs on the host? $(command -v mksquashfs || echo no)"
mkdir -p releases installers
for v in 1.0.0 1.0.1; do
  echo "== vpk pack $v"
  vpk pack --packId Toy547 --packVersion "$v" --packTitle Toy547 --packAuthors Toy547 \
    --packDir "build/$v/toy547" --mainExe toy547 --runtime linux-x64 \
    --channel linux-x64-alpha --outputDir releases
  for f in releases/*.AppImage; do cp "$f" "installers/$(basename "$f" .AppImage)-$v.AppImage"; done
done
echo "== the output folder"
ls -la releases installers
echo "== releases.linux-x64-alpha.json"
head -c 1500 releases/releases.linux-x64-alpha.json; echo
echo "== the AppImage's runtime (static? needs libfuse2?)"
a="$(ls installers/*-1.0.0.AppImage | head -1)"
file "$a" || true
offset="$("$a" --appimage-offset 2>/dev/null || true)"
echo "runtime size (squashfs offset): ${offset:-?}"
if [ -n "$offset" ]; then
  head -c "$offset" "$a" > /tmp/runtime547
  file /tmp/runtime547 || true
  ldd /tmp/runtime547 2>&1 | head -5 || true
  strings /tmp/runtime547 | grep -i -E 'libfuse|fusermount' | sort -u | head -10 || true
fi
