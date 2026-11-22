# Faster Onda rewrites

The current Onda syntax supports a faster FIR, feedback delay network, and diffuser. The
rewrites use fixed-size arrays, compile-time namespace parameters, and bounded ring cursors.
All audio indexing uses the language's ordinary indexing syntax. For each workload the original
Onda source, the rewrite, and every Faust configuration ran in the same 21 shuffled rounds.
These are median ns/frame on the Intel i9-14900HX at 48 kHz, with 256-frame blocks and FTZ/DAZ
enabled. [Machine and compiler provenance](linux-audit.md#machine-and-provenance), [Raw timings](../results/linux-x86_64/onda-idiomatic.tsv)

| Workload | Onda strict, original → rewrite | Onda fast, original → rewrite | Best Faust, strict / fast |
| --- | ---: | ---: | ---: |
| 32-tap FIR | 6.24 → **2.83** | 5.62 → **4.24** | 4.94 / 2.72 |
| Eight-line FDN | 14.33 → **5.99** | 12.81 → **5.02** | 4.92 / 3.77 |
| 32-stage diffuser | 24.09 → **22.19** | 16.09 → **14.04** | 20.21 / 13.90 |
| [FM pad](../dsp/explicit_loops/fm_pad.onda) | 24.06 → **6.63** | 23.45 → **6.54** | 24.38 / 13.72 |
| Ambisonic decoder | 53.22 → **0.83** | 53.58 → **0.44** | 0.36 / 0.31 |

The FM and decoder rows replicate the earlier experiments. The decoder's original column uses
the upstream dynamic `ins[]` / `outs[]` variant. The earlier comparison already uses the optimized
scalar-port `hoa_decoder_x` in its aggregate. The diffuser's fast result is within the observed
variation of the fastest Faust result. [Original workload selection](https://github.com/sletz/onda-vs-faust-bench/blob/95a4b9bdd20ad8a2dc8039ebfb558c765d91e934/report/gen.py#L24-L49)

## What changed

- **FIR.** The sample is stored twice in a mirrored ring, giving every tap a contiguous history
  window. The standard library's direct convolver uses the same layout. A fixed array of four
  partial sums exposes independent operations and lets LLVM emit packed loads and floating-point
  instructions in strict mode. Physical state increases from 132 to 320 bytes. In screening, the
  mirrored loop with the original left-to-right sum reduced strict time by about 16%. Use that
  form when the original addition order is required. [Onda standard library](https://github.com/onda-lang/onda/blob/0.9.2/stdlib/std/convolution.onda)
- **FDN.** One `{Capacity, wrap}` cursor advances all eight delay lines. A constant table preserves
  their individual delays, and each line occupies a fixed section of a flat history array. Three
  compile-time-specialized butterfly stages replace the dense Hadamard multiply. In screening, a
  shared cursor with a dense mixer took about 11.4 ns/frame fast, a butterfly with a bank of
  structs took 10.7, and the flat array with a butterfly took about 5.0. The chosen form costs
  65,664 bytes of state, up from 46,400.
- **Diffuser.** A constant delay table and a four-stage namespace specialization reduce the source
  from 84 to 53 lines. Each section retains its exact-length, bounded rings and the serial stage
  order. A homogeneous bank indexed at runtime took about 70 ns/frame in screening, and a bank of
  standard-library allpass processors took about 80. Keeping the stage lengths visible at compile
  time worked better for this cascade on this compiler. Those screening variants matched the
  reference output. The section rewrite's strict speedup varied across runs, and the fast-math
  speedup repeated.

The four-way FIR sum and the butterfly preserve the DSP transfer functions and change
floating-point evaluation order. All 115 timing rows met the benchmark's output gate. A
separate comparison of the three new rewrites against their original Onda sources ran 512
blocks of impulse or noise. In the noise check, the rewrites processed the same blocks in
77-frame and 179-frame segments, and the FDN's gain and damping changed three times. The
largest relative RMS error across these checks was `1.57e-7`. The diffuser matched exactly.

The [archived timings](../results/linux-x86_64/onda-idiomatic.tsv) record these
experimental implementations. See the [Linux runner instructions](../tools/linux/README.md#compare-against-the-original-sources)
to benchmark the current sources against upstream.
