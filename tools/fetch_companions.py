"""Fetch same-day GLONASS navigation files the corpus harness needs as companions.

For each day: the merged CDDIS file data/daily/YYYY/brdc/brdcDDD0.YYg(.Z|.gz) if it
exists, else up to fifteen station files from data/daily/YYYY/DDD/YYg/.
Files go to data/companions/ (gitignored) exactly as served, with a sha256
list in data/companions/COMPANIONS.json.

    python tools/fetch_companions.py 2003-180 2010-180

Uses the Earthdata client in tools/build_corpus.py (credentials are sent only to
urs.earthdata.nasa.gov and never printed).
"""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_corpus as bc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "companions"


def fetch(rel, name):
    r = bc.get(bc.BASE + rel + name)
    if r.status_code != 200:
        raise RuntimeError(f"{rel}{name}: HTTP {r.status_code}")
    data = r.content
    if data[:15].lower().startswith((b"<!doctype", b"<html")):
        raise RuntimeError(f"{rel}{name}: got an HTML page (login problem?)")
    return data


def main(days):
    bc._creds = bc.load_credentials()
    OUT.mkdir(parents=True, exist_ok=True)
    index_path = OUT / "COMPANIONS.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    for day in days:
        y, doy = (int(x) for x in day.split("-"))
        yy = y % 100
        got = []
        brdc = bc.listdir(f"data/daily/{y}/brdc/")
        want = [n for n, _ in brdc if n.startswith(f"brdc{doy:03d}0.{yy:02d}g")]
        if want:
            names = [(f"data/daily/{y}/brdc/", want[0])]
        else:
            rel = f"data/daily/{y}/{doy:03d}/{yy:02d}g/"
            names = [(rel, n) for n, _ in bc.listdir(rel) if n.endswith(("g.Z", "g.gz"))][:15]
        for rel, n in names:
            data = fetch(rel, n)
            (OUT / n).write_bytes(data)
            index[n] = {"url": bc.BASE + rel + n, "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(), "day": day}
            got.append(n)
        print(f"{day}: {', '.join(got) if got else 'nothing found'}")
    index_path.write_text(json.dumps(index, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
