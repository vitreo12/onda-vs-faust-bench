#!/usr/bin/env python3
"""Build and time the sletz/onda-vs-faust-bench sources on x86-64 Linux."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ONDA_ROOT = ROOT.parent / "onda"
HEADER = "workload\tengine\tns_per_frame\tmad\tmax_abs\trel_rms\tworst_channel_rel_rms\tfinite\tref_rms\n"


def command(*argv, **kwargs):
    return subprocess.run(argv, text=True, check=True, **kwargs)


def defaults(metadata):
    storage = bytearray(max(1, metadata["runtime"]["param_size_bytes"]))
    formats = {"f32": "f", "f64": "d", "i32": "i", "i64": "q", "bool": "?"}
    for param in metadata["metadata"]["params"]:
        kind = param["scalar"]
        for index, value in enumerate(param["default_reprs"] or []):
            offset = param["byte_offset"] + index * param["element_size_bytes"]
            number = (value == "true") if kind == "bool" else (float(value) if kind[0] == "f" else int(value))
            struct.pack_into("=" + formats[kind], storage, offset, number)
    return ",".join(map(str, storage))


def port_count(metadata, direction):
    count = 0
    for port in metadata["metadata"][direction]:
        if port["scalar"] != "f32" or port["slot_offset"] != count:
            raise ValueError(f"expected contiguous f32 audio ports in {direction}")
        count += port["array_len"]
    if count > 16:
        raise ValueError(f"too many {direction}")
    return count


def fixed_rate_libraries(original, target):
    target.mkdir()
    for src in original.glob("*.lib"):
        if src.name != "platform.lib":
            (target / src.name).write_bytes(src.read_bytes())
    platform = (original / "platform.lib").read_text()
    fixed, count = re.subn(r"^SR\s*=.*?;", "SR = 48000.0;", platform, flags=re.MULTILINE)
    if count != 1:
        raise ValueError("expected one SR definition in platform.lib")
    (target / "platform.lib").write_text(fixed)


def build(args, name, fixed_libs):
    build_dir = args.out / name
    build_dir.mkdir()
    log = (build_dir / "build.log").open("w")

    def run(*argv):
        log.write(shlex.join(map(str, argv)) + "\n")
        log.flush()
        command(*argv, cwd=build_dir, stdout=log, stderr=log)

    dsp_path = args.upstream / "dsp" / f"{name}.dsp"
    onda_path = dsp_path.with_suffix(".onda")
    cxx = [args.cxx, "-std=c++17", "-march=native", "-I", args.faust_include, "-I", args.onda_include]
    declarations, registration, objects = [], [], []
    ports = None
    onda_variants = [("onda", onda_path)]
    block_path = onda_path.parent / "explicit_loops" / onda_path.name
    if block_path.is_file():
        onda_variants.append(("onda-block", block_path))
    onda_variants.extend(args.variants.get(name, []))
    for label, source in onda_variants:
        for fast in (False, True):
            engine = label + ("-fm" if fast else "")
            symbol = engine.replace("-", "_")
            options = [args.onda, "compile", source, "--target-cpu", "host", "-b", "256", "--sr", "48000"]
            if fast:
                options.append("--fast-math")
            run(*options, "--emit", "obj", "-o", "raw.o", "--meta-out", f"{engine}.json")
            if name in args.ir:
                run(*options, "--emit", "llvm-ir", "-o", f"{engine}.ll")
                run(*options, "--emit", "mir", "-o", f"{engine}.mir")
            metadata = json.loads((build_dir / f"{engine}.json").read_text())
            if metadata["abi_version"] != 7 or metadata["metadata"]["buffers"]:
                raise ValueError("expected Onda ABI 7 with no external buffers")
            shape = tuple(port_count(metadata, port) for port in ("inputs", "outputs"))
            if ports is not None and ports != shape:
                raise ValueError("Onda variants have different port counts")
            ports = shape
            exports = metadata["exports"]
            mapping = [f"{exports[key]}={symbol}_{key}" for key in ("init", "process")]
            obj = f"{engine}.o"
            run(args.objcopy, *(f"--redefine-sym={item}" for item in mapping), "raw.o", obj)
            # Keep event symbols from different objects separate even though this harness never calls them.
            run(args.objcopy, "--wildcard", "--localize-symbol=onda_event*", obj)
            objects.append(obj)
            for key in ("init", "process"):
                decltype = "decltype(onda_processor_init)" if key == "init" else "decltype(onda_process)"
                declarations.append(f'extern "C" {decltype} {symbol}_{key};')
            declarations.append(f"const unsigned char {symbol}_defaults[] = {{{defaults(metadata)}}};")
            rt = metadata["runtime"]
            registration.append(
                f'    engines.push_back(std::make_unique<OndaEngine>("{engine}", {symbol}_init, {symbol}_process, '
                f'{rt["state_size_bytes"]}, {rt["state_align_bytes"]}, {rt["param_align_bytes"]}, '
                f'{symbol}_defaults, sizeof({symbol}_defaults)));'
            )

    def add_cpp(engine, faust, libraries, options, flags, optional=False):
        symbol = engine.replace("-", "_")
        obj = f"{engine}.o"
        cpp = f"{engine}.cpp"
        header = f"{engine}.h"
        try:
            run(faust, "-I", libraries, dsp_path, *options, "-cn", symbol, "-o", header)
        except subprocess.CalledProcessError:
            if optional:
                print(f"{name}: {engine} rejected by Faust (see {log.name})", flush=True)
                return
            raise
        (build_dir / cpp).write_text(
            "#include <faust/dsp/dsp.h>\n#include <faust/gui/UI.h>\n#include <faust/gui/meta.h>\n"
            f'#include "{header}"\ndsp* make_{symbol}() {{ return new {symbol}(); }}\n'
        )
        run(*cxx, "-O3", *flags, "-c", cpp, "-o", obj)
        if name in args.ir:
            run(*cxx, "-O3", *flags, "-S", "-emit-llvm", cpp, "-o", f"{engine}.ll")
        objects.append(obj)
        declarations.append(f"dsp* make_{symbol}();")
        registration.append(
            f'    engines.push_back(std::make_unique<FaustEngine>("{engine}", '
            f'make_{symbol}(), input_count, output_count));'
        )

    strict_flags = ["-ffp-contract=off"]
    fast_flags = ["-ffast-math"]
    for suffix, libs in (("", args.faust_libraries), ("48", fixed_libs)):
        for mode, flags in (("scal", ["-scal"]), ("vec", ["-vec", "-vs", "32"])):
            cpp = ["-lang", "cpp", *flags]
            add_cpp(f"cpp{suffix}-{mode}", args.faust, libs, cpp, strict_flags)
            add_cpp(f"cpp{suffix}-{mode}-fm", args.faust, libs, cpp, fast_flags)
    if args.libmvec:
        add_cpp("cpp-vec-libmvec", args.faust, args.faust_libraries,
                ["-lang", "cpp", "-vec", "-vs", "32"], [*fast_flags, "-fveclib=libmvec"])
    if args.cert4:
        choices = args.upstream / "results" / "autotool" / f"{name}.txt"
        winner = re.search(r"^fcautotool: winner .*? -- (.*?)  \[", choices.read_text(), re.MULTILINE)
        for suffix, libs in (("", args.faust_libraries), ("48", fixed_libs)):
            add_cpp(f"ocpp{suffix}", args.cert4, libs, ["-lang", "ocpp"], strict_flags, optional=True)
            add_cpp(f"ocpp{suffix}-fm", args.cert4, libs, ["-lang", "ocpp"], fast_flags, optional=True)
            if winner:
                add_cpp(f"m5-pick{suffix}-fm", args.cert4, libs, shlex.split(winner[1]),
                        [*fast_flags, "-fbracket-depth=1024"], optional=True)

    (build_dir / "engines.inc").write_text("\n".join([
        f"constexpr int input_count = {ports[0]}, output_count = {ports[1]};",
        *declarations, "void add_engines(Engines& engines) {", *registration, "}", "",
    ]))
    run(*cxx, "-I", build_dir, "-O2", "-ffp-contract=off", HERE / "harness.cpp", *objects,
        args.libfaust, f"-Wl,-rpath,{args.libfaust.parent}", "-no-pie", "-lm", "-o", "bench")
    log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, default=ROOT, help="benchmark source checkout")
    parser.add_argument("--faust", type=Path, required=True)
    parser.add_argument("--libfaust", type=Path, required=True, help="shared libfaust with LLVM")
    parser.add_argument("--faust-include", type=Path, required=True, help="directory containing faust/")
    parser.add_argument("--faust-libraries", type=Path, required=True, help="directory containing stdfaust.lib")
    parser.add_argument("--cert4", type=Path)
    parser.add_argument("--onda", type=Path, default=ONDA_ROOT / "target" / "release" / "onda")
    parser.add_argument("--onda-include", type=Path, default=ONDA_ROOT / "include")
    parser.add_argument("--cxx", default="clang++")
    parser.add_argument("--objcopy", default="llvm-objcopy")
    parser.add_argument("--out", type=Path, required=True, help="new result directory")
    parser.add_argument("--rounds", type=int, default=21)
    parser.add_argument("--round-ms", type=int, default=40)
    parser.add_argument("--cpu", type=int, default=min(os.sched_getaffinity(0)))
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--ir", action="append", default=[], metavar="WORKLOAD")
    parser.add_argument("--libmvec", action="store_true")
    parser.add_argument("--flush-denormals", action="store_true", help="set FTZ/DAZ for every engine")
    parser.add_argument("--llvm-no-fast", action="store_true", help="Faust LLVM no-fast-math diagnostic run")
    parser.add_argument("--onda-variant", action="append", default=[], metavar="WORKLOAD:LABEL=PATH")
    parser.add_argument("workloads", nargs="*")
    args = parser.parse_args()
    for key in ("out", "upstream", "faust", "faust_libraries", "libfaust", "faust_include", "cert4", "onda",
                "onda_include"):
        if getattr(args, key):
            setattr(args, key, getattr(args, key).absolute())
    args.variants = {}
    for spec in args.onda_variant:
        name, _, tail = spec.partition(":")
        label, _, path = tail.partition("=")
        if (not name or not re.fullmatch(r"onda-[a-z][a-z0-9-]*", label)
                or label.endswith("-fm") or not Path(path).is_file()):
            parser.error(f"expected WORKLOAD:onda-LABEL=PATH, got {spec!r}")
        variants = args.variants.setdefault(name, [])
        automatic_block = args.upstream / "dsp" / "explicit_loops" / f"{name}.onda"
        if (label == "onda-block" and automatic_block.is_file()) or any(label == key for key, _ in variants):
            parser.error(f"duplicate Onda variant label for {name}: {label}")
        variants.append((label, Path(path).resolve()))
    if args.rounds < 1 or args.round_ms < 1 or args.jobs < 1 or args.cpu not in os.sched_getaffinity(0):
        parser.error("invalid round count, round duration, build jobs or CPU selection")
    names = args.workloads or sorted(path.stem for path in (args.upstream / "dsp").glob("*.onda"))
    args.out.mkdir(parents=True, exist_ok=False)
    fixed_libs = args.out / "sr48"
    fixed_rate_libraries(args.faust_libraries, fixed_libs)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for name, _ in zip(names, pool.map(lambda name: build(args, name, fixed_libs), names)):
            print(f"Built {name}", flush=True)
    env = os.environ.copy()
    env.pop("FAUST_DEBUG", None)
    env.pop("FAUST_OPT", None)
    if args.llvm_no_fast:
        env["FAUST_OPT"] = "FAUST_LLVM_NO_FM"
    env["BENCH_FLUSH_DENORMALS"] = "1" if args.flush_denormals else "0"
    with (args.out / "results.tsv").open("w", buffering=1) as results:
        results.write(HEADER)
        for name in names:
            print(f"Timing {name} on CPU {args.cpu}", flush=True)
            build_dir = args.out / name
            command("taskset", "-c", str(args.cpu), build_dir / "bench",
                    args.upstream / "dsp" / f"{name}.dsp", name, args.faust_libraries, fixed_libs,
                    str(args.rounds), str(args.round_ms), str(build_dir) if name in args.ir else "",
                    stdout=results, cwd=build_dir, env=env)


if __name__ == "__main__":
    main()
