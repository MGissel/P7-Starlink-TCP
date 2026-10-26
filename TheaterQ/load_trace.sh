#!/bin/bash
# load_trace.sh — Clear existing TheaterQ trace entries and ingest a new CSV.
# Usage: ./load_trace.sh <path-to-trace.csv> [interface] [handle] [format:SIMPLE|EXTENDED]

set -euo pipefail

TRACE_FILE="${1:?Usage: $0 <path-to-trace.csv> [interface] [handle] [format:SIMPLE|EXTENDED]}"
IFACE="${2:-lo}"
HANDLE="${3:-1:}"
FORMAT="${4:-EXTENDED}"
DEV_PATH="/dev/theaterq:${IFACE}:${HANDLE%:}:0"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TC_LIB_DIR="${TC_LIB_DIR:-${SCRIPT_DIR}/theaterq_tc/tclib}"

if [[ ! -f "$TRACE_FILE" ]]; then
    echo "Error: trace file not found: $TRACE_FILE" >&2
    exit 1
fi

echo ">> Clearing existing trace on dev $IFACE handle $HANDLE (format $FORMAT)"
sudo env TC_LIB_DIR="$TC_LIB_DIR" tc qdisc replace dev "$IFACE" root handle "$HANDLE" theaterq stage CLEAR ingest "$FORMAT"

echo ">> Ingesting $TRACE_FILE into $DEV_PATH"
sudo bash -c "cat '$TRACE_FILE' > '$DEV_PATH'"

echo ">> Current qdisc state:"
env TC_LIB_DIR="$TC_LIB_DIR" tc qdisc show dev "$IFACE"

sudo env TC_LIB_DIR="$TC_LIB_DIR" tc qdisc change dev "$IFACE" root handle "$HANDLE" theaterq stage RUN cont LOOP

echo ">> Playback started (stage RUN, cont LOOP):"
env TC_LIB_DIR="$TC_LIB_DIR" tc qdisc show dev "$IFACE"
