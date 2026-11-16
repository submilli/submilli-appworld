#!/bin/sh
# Prepares a checkout: AppWorld at the pinned commit (with its Git LFS bundles, fetched without
# git-lfs), the Python environment, AppWorld's data, the Submilli CLI and server, and the Packages
# (unpacked from the encrypted generator/derived.bundle).
#
#   scripts/setup.sh
set -eu

appworld_commit=42b5bcf3cd334fee33f0c37c02070a9f5807add5
submilli_version=v0.6.1
root=$(cd "$(dirname "$0")/.." && pwd)
tools=$root/.tools
cd "$root"

if [ ! -d "$tools/appworld/.git" ]; then
    git clone -q https://github.com/StonyBrookNLP/appworld "$tools/appworld"
fi
git -C "$tools/appworld" checkout -q "$appworld_commit"

# The bundles are Git LFS objects. Replace each pointer with its object, checked against the
# pointer's sha256.
media=https://media.githubusercontent.com/media/StonyBrookNLP/appworld/$appworld_commit
for bundle in src/appworld/.source/apps.bundle src/appworld/.source/tests.bundle \
    generate/.source/data.bundle generate/.source/tasks.bundle; do
    file=$tools/appworld/$bundle
    if grep -q "git-lfs.github.com/spec" "$file" 2>/dev/null; then
        oid=$(sed -n 's/^oid sha256://p' "$file")
        curl -fsSL -o "$file.tmp" "$media/$bundle"
        [ "$(shasum -a 256 "$file.tmp" | cut -d' ' -f1)" = "$oid" ] || { echo "sha256 mismatch: $bundle" >&2; exit 1; }
        mv "$file.tmp" "$file"
    fi
done

uv sync -q
(cd "$tools/appworld" && "$root/.venv/bin/appworld" install --repo >/dev/null)
[ -d "$root/data/tasks" ] || "$root/.venv/bin/appworld" download data --root "$root" >/dev/null

if [ "$("$tools/bin/submilli" --version 2>/dev/null)" != "submilli ${submilli_version#v}" ]; then
    curl -fsSL https://submilli.ai/install.sh | sh -s -- --version "$submilli_version" --install-dir "$tools/bin"
fi
[ -f "$root/packages/supervisor/src/lib.ts" ] || "$root/.venv/bin/python" "$root/scripts/bundle.py" unpack
echo "Ready: AppWorld $("$root/.venv/bin/appworld" --version), $("$tools/bin/submilli" --version)."
