#!/usr/bin/env python3
"""Summarize Linux runs using finite output and a per-channel error gate."""

import argparse
import csv
from collections import defaultdict
from math import isfinite
from pathlib import Path
from statistics import geometric_mean


UPSTREAM_VARIANTS = {"fir32", "frenchbell_x", "hoa_decoder", "mixer16"}
STOCK_STRICT = {"cpp-scal", "cpp-vec"}
STOCK_FAST = {"cpp-scal-fm", "cpp-vec-fm", "cpp-vec-libmvec", "llvm-scal", "llvm-vec"}
FIXED_STRICT = {"cpp48-scal", "cpp48-vec", "ocpp48"}
FIXED_FAST = {"cpp48-scal-fm", "cpp48-vec-fm", "ocpp48-fm", "m5-pick48-fm", "llvm48", "llvm48-vec"}
ALL_STRICT = STOCK_STRICT | FIXED_STRICT | {"ocpp"}
ALL_FAST = STOCK_FAST | FIXED_FAST | {"ocpp-fm", "m5-pick-fm"}
ALL_STOCK_STRICT = STOCK_STRICT | {"cpp48-scal", "cpp48-vec"}
ALL_STOCK_FAST = STOCK_FAST | {"cpp48-scal-fm", "cpp48-vec-fm", "llvm48", "llvm48-vec"}


def load_results(path, max_error=1e-3):
    accepted = defaultdict(dict)
    rejected = []
    workload_names = set()
    with path.open() as data:
        for row in csv.DictReader(data, delimiter="\t"):
            name, engine = row["workload"], row["engine"]
            workload_names.add(name)
            time = float(row["ns_per_frame"])
            error = float(row["worst_channel_rel_rms"])
            if row["finite"] == "1" and 0 <= error <= max_error and isfinite(time) and time > 0:
                accepted[name][engine] = time
            else:
                rejected.append(f"{name}/{engine}")
    return accepted, workload_names, rejected


def summarize(path, max_error, tuned_onda, upstream_corpus):
    accepted, workload_names, rejected = load_results(path, max_error)
    print(f"\n{path} · {len(rejected)} rejected rows")
    if rejected:
        print(", ".join(rejected))
    if upstream_corpus:
        workload_names -= UPSTREAM_VARIANTS
    if tuned_onda:
        print("Onda source variants are eligible.")
    print("| Faust candidates | Workloads strict / fast | Strict speedup | Fast speedup |")
    print("| --- | ---: | ---: | ---: |")
    for label, strict, fast in (
        ("Stock 2.95.1, runtime rate", STOCK_STRICT, STOCK_FAST),
        ("Compile-time 48 kHz", FIXED_STRICT, FIXED_FAST),
        ("All configurations", ALL_STRICT, ALL_FAST),
    ):
        ratios = []
        for is_fast, faust in ((False, strict), (True, fast)):
            group = []
            for name in sorted(workload_names):
                rows = accepted[name]
                faust_candidates = [rows[key] for key in faust if key in rows]
                baseline = "onda-fm" if is_fast else "onda"
                onda_candidates = [time for key, time in rows.items()
                                   if key == baseline or (tuned_onda and key.startswith("onda-")
                                                          and key.endswith("-fm") == is_fast)]
                if onda_candidates and faust_candidates:
                    group.append(min(faust_candidates) / min(onda_candidates))
            ratios.append(group)
        strict_ratios, fast_ratios = ratios
        strict_mean, fast_mean = (f"×{geometric_mean(group):.3f}" if group else "—" for group in ratios)
        print(f"| {label} | {len(strict_ratios)} / {len(fast_ratios)} | {strict_mean} | {fast_mean} |")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-error", type=float, default=1e-3)
    parser.add_argument("--tuned-onda", action="store_true", help="include same-round Onda source variants")
    parser.add_argument("--upstream-corpus", action="store_true", help="exclude auxiliary workloads from the original corpus")
    parser.add_argument("results", type=Path, nargs="+")
    args = parser.parse_args()
    for path in args.results:
        summarize(path, args.max_error, args.tuned_onda, args.upstream_corpus)


if __name__ == "__main__":
    main()
