#!/bin/sh
# Run a UI test script inside the installed Folio Deliver: run_installed.sh /path/to/script.py
export FOLIO_TEST_SCRIPT="$1" XDG_CONFIG_HOME="$(mktemp -d)" FOLIO_TEST_DELAY=1500 UI_OUT="${UI_OUT:-/tmp/ui_out_installed}"
cd /
exec timeout ${UI_TIMEOUT:-400} /usr/bin/folio-deliver
