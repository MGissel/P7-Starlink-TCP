#!/bin/bash
# load_trace.sh — Clear existing TheaterQ trace entries and ingest a new CSV.
# Usage: ./load_trace.sh <path-to-trace.csv> [interface] [handle]

set -euo pipefail

TRACE_FILE="${1:?Usage: $0 <path-to-trace.csv> [interface] [handle]}"
IFACE="${2:-lo}"
HANDLE="${3:-1:}"
DEV_PATH="/dev/theaterq:${IFACE}:${HANDLE%:}:0"

if [[ ! -f "$TRACE_FILE" ]]; then
    echo "Error: trace file not found: $TRACE_FILE" >&2
    exit 1
fi

echo ">> Clearing existing trace on dev $IFACE handle $HANDLE"
sudo tc qdisc change dev "$IFACE" root handle "$HANDLE" theaterq stage CLEAR

echo ">> Ingesting $TRACE_FILE into $DEV_PATH"
sudo bash -c "cat '$TRACE_FILE' > '$DEV_PATH'"

echo ">> Current qdisc state:"
tc qdisc show dev "$IFACE"

sudo tc qdisc change dev lo root handle 1: theaterq stage RUN cont LOOP

echo ""
echo "Trace loaded. To start playback, run:"
echo "  sudo tc qdisc change dev $IFACE root handle $HANDLE theaterq stage RUN cont LOOP"