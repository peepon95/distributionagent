#!/bin/bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

notify() {
  if command -v osascript >/dev/null 2>&1; then
    osascript -e "display notification \"$1\" with title \"$2\""
  fi
}

notify "Starting weekly full scan: Superwall, Starter Story, and other sources..." "DistributionGPT Weekly Update"

LOGFILE="$PROJECT_ROOT/weekly_update.log"
echo "=== Weekly update $(date) ===" >> "$LOGFILE"
make update ARGS="${UPDATE_ARGS:-}" >> "$LOGFILE" 2>&1
STATUS=$?

if [ $STATUS -eq 0 ]; then
  notify "New and previously missed episodes ingested, enriched, and indexed." "DistributionGPT Weekly Update"
else
  notify "Weekly update failed - check weekly_update.log" "DistributionGPT Weekly Update"
fi

exit $STATUS
