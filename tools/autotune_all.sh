#!/bin/bash
# Elects the best Faust options for every kernel with fcautotool (faust of the certification-4 branch).
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
export FAUST="$HERE/tools/faust-cert4.sh" FCBENCH_ARCH_FLAGS="-mcpu=native"
mkdir -p "$HERE/results/autotool"
if [ -z "${KERNELS:-}" ]; then
  for source in "$HERE"/dsp/*.dsp; do
    name=${source##*/}
    KERNELS="${KERNELS:-} ${name%.dsp}"
  done
fi
for n in $KERNELS; do
  fcautotool "$HERE/dsp/$n.dsp" > "$HERE/results/autotool/$n.txt" 2>&1
  echo "$n: $(grep -m1 -iE 'elected|winner|verdict' "$HERE/results/autotool/$n.txt")"
done
