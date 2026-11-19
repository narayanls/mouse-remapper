#!/usr/bin/env bash
# Regenerates the translation template (mouse-remapper.pot) from the source code
# and merges new strings into every existing translation (po/*.po).
#
# Requires gettext (xgettext, msgmerge).
set -euo pipefail
cd "$(dirname "$0")/.."

mapfile -t sources < <(find usr/share/mouse-remapper -name '*.py' -not -path '*/__pycache__/*' | sort)

xgettext \
    --language=Python \
    --from-code=UTF-8 \
    --keyword=_ \
    --keyword=ngettext:1,2 \
    --add-comments=TRANSLATORS: \
    --package-name=mouse-remapper \
    --msgid-bugs-address=https://github.com/narayanls/mouse-remapper/issues \
    --output=po/mouse-remapper.pot \
    "${sources[@]}"

for po in po/*.po; do
    [ -e "$po" ] || continue
    msgmerge --quiet --update --backup=none "$po" po/mouse-remapper.pot
    echo "Updated $po"
done
