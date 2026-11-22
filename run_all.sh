#!/bin/bash
# Builds and runs every program in two passes, then regenerates the report.
#   pass 1: default clang contract (build/macos/results.tsv)
#   pass 2: C++ strict variants at -ffp-contract=off (build/macos/results_nocontract.tsv, the "IEEE" columns)
#   ROUNDS=21 KERNELS="sine zita_rev" ./run_all.sh
# The fcautotool election (results/autotool/) is redone separately by tools/autotune_all.sh.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
if [ -z "${KERNELS:-}" ]; then
  for source in dsp/*.onda; do
    name=${source##*/}
    KERNELS="${KERNELS:-} ${name%.onda}"
  done
fi
ROUNDS=${ROUNDS:-21}
OUT="$HERE/build/macos"
mkdir -p "$OUT"
run_pass() {  # $1 = output file, $2 = extra flags for the strict C++ variants
  : > "$1"
  for n in $KERNELS; do
    STRICT_EXTRA="$2" ./build.sh "$n" 2>&1 | grep -E "error" || true
    (cd "build/$n" && ./bench "$HERE/dsp/$n.dsp" "$n" "$ROUNDS" 2>/dev/null) | tee -a "$1"
  done
}
run_pass "$OUT/results.tsv" ""
run_pass "$OUT/results_nocontract.tsv" "-ffp-contract=off"
python3 report/gen.py "$HERE" "$OUT"
python3 report/readme_chart.py "$OUT" --apple-results "$OUT/results.json"
echo "report: $OUT/onda-vs-faust.html"
