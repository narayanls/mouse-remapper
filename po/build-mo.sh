#!/usr/bin/env bash
# Compiles po/*.po into usr/share/locale/<lang>/LC_MESSAGES/mouse-remapper.mo,
# so translations also work when running the app straight from the repository.
#
# Requires gettext (msgfmt).
set -euo pipefail
cd "$(dirname "$0")/.."

for po in po/*.po; do
    lang="$(basename "$po" .po)"
    out="usr/share/locale/$lang/LC_MESSAGES"
    mkdir -p "$out"
    msgfmt --check --output-file="$out/mouse-remapper.mo" "$po"
    echo "Built $out/mouse-remapper.mo"
done
