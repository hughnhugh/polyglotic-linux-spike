#!/usr/bin/env bash
# 547: can the build image (bare ubuntu:22.04, no squashfs-tools) run vpk
# 1.2.161 itself, so the whole build runs in one container?
#   docker run --rm -e GITHUB_ACTIONS -v "$PWD:/w" -w /w ubuntu:22.04 bash updates/vpk_in_2204.sh
set -uo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo "runs only on GitHub's runners"; exit 2; }
export DEBIAN_FRONTEND=noninteractive DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
log=/w/out/vpk_2204.log
exec > >(tee -a "$log") 2>&1
apt-get update -qq
apt-get install -y -qq --no-install-recommends ca-certificates curl libicu70 > /dev/null
echo "mksquashfs here? $(command -v mksquashfs || echo no)"
curl -fsSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh
bash /tmp/dotnet-install.sh --channel 10.0 --install-dir /opt/dotnet > /dev/null
export PATH="/opt/dotnet:$PATH"
echo "dotnet $(dotnet --version)"
dotnet tool install --tool-path /opt/tools vpk --version 1.2.161 > /dev/null
/opt/tools/vpk pack --packId Toy547 --packVersion 1.0.0 --packTitle Toy547 --packAuthors Toy547 \
  --packDir /w/build/1.0.0/toy547 --mainExe toy547 --runtime linux-x64 \
  --channel linux-x64-alpha --outputDir /tmp/out 2>&1 | grep -E 'INF|WRN|ERR|rror' | cut -c1-200
echo "vpk exit ${PIPESTATUS[0]}"
ls -la /tmp/out
