#!/bin/sh
# Prints one sha256 per generated Package file, so a build can be checked against
# generator/packages.sha256 without committing the Packages.
set -eu
cd "$(dirname "$0")/.."
find packages -type f \( -name '*.ts' -o -name '*.md' \) ! -name README_BEFORE_SHARING.md | LC_ALL=C sort | xargs shasum -a 256
