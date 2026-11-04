"""Command line: python -m rinexconv IN [IN ...] --to VERSION [options]

Exit codes (rinexcore/errors.py): 0 converted, 1 converted-with-removal,
2 invocation error, 3 refused-missing-information, 4 refused-corrupt, 5 I/O error,
6 refused-not-representable.
With several inputs the highest code wins.
"""

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from rinexcore.errors import EXIT_CODES, InvocationError, RinexError

from . import __version__
from .engine import WRITE_VERSIONS, Options, convert_data, output_locks, write_outputs

_ORDER = ["converted", "converted-with-removal", "refused-not-representable",
          "refused-missing-information", "refused-corrupt", "invocation-error", "io-error",
          "internal-error"]


def build_parser():
    ap = argparse.ArgumentParser(
        prog="python -m rinexconv",
        description="Convert RINEX observation, navigation and meteorological files between "
                    "versions 2.10-4.02 (reads 2.00-4.02; gzip, .Z, bzip2, one-file zip and "
                    "Hatanaka wrappers; tar archives, each RINEX member converted).")
    ap.add_argument("inputs", nargs="+", help="input files, directories or tar archives")
    ap.add_argument("--to", required=True, metavar="VERSION",
                    help=f"target version: {', '.join(WRITE_VERSIONS)}")
    ap.add_argument("--out", default=".", metavar="DIR", help="output directory (default: current)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--crx", dest="crx", action="store_true", default=None,
                   help="write observation files Hatanaka-compressed")
    g.add_argument("--no-crx", dest="crx", action="store_false", help="write plain observation files")
    c = ap.add_mutually_exclusive_group()
    c.add_argument("--gz", dest="compression", action="store_const", const="gz", help="gzip output")
    c.add_argument("--Z", dest="compression", action="store_const", const="Z", help=".Z output")
    c.add_argument("--no-compress", dest="compression", action="store_const", const="none")
    ap.set_defaults(compression="keep")
    m = ap.add_mutually_exclusive_group()
    m.add_argument("--lenient", action="store_true", help="repair data-level damage where possible")
    m.add_argument("--strict", action="store_true", help="refuse anything off spec")
    ap.add_argument("--nav", action="append", default=[], metavar="FILE",
                    help="companion navigation file (GLONASS frequency channels)")
    ap.add_argument("--no-auto-nav", dest="auto_nav", action="store_false",
                    help="do not look for a same-day GLONASS nav file next to the input")
    ap.add_argument("--glo-fcn", metavar="FILE",
                    help="GLONASS channels: a nav file, a RINEX >= 3.02 obs file, or 'R01 1' lines")
    ap.add_argument("--overrides", metavar="FILE",
                    help='JSON {"G:L2": "L2L", ...} observation-code overrides for RINEX 2 -> 3')
    ap.add_argument("--drop-unresolvable", action="store_true",
                    help="drop a system whose mandatory target values cannot be resolved")
    ap.add_argument("--assume-phase-aligned", action="store_true",
                    help="assert the source phases are aligned (needed for unknown alignment -> 4.x)")
    ap.add_argument("--align-phases", action="store_true",
                    help="assert the source phases are unaligned and apply the target table's shifts "
                         "(RINEX 3.02 Table A19, 3.03-3.05 Table A23), or for a 3.00 target undo the "
                         "shifts the source's SYS / PHASE SHIFT records applied; 3.00 and 3.02-3.05 "
                         "targets only")
    ap.add_argument("--dedupe", action="store_true", help="remove exact duplicate nav records")
    ap.add_argument("--merge", action="store_true",
                    help="merge all navigation inputs into one output")
    ap.add_argument("--keep-v2-nonstandard", action="store_true",
                    help="write BeiDou/QZSS/NavIC into RINEX 2.11 (non-standard, flagged)")
    ap.add_argument("--keep-lli-bit2", action="store_true",
                    help="carry LLI bit 2 even between versions where it means different things "
                         "(2.x anti-spoofing, 3.01+ BOC tracking)")
    ap.add_argument("--leap-seconds", type=int, metavar="N",
                    help="GPS-UTC leap seconds for RINEX 4 nav output when the source has none")
    ap.add_argument("--approx-position", type=float, nargs=3, metavar=("X", "Y", "Z"),
                    help="APPROX POSITION XYZ (WGS84, m) for RINEX 2 output when the input has none "
                         "(moving platforms)")
    ap.add_argument("--approx-position-zero", action="store_true",
                    help="write teqc's 0 0 0 placeholder for that APPROX POSITION XYZ instead "
                         "(reported; zeros are not a position)")
    ap.add_argument("--qzss-ion-area", choices=("WIDE", "JAPN"),
                    help="area of QZSS ionospheric sets whose source states none (RINEX 3 QZSA/QZSB, "
                         "4.02 records without WIDE/JAPN), written as the Region code of a 4.00/4.01 "
                         "target (otherwise blank, read as wide area: reported); a source's own area wins")
    ap.add_argument("--report",metavar="DIR", help="write a JSON conversion report per input here")
    ap.add_argument("--eol", choices=("lf", "crlf"), default="lf")
    ap.add_argument("--force", action="store_true", help="overwrite existing outputs")
    ap.add_argument("--jobs", type=int, default=1, help="parallel processes for batch mode")
    ap.add_argument("--version", action="version", version=f"rinexconv {__version__}")
    return ap


def expand(inputs):
    out = []
    for p in inputs:
        pp = Path(p)
        if pp.is_dir():
            out.extend(sorted(str(x) for x in pp.iterdir() if x.is_file()))
        else:
            out.append(str(pp))
    return out


def sibling_nav(path):
    """Same-day navigation files with GLONASS records next to an observation file
    (RINEX 2 'g' or mixed, RINEX 3/4 *_RN / *_MN), as GLONASS channel companions."""
    from rinexcore import names
    me = names.parse(names.strip_compression(os.path.basename(path)))
    if not me:
        return []
    if me["style"] == "short":
        yy = int(me["yy"])
        day = (1900 + yy if yy >= 80 else 2000 + yy, int(me["ddd"]))
    else:
        day = (int(me["y"]), int(me["ddd"]))
    out = []
    folder = os.path.dirname(os.path.abspath(path))
    try:
        listing = sorted(os.listdir(folder))
    except OSError:
        return []                          # an unreadable folder offers no companions
    for name in listing:
        p = names.parse(names.strip_compression(name))
        if not p:
            continue
        if p["style"] == "short":
            yy = int(p["yy"])
            d = (1900 + yy if yy >= 80 else 2000 + yy, int(p["ddd"]))
            ok = p["t"].lower() in ("g", "p")
        else:
            d = (int(p["y"]), int(p["ddd"]))
            ok = p["tt"].upper() in ("RN", "MN")
        if ok and d == day:
            out.append(os.path.join(folder, name))
    return out


def run_input(path, opts, out_dir, report_dir, force):
    """The results of one input path: one for a file, one per member for a tar archive."""
    from rinexcore.io import archive
    from rinexcore.rinexfile import read_path
    try:
        data = read_path(path)             # first: a missing input is an invocation error
    except InvocationError as e:
        return [(path, "invocation-error", str(e), [])]
    if archive.is_tar(data):
        return run_archive(path, data, opts, out_dir, report_dir, force)
    return [run_one(path, opts, out_dir, report_dir, force, data=data)]


def run_archive(path, data, opts, out_dir, report_dir, force):
    """Convert each RINEX member of the tar archive at `path` as if it had been given on the
    command line (the user's choice, 2026-11-01; rinexcore/io/archive.py). A member counts
    as RINEX when its content starts like a RINEX or Compact RINEX file or its name is a
    RINEX file name, so a damaged one is refused rather than passed over; other members,
    archives inside the archive and non-files are skipped and listed. Same-day GLONASS
    companions are looked for next to the archive, not inside it."""
    from rinexcore import names
    from rinexcore.io import archive
    results = []
    try:
        for full, base, member, why in archive.members(data):
            label = f"{path}:{full}"
            if member is not None and archive.is_tar(member):
                why = "an archive inside the archive"
            elif member is not None and not (archive.is_rinex(member)
                                             or names.parse(names.strip_compression(base))):
                why = "not a RINEX file"
            if why:
                results.append((label, "skipped", f"{label} ({why})", []))
                continue
            lab, outcome, msg, written = run_one(path, opts, out_dir, report_dir, force,
                                                 data=member, name=base, label=label)
            results.append((lab, outcome, f"{full}: {msg}", written))
    except RinexError as e:                # a damaged archive, after the members before it
        results.append((path, e.outcome, str(e), []))
    if all(r[1] == "skipped" for r in results):
        results.append((path, "invocation-error", f"{path}: the archive holds no RINEX file", []))
    return results


def run_one(path, opts, out_dir, report_dir, force, data=None, name=None, label=None):
    """Convert one input: the file at `path`, or `data` named `name`, a member of the archive
    at `path` (`label` names it in the results)."""
    from rinexcore.rinexfile import read_path
    label = label or path
    if data is None:
        try:
            data = read_path(path)         # first: a missing input is an invocation error
        except InvocationError as e:
            return label, "invocation-error", str(e), []
    name = name or os.path.basename(path)
    if not opts.nav and not opts.glo_fcn and getattr(opts, "auto_nav", True):
        import dataclasses
        opts = dataclasses.replace(opts, nav=sibling_nav(os.path.join(os.path.dirname(path), name)))
    try:
        outs = convert_data(data, name, opts)
    except RinexError as e:
        rep = getattr(e, "report", None)
        err = _write_report(rep, report_dir, name, force) if rep is not None and report_dir else None
        if err:
            return label, "io-error", f"{e}; and {err}", []
        return label, e.outcome, str(e), []
    except InvocationError as e:
        return label, "invocation-error", str(e), []
    except Exception as e:  # noqa: BLE001 - a bug: report it, keep the batch going
        return label, "internal-error", f"{type(e).__name__}: {e} (please report this file)", []
    rep = outs[0].report if outs else None
    # one transaction for the input: its outputs and its report are published under the locks
    # of both folders, so no other writer's outputs or report can come between them (round 36)
    try:
        locks = output_locks([out_dir] + ([report_dir] if rep is not None and report_dir else []))
        with locks:
            return _publish(label, outs, rep, path, name, out_dir, report_dir, force)
    except InvocationError as e:
        return label, "io-error", str(e), []


def _publish(label, outs, rep, path, name, out_dir, report_dir, force):
    if rep is not None and report_dir:
        err = _report_target(report_dir, name, force)[1]    # before any output is written
        if err:
            return label, "io-error", err, []
    try:
        written = [str(t) for t in write_outputs(outs, out_dir, force, inputs=[path])]
    except InvocationError as e:
        return label, "io-error", str(e), []
    err = _write_report(rep, report_dir, name, force) if rep is not None and report_dir else None
    if err:
        return label, "io-error", err, written
    summary = rep.summary() if rep is not None else ""
    return label, rep.outcome if rep else "converted", summary, written


def _report_target(report_dir, base, force):
    """(path, None) for <base>.report.json in report_dir, or (None, message). Like an output,
    an existing report is not overwritten without --force (round 32: two inputs or archive
    members with the same name kept only the last report)."""
    from .engine import safe_path
    d = Path(report_dir)
    try:
        d.mkdir(parents=True, exist_ok=True)
        target = safe_path(d, base + ".report.json", "report")
    except (OSError, InvocationError) as e:
        return None, f"the report could not be written: {e}"
    if target.exists() and not force:
        return None, f"the report {target} exists (use --force to overwrite)"
    return target, None


def _write_report(rep, report_dir, base, force=False):
    """Write the JSON report as <base>.report.json in report_dir, under the same name checks
    as outputs (engine.safe_path); a failure is returned as a message, so the input gets an
    io-error and the batch goes on (Sol round 30). It is written like an output
    (engine.write_outputs: reserved without --force, a temporary file renamed into place, under
    the folder lock), so two jobs writing the same report at once never mix their bytes (round
    35, Sol: two forced writes left invalid JSON) and without --force the second gets "exists"."""
    from .engine import Output
    target, err = _report_target(report_dir, base, force)
    if err:
        return err
    try:
        write_outputs([Output(target.name, rep.to_json().encode("utf-8"), None)], target.parent, force)
    except InvocationError as e:
        return f"the report could not be written: {e}"
    return None


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)
    try:
        overrides = {}
        if a.overrides:
            overrides = json.loads(Path(a.overrides).read_text(encoding="utf-8"))
        opts = Options(target=a.to, lenient=a.lenient, strict=a.strict, nav=a.nav, glo_fcn=a.glo_fcn,
                       overrides=overrides, drop_unresolvable=a.drop_unresolvable,
                       assume_phase_aligned=a.assume_phase_aligned, align_phases=a.align_phases,
                       dedupe=a.dedupe, crx=a.crx,
                       compression=a.compression, eol=a.eol,
                       keep_v2_nonstandard=a.keep_v2_nonstandard, keep_lli_bit2=a.keep_lli_bit2,
                       leap_seconds=a.leap_seconds, auto_nav=a.auto_nav,
                       approx_position=tuple(a.approx_position) if a.approx_position else None,
                       approx_position_zero=a.approx_position_zero, qzss_ion_area=a.qzss_ion_area)
        from .engine import check_options
        check_options(opts)
    except (InvocationError, OSError, ValueError) as e:
        print(f"rinexconv: {e}", file=sys.stderr)
        return EXIT_CODES["invocation-error"]
    paths = expand(a.inputs)
    if a.merge:
        tars = [p for p in paths if _is_tar_file(p)]
        if tars:
            print(f"rinexconv: --merge takes navigation files, not a tar archive ({tars[0]}): "
                  "unpack it first", file=sys.stderr)
            return EXIT_CODES["invocation-error"]
        opts.merge = paths[1:]
        paths = paths[:1]
    worst = "converted"
    if a.jobs > 1 and len(paths) > 1:
        with ProcessPoolExecutor(max_workers=a.jobs) as ex:
            futs = [ex.submit(run_input, p, opts, a.out, a.report, a.force) for p in paths]
            results = [r for f in futs for r in f.result()]
    else:
        results = [r for p in paths for r in run_input(p, opts, a.out, a.report, a.force)]
    for path, outcome, msg, written in results:
        print(f"{outcome}: {msg}" + (f" -> {', '.join(written)}" if written else ""), file=sys.stderr)
        if outcome != "skipped" and _ORDER.index(outcome) > _ORDER.index(worst):
            worst = outcome
    return EXIT_CODES[worst]


def _is_tar_file(path):
    from rinexcore.io import archive
    try:
        return archive.is_tar(Path(path).read_bytes())
    except OSError:
        return False                       # reported when it is read
