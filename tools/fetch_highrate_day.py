"""Fetch one station-day of CDDIS 1 Hz high-rate observations and splice it into one 24 h file.

CDDIS keeps high-rate data as 15-minute Hatanaka files (docs/CDDIS.md):
data/highrate/YYYY/DDD/YYd/HH/<SITE>_R_YYYYDDDHHMM_15M_01S_MO.crx.gz, 96 per day. This tool
downloads them, decodes each with rinexcore's Hatanaka decoder, checks that every file
declares the same observation types and that the epochs follow on, and writes one plain
RINEX 3/4 file holding the whole day: the first file's header with TIME OF LAST OBS set to
the last epoch and the optional per-file counts (# OF SATELLITES, PRN / # OF OBS) left out.

Dev-only: it feeds the 24 h memory and speed test (docs/DECISIONS.md). Nothing in it is
used by rinexconv.

    python tools/fetch_highrate_day.py MIZU00JPN 2026 290

Output, relative to the repository root:
    data/highrate/<SITE>_<YYYYDDD>/raw/*.crx.gz             the 96 files as CDDIS serves them
    data/highrate/<SITE>_<YYYYDDD>/<SITE>_R_<YYYYDDD>0000_01D_01S_MO.rnx
"""
import argparse
import sys
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_corpus as B  # noqa: E402

from rinexcore.io.hatanaka import crx_to_rnx  # noqa: E402

# header records that must be the same in every 15-minute file of the day
SAME = ("RINEX VERSION / TYPE", "SYS / # / OBS TYPES", "SYS / SCALE FACTOR", "SYS / PHASE SHIFT",
        "GLONASS COD/PHS/BIS", "OBS SCALE FACTOR")
DROP = ("# OF SATELLITES", "PRN / # OF OBS", "TIME OF LAST OBS")


def names(site, year, doy):
    out = []
    for hh in range(24):
        for mm in (0, 15, 30, 45):
            rel = f"data/highrate/{year}/{doy:03d}/{year % 100:02d}d/{hh:02d}/"
            out.append((rel, f"{site}_R_{year}{doy:03d}{hh:02d}{mm:02d}_15M_01S_MO.crx.gz"))
    return out


def fetch(rel, name, dest):
    p = dest / name
    if p.exists() and p.stat().st_size > 0:
        return p, "kept"
    for attempt in range(3):
        try:
            r = B.get(B.BASE + rel + name, timeout=300)
            if r.status_code == 404:
                return None, "missing"
            if r.status_code != 200 or b"<html" in r.content[:500].lower():
                raise RuntimeError(f"HTTP {r.status_code}")
            d = zlib.decompressobj(31)
            d.decompress(r.content)
            if not d.eof:
                raise RuntimeError("truncated gzip")
            tmp = p.with_suffix(".part")
            tmp.write_bytes(r.content)
            tmp.replace(p)
            return p, "fetched"
        except Exception as e:  # network trouble: retry, then report
            if attempt == 2:
                return None, f"error: {e}"
            time.sleep(5 * (attempt + 1))


def split(rnx):
    end = rnx.find(b"END OF HEADER")
    cut = rnx.index(b"\n", end) + 1
    return rnx[:cut].decode("latin-1").splitlines(), rnx[cut:]


def glonass_slots(head):
    """{sat: channel} of GLONASS SLOT / FRQ # (I3,1X,8(A3,1X,I2,1X), continuation 4X)."""
    out = {}
    for ln in head:
        if ln[60:].strip() == "GLONASS SLOT / FRQ #":
            for k in range(4, 60, 7):
                sat, ch = ln[k:k + 3].strip(), ln[k + 4:k + 6].strip()
                if sat:
                    out[sat] = int(ch)
    return out


def slot_records(slots):
    """GLONASS SLOT / FRQ # lines for {sat: channel}, 8 per line."""
    items = [f"{s} {c:2d} " for s, c in sorted(slots.items())]
    out = []
    for k in range(0, len(items), 8):
        lead = f"{len(items):3d} " if k == 0 else "    "
        out.append((lead + "".join(items[k:k + 8])).ljust(60) + "GLONASS SLOT / FRQ #")
    return out


def epoch_times(body):
    """(first, last) epoch time tuples of a RINEX 3/4 body."""
    first = last = None
    for ln in body.split(b"\n"):
        if ln[:1] == b">":
            t = ln[2:29].decode("latin-1").split()
            t = tuple(int(x) for x in t[:5]) + (Decimal(t[5]),)
            first = first or t
            last = t
    return first, last


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("site", help="9-character site ID, e.g. MIZU00JPN")
    ap.add_argument("year", type=int)
    ap.add_argument("doy", type=int)
    a = ap.parse_args()
    B._creds = B.load_credentials()
    out = B.ROOT / "data" / "highrate" / f"{a.site}_{a.year}{a.doy:03d}"
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    todo = names(a.site, a.year, a.doy)
    t0 = time.time()
    with ThreadPoolExecutor(B.WORKERS) as ex:
        got = list(ex.map(lambda x: fetch(x[0], x[1], raw), todo))
    bad = [(n, why) for (rel, n), (p, why) in zip(todo, got) if p is None]
    print(f"{len(todo) - len(bad)}/{len(todo)} files in {time.time() - t0:.0f} s", flush=True)
    for n, why in bad:
        print(f"  {n}: {why}")
    if bad:
        sys.exit("not a whole day: nothing spliced")

    dest = out / f"{a.site}_R_{a.year}{a.doy:03d}0000_01D_01S_MO.rnx"
    tmp = dest.with_suffix(".part")
    ref = None
    prev_last = None
    epochs = 0
    slots = {}                 # a 15-minute file lists only the GLONASS satellites it saw
    with open(tmp, "wb") as fh:
        for p, _ in got:
            rnx = crx_to_rnx(zlib.decompress(p.read_bytes(), 31))
            head, body = split(rnx)
            same = [ln for ln in head if ln[60:].strip() in SAME]
            first, last = epoch_times(body)
            if ref is None:
                ref = same
                tsys = next(ln[48:51] for ln in head if ln[60:].strip() == "TIME OF FIRST OBS")
                header = [ln for ln in head if ln[60:].strip() not in DROP]
            elif same != ref:
                diff = sorted(set(same) ^ set(ref))
                sys.exit(f"{p.name}: header differs from the first file's:\n  " + "\n  ".join(diff))
            for sat, ch in glonass_slots(head).items():
                if slots.setdefault(sat, ch) != ch:
                    sys.exit(f"{p.name}: GLONASS {sat} channel {ch}, earlier files say {slots[sat]}")
            if prev_last is not None and not first > prev_last:
                sys.exit(f"{p.name}: first epoch {first} does not follow {prev_last}")
            prev_last = last
            epochs += body.count(b"\n>") + body.startswith(b">")
            fh.write(body)               # spooled: the header needs the last epoch first
    y, mo, d, h, mi, s = prev_last
    lastrec = f"{y:6d}{mo:6d}{d:6d}{h:6d}{mi:6d}{s:13.7f}     {tsys}".ljust(60) + "TIME OF LAST OBS"
    at = next(i for i, ln in enumerate(header) if ln[60:].strip() == "TIME OF FIRST OBS") + 1
    header = header[:at] + [lastrec] + header[at:]
    if slots:
        at = next(i for i, ln in enumerate(header) if ln[60:].strip() == "GLONASS SLOT / FRQ #")
        header = ([ln for ln in header[:at]] + slot_records(slots)
                  + [ln for ln in header[at:] if ln[60:].strip() != "GLONASS SLOT / FRQ #"])
    with open(dest, "wb") as fh, open(tmp, "rb") as spool:
        fh.write(("\n".join(header) + "\n").encode("latin-1"))
        while chunk := spool.read(1 << 24):
            fh.write(chunk)
    tmp.unlink()
    print(f"{dest.relative_to(B.ROOT)}: {dest.stat().st_size / 1e6:.0f} MB, {epochs} epochs, "
          f"last {prev_last[3]:02d}:{prev_last[4]:02d}:{prev_last[5]}")


if __name__ == "__main__":
    main()
