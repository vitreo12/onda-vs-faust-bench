# Linux reproduction

The runner needs Python 3, Clang C++, `llvm-objcopy`, `taskset`, Onda with its processor ABI
header, and a Faust executable, headers and LLVM-enabled shared library. The optional libmvec
build requires glibc and Clang support for `-fveclib=libmvec`. A sibling `../onda` checkout
supplies `target/release/onda` and `include/` by default. Override both paths together to test a
precompiled release. The harness links an ordinary Linux executable because some emitted Onda
objects use non-PIC relocations.

## Toolchains used in the audit

The source revisions are listed in the [audit](../../report/linux-audit.md). Fetch them into
`build/toolchains/` or supply equivalent paths in the commands below. In the Faust 2.95.1
checkout, build both the executable and the LLVM-capable shared library. The commands below use
the source directory names from the audit.

```sh
deps="$PWD/build/toolchains"
cmake -S "$deps/onda-faust-main/build" -B "$deps/onda-faust-main-cmake" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER=clang++ \
  -DINCLUDE_LLVM=ON -DLINK_LLVM_STATIC=OFF -DINCLUDE_DYNAMIC=ON \
  '-DLLVM_BACKEND=COMPILER DYNAMIC' '-DCPP_BACKEND=COMPILER DYNAMIC' \
  '-DOLDCPP_BACKEND=COMPILER DYNAMIC' -DINCLUDE_OSC=OFF -DINCLUDE_HTTP=OFF \
  -DINCLUDE_EMCC=OFF -DINCLUDE_WASM_GLUE=OFF
cmake --build "$deps/onda-faust-main-cmake" --target faust dynamiclib -j 8

make -C "$deps/onda-faust-cert4/build" cmake BACKENDS=regular.cmake TARGETS=regular.cmake \
  CMAKEOPTS=-DCMAKE_CXX_COMPILER=clang++
make -C "$deps/onda-faust-cert4/build" -j 8 faust
```

## Run and inspect

Run from the benchmark checkout. Choose an available performance core. This command runs all
18 workloads and captures optimized LLVM IR and Onda MIR for FM. A matching source in
`dsp/explicit_loops/` runs in the same process as the per-sample source and Faust, with
`onda-block` and `onda-block-fm` in the TSV. The runner sets the same floating-point
denormal mode for every engine in each process.

```bash
faust_args=(
  --faust "$deps/onda-faust-main/build/bin/faust"
  --faust-include "$deps/onda-faust-main/architecture"
  --libfaust "$deps/onda-faust-main/build/lib/libfaust.so"
  --faust-libraries "$deps/onda-faust-libraries"
  --cert4 "$deps/onda-faust-cert4/build/bin/faust"
  --cpu 8 --rounds 21 --round-ms 20 --libmvec
)
python3 tools/linux/run.py "${faust_args[@]}" --flush-denormals --out build/run --ir fm_pad
python3 tools/linux/summarize.py build/run/results.tsv
python3 report/readme_chart.py . --linux-results build/run/results.tsv \
  --machine 'Intel Core i9-14900HX, Linux x86-64, FTZ/DAZ'
```

Pass `--flush-denormals` for FTZ/DAZ on x86-64. Pass `--llvm-no-fast` in a separate diagnostic
run to disable the default Faust LLVM fast-math flags on the audited version. Inspect the
emitted IR to verify this setting. Use the diagnostic run's `-no-fm` rows for this experiment.

## Compare against the original sources

Use the original benchmark revision as the baseline. The left side of each
`--onda-variant` mapping uses the workload name in that checkout.

```bash
git worktree add --detach build/original 95a4b9bdd20ad8a2dc8039ebfb558c765d91e934
python3 tools/linux/run.py "${faust_args[@]}" --upstream build/original \
  --flush-denormals --out build/variants --ir fm_pad --ir hoa_decoder_x \
  --onda-variant fm_pad:onda-final=dsp/fm_pad.onda \
  --onda-variant hoa_decoder_x:onda-final=dsp/hoa_decoder.onda \
  --onda-variant mixer16_x:onda-final=dsp/mixer16.onda \
  fm_pad hoa_decoder_x mixer16_x
python3 tools/linux/summarize.py --upstream-corpus --tuned-onda build/variants/results.tsv
```

Each workload subdirectory contains `build.log`, the Onda object and descriptor for each arm,
and the generated Faust C++ sources. With `--ir`, the `.ll` files come from the Onda compiler,
Clang on the timed Faust C++ translation unit, or the timed libfaust LLVM factory. Use
`llvm-objdump -d build/run/fm_pad/onda.o` to inspect native instructions. The runner keeps
cert-4 compilation rejections in the individual workload logs and excludes those engines.
