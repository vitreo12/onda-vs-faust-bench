# Onda vs Faust on x86-64 Linux

The audit below covers the original benchmark sources. The [README](../README.md) shows the
measurements after promoting the optimized sources.

The upstream benchmark uses Onda’s raw AOT processing callback. This is the intended fast path
for a host with a compiled object and a valid block. The shared harness and the use of the same
workload and audio buffers make this a useful native DSP comparison. Sample-rate specialization,
floating-point policy, input and output validation, and the optimization effort invested in each
source program affect the interpretation of the results.

## Reproduction results

The Apple M5 headline favored Onda against stock Faust and favored Faust once cert-4 entered the
comparison. The Intel run reproduced the first result in all three runs. With cert-4 included,
the two engines were close under preserved subnormals. Shared FTZ/DAZ restored the Apple ranking
for the original sources. Greater than ×1 means Onda is faster. Each figure is the geometric mean
across the 18 primary workloads of each workload's fastest eligible Faust time divided by its
Onda time. [Apple report](onda-vs-faust.html), [Linux aggregation](../tools/linux/summarize.py)

| Onda build and source | Host denormal mode | Stock Faust strict / fast | All Faust strict / fast |
| --- | --- | ---: | ---: |
| Apple M5, Onda 0.9.2 | Publication setting | ×1.19 / ×1.06 | ×0.90 / ×0.78 |
| Linux, released Onda 0.9.2 | Preserve | ×1.219 / ×1.333 | ×0.965 / ×1.045 |
| Linux, local Onda 0.9.3 | Preserve | ×1.223 / ×1.334 | ×0.964 / ×1.046 |
| Linux, local Onda 0.9.3 | FTZ/DAZ | ×1.178 / ×1.126 | ×0.912 / ×0.901 |
| Linux, local Onda 0.9.3 with same-round source variants eligible | FTZ/DAZ | ×1.465 / ×1.253 | ×1.134 / ×1.002 |

The Linux stock group uses Faust 2.95.1 at runtime sample rate, including the Linux libmvec
candidate in fast math. The all-configurations group adds fixed 48 kHz and cert-4. Restricting
the FTZ/DAZ comparison to compile-time 48 kHz on both sides gives ×0.915 strict and ×1.031 fast
for the original Onda sources. The four upstream alternative-source workloads stay out of all
geometric means. The tuned Onda row allows the fastest same-round Onda source per workload.

All 1,380 rows in the three full Linux sweeps passed the default-control four-second check.
The largest per-channel relative RMS error was 0.000786675, on `additive64`. The median
within-run MAD was 0.8–1.4% of each arm's median. These measurements characterize the
given machine and toolchain with 256-frame blocks. [Released Onda TSV](../results/linux-x86_64/onda-0.9.2-preserve.tsv), [Local Onda TSV](../results/linux-x86_64/onda-0.9.3-preserve.tsv), [FTZ/DAZ and source variants TSV](../results/linux-x86_64/onda-0.9.3-flush.tsv)

A [follow-up on idiomatic Onda rewrites](idiomatic-onda.md) measures new FIR, FDN, and diffuser
variants and repeats the FM and decoder experiments in a common run.

The French bell illustrates the impact of denormal policy. It is struck once before 10.67
seconds of warmup, so timing measures the late tail. With preserved subnormals, strict Onda
took 241 ns/frame and scalar C++ Faust took 1,240. With FTZ/DAZ, these fell to 21.4 and 52.8,
and fixed-rate Faust cert-4 reached 14.2 strict and 9.11 fast. Violin moved from 100 to 24.5 ns/frame
in strict Onda and from 129 to 37.4 in strict scalar C++ Faust. The mode was shared by all
engines within each run. Per-note attack and retrigger timing would require a separate schedule.
[French bell source](../dsp/frenchbell.dsp), [Preserve TSV](../results/linux-x86_64/onda-0.9.3-preserve.tsv), [FTZ/DAZ TSV](../results/linux-x86_64/onda-0.9.3-flush.tsv)

## Callback and correctness audit

- The original harness links `onda_processor_init` and `onda_process` under renamed symbols and
  calls the latter with `start_frame=0`, `frames=256`, and both block flags. It already bypasses
  the hosted API, so changing it to `onda_process_unchecked` would add the hosted instance layer.
  For an Onda JIT comparison using `libonda`, bind input and output memory, fully initialize the
  instance, call `onda_prepare_process` once, then use `onda_process_unchecked` for whole blocks.
  The raw and hosted fast paths both retain generated DSP safety semantics.
  [Original harness](../harness.cpp#L57-L83), [Onda 0.9.2 processor ABI](https://github.com/onda-lang/onda/blob/0.9.2/docs/processor-abi.md), [Onda hosted C API](https://github.com/onda-lang/onda/blob/0.9.2/docs/api.md#unchecked-processing)
- The original raw harness hand-declares the ABI, derives allocations and defaults from the strict
  object alone, and ignores the return from processing. The Linux harness uses the public ABI
  types and each object's descriptor, checks init and process status, and requires matching Faust
  and Onda port counts. Those checks include a status branch once per Onda block. Host readiness,
  compilation, initialization, and numerical checking are outside the timed loop.
  [Original build](../build.sh#L16-L41), [Linux harness](../tools/linux/harness.cpp), [Linux runner](../tools/linux/run.py)
- The original checker compares all 16 shared output buffers, including channels the DSP never
  writes. The report discards the numerical columns before choosing a winner. The Linux harness
  compares only declared outputs, poisons them before every untimed call to detect unwritten
  samples, and computes relative RMS per channel against the no-contraction Faust C++ scalar
  reference. The summary admits finite results with worst-channel relative RMS at or below
  `0.001`. That threshold covers the already published errors, whose maximum reported relative RMS
  was `0.000787`. An entirely silent reference channel requires exact silence. These are four-second
  renders with deterministic noise and default controls. Control automation, impulse and adversarial
  inputs, and very long feedback behavior are outside the tested domain.
  [Original checker](../harness.cpp#L129-L208), [Original report aggregation](https://github.com/sletz/onda-vs-faust-bench/blob/95a4b9bdd20ad8a2dc8039ebfb558c765d91e934/report/gen.py#L8-L21), [Published measurements](../results/results_nocontract.tsv), [Linux summary](../tools/linux/summarize.py)
- The Apple strict aggregate combines Onda from the default-contraction run with Faust C++ from
  a separate no-contraction run. Using the Onda numbers from that same no-contraction run changes
  the strict geometric means from ×1.187 to ×1.196 against stock Faust, and ×0.901 to ×0.907
  with cert-4. The Linux run interleaves both floating-point policies and every backend in the
  same process. It also measures scalar and vector C++ and LLVM with `SR` fixed at 48 kHz, since
  Onda has that constant at compile time. The fixed-rate and runtime-rate Faust arms use the
  same library revision.
  [Original Apple run script](https://github.com/sletz/onda-vs-faust-bench/blob/95a4b9bdd20ad8a2dc8039ebfb558c765d91e934/run_all.sh), [Original aggregate calculation](https://github.com/sletz/onda-vs-faust-bench/blob/95a4b9bdd20ad8a2dc8039ebfb558c765d91e934/report/gen.py#L43-L85), [Faust rate specialization](https://faustdoc.grame.fr/manual/optimizing/#specializing-the-dsp-code)
- The strict C++ arm uses `-ffp-contract=off`. Faust can already change floating-point operation
  order during signal normalization. For example, the generated scalar FM recurrence is
  `inc - floor(inc + old) + old`, while the Onda source evaluates `old + inc` first. “Strict” in
  these tables identifies the native compiler policy. The output tolerance is the test of
  equivalence between the two source programs. Fast math relaxes each compiler's usual contract.
  [Original Onda FM source](https://github.com/sletz/onda-vs-faust-bench/blob/95a4b9bdd20ad8a2dc8039ebfb558c765d91e934/dsp/fm_pad.onda), [Faust FM source](../dsp/fm_pad.dsp), [Faust LLVM flags](https://github.com/grame-cncm/faust/blob/955f6e2ad2d985bd2ae1b288bebb2858ec1e6a91/compiler/generator/llvm/llvm_code_container.cpp#L76-L95)

## Machine and provenance

- CachyOS Linux `7.3.4-1-cachyos`, Intel Core i9-14900HX, pinned to logical CPU 8 on a P-core.
  The CPU governor was `powersave` with `balance_performance`. Clang and system LLVM were 23.1.5,
  glibc was 2.44, and the local Onda used its LLVM 21.1.2 toolchain. Each engine processed 256
  frames per call at 48 kHz with 2,000 warm-up blocks followed by 21 interleaved shuffled rounds.
  Calibration targeted 20 ms for the slowest arm in each round. Results are median ns per frame
  across all channels. TSVs include median absolute deviation.
- The workload source is `95a4b9bdd20ad8a2dc8039ebfb558c765d91e934`. Onda 0.9.2 came from the
  published Linux x64 release (`dcdf2eaf8a47a0c76baca7607072d9286f30b81a`) and was verified against
  its published SHA-256. The Onda 0.9.3 runs used the local checkout based on
  `e9ec3d0a5bc446a5f59bcd04783ced0958b0537f` with working-tree changes. Its release executable's
  SHA-256 was `50b827cc96b6b6509fafd1462831780887c425affabbf8b2753bc4568fd92e6b`. The binary
  identifies the exact local tool used. The release run provides the independently available Onda
  toolchain. [Benchmark revision](https://github.com/sletz/onda-vs-faust-bench/tree/95a4b9bdd20ad8a2dc8039ebfb558c765d91e934), [Onda release](https://github.com/onda-lang/onda/releases/tag/0.9.2)
- Faust 2.95.1 was built from `955f6e2ad2d985bd2ae1b288bebb2858ec1e6a91` and the cert-4
  Faust 2.92.5 from `106dda74a549501a6d96624cc2adde0ffecf5106`, the revision named in the Apple
  report. Both used `faustlibraries` at `c957169c07f80e6e99ca7af3949aa7f02aa38e9b`. The Apple
  report gives version labels and an independent library checkout path. Its exact stock Faust
  and library commits are unspecified. Apple Accelerate was replaced by a glibc libmvec candidate.
  The `m5-pick` arms reused the flags elected by `fcautotool` on the M5. Faust cert-4 rejected
  the violin in both rate modes here as well. The cert-4 comparison measures a compiler revision
  and backend together. Isolating the backend would require testing both backends on one revision.
  [Faust 2.95.1](https://github.com/grame-cncm/faust/tree/955f6e2ad2d985bd2ae1b288bebb2858ec1e6a91), [Faust cert-4](https://github.com/grame-cncm/faust/tree/106dda74a549501a6d96624cc2adde0ffecf5106), [Faust libraries](https://github.com/grame-cncm/faustlibraries/tree/c957169c07f80e6e99ca7af3949aa7f02aa38e9b), [Apple flags](../results/autotool)

## Onda source and LLVM findings

The original Onda versions generally use the right execution rates. The oscillators and filter
cascades calculate control-dependent coefficients in `block`, the FIR reserves `init` or a
`const def` for its tap table, and the delays express their cursors with bounded integer `wrap`
domains. The emitted FIR and FDN code contains no per-tap bounds clamps or remainder instructions.
The FIR uses a mask, and the non-power-of-two rings use compare-and-reset. Blanket
`read_unsafe` or `write_unsafe` conversions would add proof obligations without helping those
loops. The largest opportunities were loop scheduling and representation. [Onda language guide on unchecked access](https://github.com/onda-lang/onda/blob/0.9.2/docs/syntax.md#unchecked-indexed-access), [Original FIR](https://github.com/sletz/onda-vs-faust-bench/blob/95a4b9bdd20ad8a2dc8039ebfb558c765d91e934/dsp/fir32c.onda), [Original FDN](https://github.com/sletz/onda-vs-faust-bench/blob/95a4b9bdd20ad8a2dc8039ebfb558c765d91e934/dsp/fdn8.onda)

The table uses the common FTZ/DAZ run. Strict and fast values are each median ns/frame.

| Workload | Onda source change | Strict before → after | Fast before → after |
| --- | --- | ---: | ---: |
| `additive64` | Render partials, then sum in source order | 353.96 → 39.19 | 29.07 → 32.13 |
| `fm_pad` | Split the phase recurrence from waveform rendering | 25.15 → 6.90 | 24.58 → 6.84 |
| `hoa_decoder` | Declare named input/output arrays | 50.02 → 0.86 | 50.64 → 0.46 |
| `mixer16_x` | Declare a named channel array, keeping block-rate coefficients | 1.12 → 1.11 | 0.94 → 0.94 |
| `biquad8` | Factor the equal feed-forward coefficients | 5.99 → 5.72 | 4.83 → 4.22 |
| `peq10` | Reuse adjacent stages' history and sum past terms first | 13.95 → 9.65 | 13.95 → 8.53 |

- In `additive64`, LLVM kept scalar `sinf` calls in the strict fused reduction in both Onda
  versions. A separate render loop exposes eight-wide SLEEF sine calls with an ordered sum.
  The original fast version already vectorizes the fused reduction and benefits from avoiding
  the temporary array. On this CPU the source shape that minimizes runtime depends on the
  floating-point permissions. This is a compiler opportunity for an ordered reduction over
  independent expensive math when loop fission pays for temporary storage.
  [Additive variant](../dsp/additive64.onda)
- In `fm_pad` the original Onda code packs four phase updates into a vector, but calls scalar
  libm for sine and tanh. The split version lets LLVM run eight-wide SLEEF sine and tanh over
  consecutive frames. Worst-channel relative RMS against the Faust reference remained
  0.000245 strict and 0.000532 fast or lower. Faust `-vec` already schedules separate phase and
  waveform loops. With libmvec, Clang emitted `_ZGVdN8v_sinf` and `llvm.tanh.v8f32` and improved
  from 24.24 to 14.23 ns/frame under fast math. The Faust object imports vector sine and scalar
  `tanhf`. The Onda variant renders the whole block in advance and stores it until `sample`
  publishes each frame. These timings use complete callbacks.
  [FM variant](../dsp/explicit_loops/fm_pad.onda), [Faust FM](../dsp/fm_pad.dsp)
- The dynamic `ins[]` and `outs[]` views in `hoa_decoder` leave port selection inside the sample
  loop even though the coordinate is in range. Declared interface arrays remove the dispatch and
  express the channel layout directly. The upstream scalar-port `hoa_decoder_x` reaches 0.75
  strict and 0.47 fast. The large mixer gain comes from moving control-dependent `pow`, `cos`,
  and `sin` to the block section, as upstream already did in `mixer16_x` (97.83 → 1.12 ns/frame
  strict). The named array is a shorter way to express its channels with matching performance.
  [Final decoder](../dsp/hoa_decoder.onda), [Final mixer](../dsp/mixer16.onda)
- `biquad8` can use the same feed-forward factorization as Faust. In `peq10` the delayed inputs
  to a stage are the previous stage's output history. Sharing that history removes ten static
  load sites from the optimized Onda `onda_process` function. Computing the past terms first
  shortens the current-sample dependency. The change reassociates floating-point sums at the
  source level, with the measured worst-channel relative RMS below 0.00057. The cert-4
  winner remains faster on the fast PEQ (6.94 ns/frame). [Measured variants](../results/linux-x86_64/onda-0.9.3-flush.tsv)
- Remaining differences worth profiling include `fdn8` (13.38 Onda versus 4.08 cert-4 fast)
  and `fir32c` (6.07 versus 2.82 on the best Faust fast arm). The FDN source uses exact-length
  delay buffers with distinct wrap cursors. The generated Faust layouts include mask-indexed
  power-of-two storage and the cert-4 tuning options change the scheduling. A common-cursor
  ring variant and an optimized IR comparison of history load scheduling would test how much
  of the gap is storage and how much is dependency order. The opposite pattern appears in
  `tanh_drive`, where Onda's vector SLEEF implementation takes 0.59 versus Faust's 2.59 ns/frame
  under fast math. [Original FDN pair](https://github.com/sletz/onda-vs-faust-bench/blob/95a4b9bdd20ad8a2dc8039ebfb558c765d91e934/dsp/fdn8.onda), [FDN Apple-selected flags](../results/autotool/fdn8.txt), [FTZ/DAZ TSV](../results/linux-x86_64/onda-0.9.3-flush.tsv)

## Inspecting and tuning Faust

Faust supports two LLVM inspection paths. For the direct backend, the runner exports optimized
IR with `writeDSPFactoryToIRFile` from the same host-target O3 JIT factory it times. Faust also
exposes `FAUST_DEBUG=FAUST_LLVM1` and `FAUST_DEBUG=FAUST_LLVM2` for IR before and after
optimization. For C++ and oCPP, the runner uses `clang++ -O3 -march=native -S -emit-llvm` with
the same floating-point and vector-library flags as the timed object. Clang's `-Rpass`,
`-Rpass-missed`, `-Rpass-analysis`, and `-fsave-optimization-record` can explain vectorization
decisions. Onda's `--emit llvm-ir` and `--emit mir` expose both compiler stages directly.
[Faust optimized factory implementation](https://github.com/grame-cncm/faust/blob/955f6e2ad2d985bd2ae1b288bebb2858ec1e6a91/compiler/generator/llvm/llvm_dynamic_dsp_aux.cpp#L433-L472), [Faust IR export](https://github.com/grame-cncm/faust/blob/955f6e2ad2d985bd2ae1b288bebb2858ec1e6a91/compiler/generator/llvm/llvm_dynamic_dsp_aux.cpp#L257-L270), [Clang optimization remarks](https://clang.llvm.org/docs/UsersManual.html#options-to-emit-optimization-reports), [Reproduction commands](../tools/linux/README.md)

The direct Faust backend defaults to fast arithmetic flags. On this Faust revision, use
`FAUST_OPT=FAUST_LLVM_NO_FM` in a separate process to disable that policy. The built-in help
incorrectly names `FAUST_DEBUG` for this one switch. Inspect the IR to verify the result. The
setting leaves frontend normalization in place and is a separate diagnostic arm. LLVM JIT
uses a bare `PassBuilder` for the O3 middle-end, with a separate host target selection for
native code. The two routes expose different frontend schedules and optimizer inputs even
when both run LLVM.
[Environment parser](https://github.com/grame-cncm/faust/blob/955f6e2ad2d985bd2ae1b288bebb2858ec1e6a91/compiler/global.cpp#L1228-L1247), [Native pipeline](https://github.com/grame-cncm/faust/blob/955f6e2ad2d985bd2ae1b288bebb2858ec1e6a91/compiler/generator/llvm/llvm_dynamic_dsp_aux.cpp#L365-L472)

The diagnostic run on `sine`, `fm_pad`, and `biquad8` verified the setting. For FM the optimized
default factory emitted `fadd reassoc nnan ninf nsz arcp contract`, and the diagnostic factory
emitted plain `fadd`. The diagnostic results use nine rounds and are outside the headline
comparison. [No-fast-math diagnostic TSV](../results/linux-x86_64/faust-llvm-no-fast.tsv)

For Faust, compare `-scal` with `-vec`, change the chunk size `-vs` and loop shape `-lv`, and
inspect the generation of delay lines and the placement of math across loops. `fcautotool` searches
C++ and oCPP options, including cert-4 layout and scheduling options. Its published version
defaults to 512 frames and initializes at 44.1 kHz, so rerun any selected candidate at the intended
block size and sample rate. `faustbench-llvm` searches the direct JIT backend's flags and accepts
`-bs 256`. The same validation gate and a fresh shared-harness comparison apply to either tuner.
[Faust optimization guide](https://faustdoc.grame.fr/manual/optimizing/), [fcautotool timing harness](https://github.com/orlarey/faustcompilerbenchtool/blob/1dbf3ea4af3b6fa44d011fb2521e4ee01cc330c3/flasharch_footer.cpp#L68-L81), [faustbench-llvm](https://github.com/grame-cncm/faust/blob/955f6e2ad2d985bd2ae1b288bebb2858ec1e6a91/tools/benchmark/faustbench-llvm.cpp#L35-L96)
