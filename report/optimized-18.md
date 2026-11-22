# Optimized Onda across the 18 primary workloads

This run measures the original sources and the candidate rewrites together. The [README](../README.md)
shows the subsequent run with one promoted Onda source per workload.

Onda led on 14 workloads, the modulated SVF was within 5%, and Faust led on three when each
side used its fastest measured build. The remaining gaps were the ambisonic decoder,
parametric EQ, and the FIR in fast math. Each workload's original Onda source, candidate Onda sources, and Faust
engines ran in the same process and timing rounds. [Full measurement TSV](../results/linux-x86_64/onda-optimized-18.tsv)

## Results

Median ns per frame at 48 kHz with 256-frame blocks and shared FTZ/DAZ, pinned to P-core
CPU 12 on the Intel Core i9-14900HX. Each workload had 21 shuffled rounds. The toolchains
match the Linux audit. Fastest values are selected within each column after the output gate.
The archived timing rows use the original source names, including `hoa_decoder_x` and
`mixer16_x`. The current corpus uses `hoa_decoder` and `mixer16`. [Toolchain provenance](linux-audit.md#machine-and-provenance), [Upstream workload selection](https://github.com/sletz/onda-vs-faust-bench/blob/95a4b9bdd20ad8a2dc8039ebfb558c765d91e934/report/gen.py#L24-L49)

| Workload | Onda strict | Faust strict | Onda fast | Faust fast |
| --- | ---: | ---: | ---: | ---: |
| `additive64` | 39.93 | 305.03 | 29.44 | 92.57 |
| `biquad8` | 4.35 | 5.32 | 4.15 | 4.47 |
| `clarinet` | 10.94 | 12.52 | 8.75 | 11.58 |
| `diffuser32` | 13.46 | 21.43 | 14.03 | 13.51 |
| `fdn8` | 5.32 | 5.21 | 5.18 | 4.09 |
| `fir32c` | 3.01 | 5.19 | 3.16 | 2.87 |
| `fm_pad` | 6.97 | 25.64 | 6.93 | 14.39 |
| `freeverb` | 5.99 | 6.12 | 5.54 | 6.77 |
| `frenchbell` | 11.55 | 15.15 | 6.17 | 9.70 |
| `hoa_decoder_x` | 0.400 | 0.392 | 0.402 | 0.333 |
| `mixer16_x` | 1.14 | 1.19 | 0.964 | 1.07 |
| `noise` | 0.919 | 1.43 | 0.927 | 1.31 |
| `peq10` | 7.82 | 9.71 | 7.50 | 6.90 |
| `sine` | 3.03 | 4.23 | 3.01 | 4.19 |
| `svf_mod` | 7.75 | 14.71 | 7.36 | 7.12 |
| `tanh_drive` | 0.602 | 2.85 | 0.602 | 2.76 |
| `violin` | 18.48 | 25.10 | 16.13 | 17.40 |
| `zita_rev` | 19.88 | 20.90 | 10.29 | 18.36 |

The geometric mean of Faust time divided by Onda time was ×1.64 in the strict comparison and
×1.38 in the fast comparison, with the same 18 workloads and the best eligible Faust
configuration per workload. A ratio between 0.95 and 1.05 is reported as close. That band is a
description of timing magnitude. The TSV retains median absolute deviation for each row.
Against stock Faust 2.95.1 including fixed-rate builds, Onda was faster by over 5% on
all 18 strict workloads and had a geometric mean speedup of ×2.11. When each side used
its fastest eligible build, Onda led on 16 and the decoder and SVF were within 5%.

## Source changes that helped

- **Physical models.** Clarinet and violin compute the pitch, vibrato, and envelope trajectories
  at block scope, then apply fractional delays in the sample loop. A shared waveguide module
  prepares each five-tap interpolation once and lets multiple lines read it with the same
  bounded cursor. In the violin, a reciprocal fourth power uses two squarings and a divide.
  [Block clarinet](../dsp/explicit_loops/clarinet.onda), [Block violin](../dsp/explicit_loops/violin.onda), [Waveguide module](../dsp/common/waveguide.onda)
- **French bell.** A fixed-size mode bank uses padded eight-lane groups and independent
  partial sums. When the excitation is zero, the same mode equations reduce to unforced decay.
  The filters and trigger continue running, so subsequent strikes still enter the same modes.
  This benchmark predominantly measures the late tail. [Modal rewrite](../dsp/frenchbell.onda)
- **Sample recurrences.** An earlier sine experiment separated phase stepping from the waveform
  loop. The modulated SVF separates modulation and coefficient calculations from its feedback
  loop. An earlier noise experiment used compile-time skip-ahead coefficients to produce the
  same wrapping LCG sequence in groups. [Block SVF](../dsp/explicit_loops/svf_mod.onda)
- **FDN.** The ring stores the samples that arrive together in one row. The cursor reads all
  eight channels contiguously, and each write chooses its future row using the channel's delay.
  LLVM emits an aligned eight-wide load for the arriving samples. This keeps the same feedback
  network and improves on the earlier flat per-line history. [FDN](../dsp/fdn8.onda)
- **Cascades and matrices.** Explicit `fma` and precomputed coefficients shorten dependencies
  in the biquads, diffuser and EQ. The decoder shares weighted odd harmonics between opposite
  speakers. Its optimized LLVM IR still contains `vector.memcheck` and a scalar overlap path,
  so the source rewrite leaves useful evidence for a compiler-side investigation. [Biquad](../dsp/biquad8.onda), [Diffuser](../dsp/diffuser32.onda), [EQ](../dsp/peq10.onda), [Decoder](../dsp/hoa_decoder.onda)

The explicit `fma` variants author fused arithmetic even in the strict compiler configuration.
Some rewrites also change addition order. All 416 rows passed the same four-second benchmark
gate. A separate strict Onda-to-Onda check ran 14 new source implementations with
93- and 163-frame segments, changing controls at three block boundaries where applicable.
This included retriggering the physical models. The highest per-channel relative RMS against
the original Onda sources was 0.000479, on the EQ. [Control and segment verification](../results/linux-x86_64/onda-optimized-controls.tsv)

## Final source selection

Noise uses one block-rate coefficient for input gain and integer scaling. Its wrapping LCG
and one-pole FMA run in `sample`. In a same-run comparison, the per-sample rewrite took
0.71 ns/frame strict and the skip-ahead version took 0.87. [Noise](../dsp/noise.onda)

The sine benchmark uses Onda’s basic sine example verbatim. Both languages evaluate `sin`
at the current phase and then advance a wrapped radian phase. The defaults are 440 Hz,
zero initial phase, and a gain of 0.6. [Onda source](../dsp/sine.onda), [Faust source](../dsp/sine.dsp)

The [current measurements](../results/linux-x86_64/current.tsv) compare the per-sample
implementations with six explicit vectorized-loop implementations. The block versions split sine and FM
phase updates from waveform evaluation, or prepare filter coefficients and waveguide
trajectories before applying per-sample feedback. The SVF uses equivalent cutoff formulas
with `pow` in the per-sample version and vectorizable `exp` in the block version. Noise
batches the random-number sequence and applies its one-pole filter in `sample`.
Both Onda schedules are timed against the same Faust builds.

| Workload | Sample strict | Vectorized loops strict | Sample fast | Vectorized loops fast |
| --- | ---: | ---: | ---: | ---: |
| `clarinet` | 11.98 | 9.16 | 10.09 | 7.53 |
| `fm_pad` | 23.64 | 6.36 | 23.06 | 6.36 |
| `noise` | 0.71 | 0.85 | 0.71 | 0.85 |
| `sine` | 3.43 | 2.60 | 3.43 | 2.59 |
| `svf_mod` | 14.00 | 6.94 | 13.84 | 6.83 |
| `violin` | 21.94 | 15.58 | 21.78 | 14.14 |

Times are median ns/frame. In a separate check with 93- and 163-frame segments
and control changes between logical blocks, the worst relative RMS difference
between the schedules was below 0.001%. [Control check](../results/linux-x86_64/schedule-controls.tsv)

The [Linux runner instructions](../tools/linux/README.md#compare-against-the-original-sources)
show how to compare final and upstream implementations in the same timing rounds.
