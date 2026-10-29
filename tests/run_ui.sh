#!/bin/sh
# Run a UI test script inside Folio Show on an X display (Xvfb): run_ui.sh script.py [file]
HERE="$(cd "$(dirname "$0")" && pwd)"
export FOLIO_TEST_SCRIPT="$HERE/$1" FOLIO_DELIVER_SHARE="${FOLIO_DELIVER_SHARE:-$HERE/../share}"
export XDG_CONFIG_HOME="$(mktemp -d)" FOLIO_TEST_DELAY=1500 UI_OUT="${UI_OUT:-/tmp/ui_out}"
cd "$HERE/../app"
if [ -n "$2" ]; then exec timeout ${UI_TIMEOUT:-180} python3 -m folio_deliver "$2"; fi
exec timeout ${UI_TIMEOUT:-180} python3 -m folio_deliver
