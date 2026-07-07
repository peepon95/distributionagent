#!/bin/bash
# Patiently wait out YouTube's IP block on transcript fetches, then ingest
# everything. Probe-first: one cheap transcript request per round; if still
# blocked, sleep 2h WITHOUT hammering the channels (repeated attempts appear
# to refresh the block). Once the probe succeeds, run the full ingest, then
# enrich + index the new episodes.
cd "$(dirname "$0")/.."
PYTHON=.venv/bin/python
export YT_TRANSCRIPT_DELAY="${YT_TRANSCRIPT_DELAY:-15}"
PROBE_VIDEO="DiRxTfnHTaY"  # known-good starterstory video with a transcript

for round in $(seq 1 12); do
  echo "=== YT PROBE $round $(date +%H:%M) ===" | tee -a ingest_all.log
  if $PYTHON -c "
from pipeline.ingest_youtube import fetch_transcript, TransientlyBlocked
import sys
try:
    fetch_transcript('$PROBE_VIDEO')
except TransientlyBlocked:
    sys.exit(1)
"; then
    echo "Probe OK — block lifted, ingesting all channels" | tee -a ingest_all.log
    $PYTHON -m pipeline.ingest_youtube @starterstory 2>&1 | tee -a ingest_all.log | tail -1
    $PYTHON -m pipeline.ingest_youtube @SuperwallHQ 2>&1 | tee -a ingest_all.log | tail -1
    echo "Enriching + indexing new episodes" | tee -a ingest_all.log
    $PYTHON -m pipeline.enrich 2>&1 | tail -2 | tee -a ingest_all.log
    $PYTHON -m pipeline.index 2>&1 | tail -1 | tee -a ingest_all.log
    # if the ingest itself got re-blocked partway, loop again; else done
    if tail -20 ingest_all.log | grep -q "0 blocked"; then
      echo "YouTube ingestion COMPLETE $(date +%H:%M)" | tee -a ingest_all.log
      exit 0
    fi
  else
    echo "Still blocked; sleeping 2h" | tee -a ingest_all.log
  fi
  sleep 7200
done
echo "yt_retry: gave up after 12 probes (~24h) — try from a different network" | tee -a ingest_all.log
