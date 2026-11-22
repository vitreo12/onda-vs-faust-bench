"""Build a macOS report from the default-contraction and no-contraction benchmark runs."""
import collections, html, json, math, os, re, sys

B, out_dir = sys.argv[1:3]


def load(path):
    R = collections.defaultdict(dict)
    for l in open(path):
        f = l.rstrip('\n').split('\t')
        if len(f) > 2:
            R[f[0]][f[1]] = float(f[2])
    return R


R = load(f"{out_dir}/results.tsv")
for n, r in load(f"{out_dir}/results_nocontract.tsv").items():
    for k in ('cpp-scal', 'cpp-vec', 'ocpp', 'ocpp48'):
        if k in r:
            R[n][k + '-ieee'] = r[k]

# Programs by DSP category.
CATS = [
    ('Oscillators and sources', [('sine', 'phasor + sin'), ('fm_pad', '2 FM voices + tanh'), ('additive64', '64 sine partials'),
                                 ('noise', 'LCG + one-pole lowpass')]),
    ('Nonlinearities', [('tanh_drive', 'tanh saturation')]),
    ('Filters', [('biquad8', '8 RBJ biquads in series'), ('peq10', '10-band parametric EQ'),
                 ('svf_mod', 'TPT SVF, cutoff modulated per sample'), ('fir32c', '32-tap FIR')]),
    ('Matrices and mixing', [('hoa_decoder', '2D HOA decoder, order 3, 7→8'),
                            ('mixer16', '16-channel mixer, dB gain + pan')]),
    ('Delays and reverbs', [('freeverb', '8 combs + 4 allpasses'), ('fdn8', '8-line FDN, dense Hadamard'),
                                  ('diffuser32', '32 allpasses in series'), ('zita_rev', 're.zita_rev1_stereo')]),
    ('Physical models', [('clarinet', 'pm.clarinet_ui_MIDI, gate held'), ('violin', 'pm.violin_ui_MIDI, gate held'),
                         ('frenchbell', 'pm.frenchBell_ui, 50 modes, struck once')]),
]
unknown = R.keys() - {name for _, progs in CATS for name, _ in progs}
if unknown:
    raise SystemExit(f"Unexpected workloads in the macOS results: {', '.join(sorted(unknown))}")
CATS = [(cat, [(name, label) for name, label in progs if name in R]) for cat, progs in CATS]
CATS = [(cat, progs) for cat, progs in CATS if progs]
if not CATS:
    raise SystemExit("No benchmark workloads in the macOS results.")
json.dump(R, open(f"{out_dir}/results.json", 'w'), indent=1)
cols = [('onda', 'onda'), ('onda-fm', 'onda --fast-math'),
        ('cpp-scal-ieee', 'C++ IEEE'), ('cpp-scal-fm', 'C++ -ffast-math'), ('cpp-vec-fm', 'C++ -vec -ffast-math'),
        ('cpp-vec-acc', 'C++ -vec + Accelerate'), ('llvm-scal', 'Faust LLVM'), ('llvm48', 'Faust LLVM, fixed SR'),
        ('ocpp-ieee', 'ocpp IEEE'), ('ocpp48-ieee', 'ocpp IEEE, fixed SR'), ('ocpp-fm', 'ocpp -ffast-math'),
        ('best-fm', 'fcautotool pick'), ('best48-fm', 'pick, fixed SR')]
IEEE = ['cpp-scal-ieee', 'cpp-vec-ieee', 'ocpp-ieee', 'ocpp48-ieee']
FAST = ['cpp-scal-fm', 'cpp-vec-fm', 'cpp-vec-acc', 'llvm-scal', 'llvm-vec', 'llvm48', 'ocpp-fm', 'best-fm', 'best48-fm']
IEEE_OLD = ['cpp-scal-ieee', 'cpp-vec-ieee']                                   # Faust 2.95.1
FAST_OLD = ['cpp-scal-fm', 'cpp-vec-fm', 'cpp-vec-acc', 'llvm-scal', 'llvm-vec']


def best(r, keys):
    return min(r[k] for k in keys if k in r)


def num(v):
    return f'{v:.2f}' if v < 100 else f'{v:.1f}'


def rat(x):
    c = 'win' if x >= 1.05 else ('loss' if x <= 0.95 else 'tie')
    return f'<td class="ratio {c}">×{x:.2f}</td>'


rows, chart, stats = [], [], []
ncols = len(cols) + 3
for cat, progs in CATS:
    rows.append(f'<tr class="cat"><th colspan="{ncols}" scope="rowgroup">{html.escape(cat)}</th></tr>')
    for n, lab in progs:
        r = R[n]
        lo = min(r[c] for c, _ in cols if c in r)
        cells = ''.join(('<td class="best">' if r.get(c) == lo else '<td>') + (num(r[c]) if c in r else '—') + '</td>' for c, _ in cols)
        s, f = best(r, IEEE) / r['onda'], best(r, FAST) / r['onda-fm']
        rows.append(f'<tr><th scope="row"><code>{n}</code><span class="lab">{html.escape(lab)}</span></th>{cells}{rat(s)}{rat(f)}</tr>')
        chart.append({'n': n, 's': round(s, 3), 'f': round(f, 3)})
        stats.append((s, f, best(r, IEEE_OLD) / r['onda'], best(r, FAST_OLD) / r['onda-fm']))

g = lambda a: math.exp(sum(map(math.log, a)) / len(a))
gs, gf = g([x[0] for x in stats]), g([x[1] for x in stats])
gso, gfo = g([x[2] for x in stats]), g([x[3] for x in stats])
wins = sum(x[0] >= 1.05 for x in stats); ties = sum(0.95 < x[0] < 1.05 for x in stats); losses = len(stats) - wins - ties
fwins = sum(x[1] >= 1.05 for x in stats); fties = sum(0.95 < x[1] < 1.05 for x in stats); flosses = len(stats) - fwins - fties

# options elected by fcautotool
erows = []
for _, progs in CATS:
    for n, _ in progs:
        f = f"{B}/results/autotool/{n}.txt"
        if not os.path.exists(f):
            continue
        t = open(f).read()
        m = re.search(r'winner (\S+) \(([0-9.]+) ns/frame.*?-- (.*?)  \[', t)
        cpp = re.search(r'^\s+cpp\s+([0-9.]+) ns', t, re.M)
        if m and cpp:
            erows.append(f'<tr><th scope="row"><code>{n}</code></th><td style="text-align:left"><code>{html.escape(m.group(3))}</code></td>'
                         f'<td>{float(m.group(2)):.2f}</td><td>{float(cpp.group(1)):.2f}</td>'
                         f'<td class="ratio">×{float(cpp.group(1)) / float(m.group(2)):.2f}</td></tr>')

src = []
for cat, progs in CATS:
    for n, lab in progs:
        fd = open(f"{B}/dsp/{n}.dsp").read(); od = open(f"{B}/dsp/{n}.onda").read()
        op = ' open' if n == 'zita_rev' else ''
        src.append(f'''<details{op}><summary><code>{n}</code> — {html.escape(lab)}</summary><div class="pair">
<figure><figcaption>Faust · {n}.dsp</figcaption><pre><code>{html.escape(fd)}</code></pre></figure>
<figure><figcaption>Onda · {n}.onda</figcaption><pre><code>{html.escape(od)}</code></pre></figure></div></details>''')

fr = lambda x: f'{x:.2f}'
sub = {'ROWS': '\n'.join(rows), 'HEAD': ''.join(f'<th scope="col">{html.escape(t)}</th>' for _, t in cols),
       'CHART': json.dumps(chart), 'SOURCES': '\n'.join(src), 'EROWS': '\n'.join(erows),
       'GS': fr(gs), 'GF': fr(gf), 'GSO': fr(gso), 'GFO': fr(gfo), 'NPROG': str(len(stats)),
       'WINS': str(wins), 'TIES': str(ties), 'LOSSES': str(losses),
       'FWINS': str(fwins), 'FTIES': str(fties), 'FLOSSES': str(flosses)}
out = open(f"{B}/report/template.html").read()
for k, v in sub.items():
    out = out.replace(f'%%{k}%%', v)
assert '%%' not in out, re.findall(r'%%\w+%%', out)
open(f"{out_dir}/onda-vs-faust.html", 'w').write(out)
print(f'{len(stats)} programs: strict {gs:.3f} fast {gf:.3f} | vs 2.95.1 strict {gso:.3f} fast {gfo:.3f} | '
      f'strict W/T/L {wins}/{ties}/{losses} fast {fwins}/{fties}/{flosses}')
