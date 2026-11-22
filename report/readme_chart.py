"""Draw README charts from macOS JSON or validated Linux benchmark results."""
import argparse
from html import escape
import json
import math
from pathlib import Path
from statistics import geometric_mean
import sys


CATEGORIES = [
    ("Oscillators and sources", ("sine", "fm_pad", "additive64", "noise")),
    ("Nonlinearities", ("tanh_drive",)),
    ("Filters", ("biquad8", "peq10", "svf_mod", "fir32c")),
    ("Matrices and mixing", ("hoa_decoder", "mixer16")),
    ("Delays and reverbs", ("freeverb", "fdn8", "diffuser32", "zita_rev")),
    ("Physical models", ("clarinet", "violin", "frenchbell")),
]
THEMES = {
    "light": dict(bg="#ffffff", ink="#1f2328", muted="#485465", grid="#dbe0e6", baseline="#758194",
                  onda="#1764ad", faust="#a04a11"),
    "dark": dict(bg="#0d1117", ink="#f0f3f6", muted="#b1bac4", grid="#303944", baseline="#8995a4",
                 onda="#75bdff", faust="#f6a76d"),
}
SAMPLE = "sample"
BLOCK = "block"
MEAN = "Geometric mean"


def policy_ratios(results, names, suffix, candidates):
    ratios = {}
    for name in names:
        times = results.get(name, {})
        sample = "onda" + suffix
        block = "onda-block" + suffix
        if sample not in times:
            raise ValueError(f"{name} lacks an eligible {sample} timing")
        faust = candidates & times.keys()
        if not faust:
            ratios[name] = {}
            continue
        best = min(times[engine] for engine in faust)
        scores = {SAMPLE: best / times[sample]}
        if block in times:
            scores[BLOCK] = best / times[block]
        ratios[name] = scores
    return ratios


def add_mean(ratios, has_block):
    eligible = [row for row in ratios.values() if row]
    mean = {}
    if eligible:
        mean[SAMPLE] = geometric_mean(row[SAMPLE] for row in eligible)
        if has_block:
            mean[BLOCK] = geometric_mean(row.get(BLOCK, row[SAMPLE]) for row in eligible)
    return {**ratios, MEAN: mean}


def render_chart(theme, machine, categories, groups, block_names):
    colors = THEMES[theme]
    width = 1160 if len(groups) > 1 else 974
    left, panel_gap, group_gap, top = 155, 14, 34, 142
    right = 44 if len(groups) > 1 else 24
    panels_per_group = 2
    panel_width = (width - left - right - len(groups) * panel_gap
                   - (len(groups) - 1) * group_gap) / (len(groups) * panels_per_group)
    group_width = panels_per_group * panel_width + panel_gap
    values = [value for _, panels in groups for _, panel, _ in panels
              for row in panel.values() for value in row.values()]
    log_min = math.log(min(0.4, min(values) / 1.7))
    log_max = math.log(max(4.5, max(values) * 1.7))
    ticks = [tick for tick in (0.125, 0.25, 0.5, 1, 2, 4, 8, 16, 32)
             if log_min <= math.log(tick) <= log_max]

    layout = []
    position = top
    for category, names in categories:
        layout.append((category.upper(), position, 26, True))
        position += 26
        for name in names:
            height = 36 if name in block_names else 24
            layout.append((name, position, height, False))
            position += height
    position += 8
    height = 39 if block_names else 28
    layout.append((MEAN, position, height, False))
    bottom = position + height
    total_height = bottom + (64 if block_names else 50)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {total_height}" '
        f'width="{width}" height="{total_height}" font-family="system-ui, sans-serif" role="img" aria-labelledby="title">',
        f'<rect width="{width}" height="{total_height}" fill="{colors["bg"]}"/>',
        '<title id="title">Onda vs Faust by workload and compiler</title>',
        f'<text x="24" y="34" font-size="20" font-weight="650" fill="{colors["ink"]}">'
        'Onda vs Faust by workload</text>',
        f'<text x="24" y="56" font-size="13" fill="{colors["muted"]}">'
        f'{machine}, f32, 48 kHz. Bars right of ×1 favor Onda. Log scale.</text>',
    ]
    legend = [(24, "Onda faster", "onda", False), (139, "Faust faster", "faust", False)]
    if block_names:
        legend += [(318, "Per-sample Onda", "muted", False), (461, "Explicit vectorized loops", "muted", True)]
    for x, label, color, outlined in legend:
        fill = colors["bg"] if outlined else colors[color]
        out.append(f'<rect x="{x}" y="69" width="16" height="9" rx="2" fill="{fill}" '
                   f'stroke="{colors[color]}" stroke-width="1.5"/>')
        out.append(f'<text x="{x + 23}" y="78" font-size="12" fill="{colors["ink"]}">{label}</text>')

    for group_index, (toolchain, panels) in enumerate(groups):
        group_left = left + group_index * (group_width + group_gap)
        if group_index:
            divider = group_left - group_gap / 2
            out.append(f'<line x1="{divider:.1f}" x2="{divider:.1f}" y1="{top - 42}" '
                       f'y2="{bottom + 18}" stroke="{colors["grid"]}"/>')
        out.append(f'<text x="{group_left:.1f}" y="{top - 32}" font-size="15" font-weight="650" '
                   f'fill="{colors["ink"]}">{toolchain}</text>')

        for index, (heading, panel, count) in enumerate(panels):
            origin = group_left + index * (panel_width + panel_gap)

            def x_for(value):
                return origin + (math.log(value) - log_min) / (log_max - log_min) * panel_width

            out.append(f'<text x="{origin:.1f}" y="{top - 10}" font-size="13" font-weight="650" '
                       f'fill="{colors["ink"]}">{heading}</text>')
            out.append(f'<text x="{origin + panel_width:.1f}" y="{top - 10}" text-anchor="end" '
                       f'font-size="10.5" fill="{colors["muted"]}">{count} workloads</text>')
            for tick in ticks:
                x = x_for(tick)
                stroke = colors["baseline"] if tick == 1 else colors["grid"]
                out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{top + 4}" y2="{bottom}" stroke="{stroke}"/>')
                out.append(f'<text x="{x:.1f}" y="{bottom + 16}" text-anchor="middle" font-size="11" '
                           f'fill="{colors["muted"]}">×{tick:g}</text>')

            for name, y, height, category in layout:
                middle = y + height / 2
                first_panel = group_index == 0 and index == 0
                if category:
                    if first_panel:
                        out.append(f'<text x="24" y="{middle + 4:.1f}" font-size="10.5" font-weight="650" '
                                   f'letter-spacing=".5" fill="{colors["muted"]}">{name}</text>')
                    continue

                weight = 650 if name == MEAN else 400
                if first_panel:
                    out.append(f'<text x="{left - 12}" y="{middle + 4:.1f}" text-anchor="end" '
                               f'font-size="12" font-weight="{weight}" fill="{colors["ink"]}">{name}</text>')

                series = panel[name]
                if not series:
                    out.append(f'<text x="{x_for(1):.1f}" y="{middle + 4:.1f}" text-anchor="middle" '
                               f'font-size="12" fill="{colors["muted"]}">—'
                               f'<title>{name}, {toolchain}, {heading}: no eligible Faust timing</title></text>')
                    continue
                offset = -7 if BLOCK in series else 0
                for kind, ratio in series.items():
                    center = middle + offset
                    offset += 14
                    end = x_for(ratio)
                    low, high = sorted((x_for(1), end))
                    anchor, padding = ("start", 7) if ratio >= 1 else ("end", -7)
                    label = f"×{ratio:.2f}"
                    outlined = kind == BLOCK
                    schedule = "Explicit vectorized loops" if outlined else "Per-sample"
                    color = colors["onda" if ratio > 1 else "faust" if ratio < 1 else "baseline"]
                    fill = colors["bg"] if outlined else color
                    title = f'<title>{name}, {schedule}, {toolchain}, {heading}: {label}</title>'
                    style = f'fill="{fill}" stroke="{color}" stroke-width="{1.5 if outlined else 0}"'
                    extent = high - low
                    if extent < 5:
                        out.append(f'<circle cx="{end:.1f}" cy="{center:.1f}" r="3" {style}>{title}</circle>')
                    else:
                        out.append(f'<rect x="{low:.1f}" y="{center - 4.5:.1f}" '
                                   f'width="{extent:.1f}" height="9" rx="2" {style}>{title}</rect>')
                    label_color = colors["ink"] if ratio == 1 else color
                    display_label = f"Explicit loops {label}" if outlined else label
                    out.append(f'<text x="{end + padding:.1f}" y="{center + 3.5:.1f}" text-anchor="{anchor}" '
                               f'font-size="11" font-weight="{weight}" fill="{label_color}">{display_label}</text>')

    out.append(f'<text x="24" y="{bottom + 36}" font-size="11.5" fill="{colors["muted"]}">'
               'Each panel uses its fastest eligible Faust build per workload. A dash marks a missing timing.</text>')
    if block_names:
        out.append(f'<text x="24" y="{bottom + 52}" font-size="11.5" fill="{colors["muted"]}">'
                   'The vectorized-loop mean uses per-sample timings for workloads with one implementation.</text>')
    out.append('</svg>')
    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--linux-results", type=Path)
    inputs.add_argument("--apple-results", type=Path)
    parser.add_argument("--machine", help="measurement setup shown on a Linux chart")
    args = parser.parse_args()
    if bool(args.linux_results) != bool(args.machine):
        parser.error("--linux-results and --machine must be supplied together")

    categories = CATEGORIES
    if args.linux_results:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "linux"))
        from summarize import ALL_FAST, ALL_STOCK_FAST, ALL_STOCK_STRICT, ALL_STRICT, load_results

        results, _, rejected = load_results(args.linux_results)
        if any(row.endswith(("/onda-block", "/onda-block-fm")) for row in rejected):
            parser.error("an explicit block implementation failed the output check")
        toolchains = (
            ("Stock Faust 2.95.1", ALL_STOCK_STRICT, ALL_STOCK_FAST),
            ("Pinned Faust 2.92.5 cert-4", ALL_STRICT - ALL_STOCK_STRICT, ALL_FAST - ALL_STOCK_FAST),
        )
        machine = escape(args.machine)
    else:
        results = json.loads(args.apple_results.read_text())
        unknown = results.keys() - {name for _, names in CATEGORIES for name in names}
        if unknown:
            parser.error(f"unexpected workloads in the Apple results: {', '.join(sorted(unknown))}")
        categories = [(cat, [name for name in names if name in results]) for cat, names in CATEGORIES]
        categories = [(cat, names) for cat, names in categories if names]
        toolchains = (
            ("Stock Faust", {"cpp-scal-ieee", "cpp-vec-ieee"},
             {"cpp-scal-fm", "cpp-vec-fm", "cpp-vec-acc", "llvm-scal", "llvm-vec", "llvm48"}),
            ("Pinned Faust cert-4", {"ocpp-ieee", "ocpp48-ieee"},
             {"ocpp-fm", "best-fm", "best48-fm"}),
        )
        machine = "macOS"

    names = [name for _, group in categories for name in group]
    if not names:
        parser.error("no benchmark workloads in the results")
    block_names = set()
    for name in names:
        times = results.get(name, {})
        if ("onda-block" in times) != ("onda-block-fm" in times):
            parser.error(f"{name} needs both strict and fast timings for its explicit block implementation")
        if "onda-block" in times:
            block_names.add(name)

    groups = []
    try:
        for toolchain, strict, fast in toolchains:
            panels = []
            for heading, suffix, candidates in (("Strict arithmetic", "", strict), ("Fast math", "-fm", fast)):
                ratios = policy_ratios(results, names, suffix, candidates)
                panels.append((heading, add_mean(ratios, block_names), sum(bool(row) for row in ratios.values())))
            if any(count for _, _, count in panels):
                groups.append((toolchain, panels))
    except ValueError as error:
        parser.error(str(error))
    if not groups:
        parser.error("no eligible Faust timings in the results")

    report_dir = args.root / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        (report_dir / f"chart-{theme}.svg").write_text(render_chart(theme, machine, categories, groups, block_names))
    for toolchain, panels in groups:
        for policy, panel, count in panels:
            print(toolchain, policy, count, {kind: round(value, 3) for kind, value in panel[MEAN].items()})


if __name__ == "__main__":
    main()
