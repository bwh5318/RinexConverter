"""Generated files (tests/independent/generate.py), each converted to every version, plain
and Compact RINEX, and checked independently: the output validates, compare_obs finds no
unclaimed change, the loss table allows every claim, the Compact RINEX decodes to the plain
output's values (or the file is written plain with its warning), and CRX2RNX agrees when it
is present (dev-only oracle: CLAUDE.md rule 2). A conversion may refuse only with a named
RinexError.

RINEX_GEN_SEEDS (default 30) sets the number of seeds; RINEX_GEN_FIRST the first one.
"""

import glob
import os
import random
import re
import subprocess
import tempfile
import traceback
import unittest

from rinexconv.engine import Options, convert_data
from rinexcore import validate as V
from rinexcore.errors import NotRepresentableError, RinexError
from rinexcore.rinexfile import open_container
from tests.independent import codes as _codes
from tests.independent.allowed import check as allowed_check
from tests.independent.allowed import TABLE, code_not_representable
from tests.independent.headers import _nav_systems
from tests.independent.compare import compare_met, compare_nav, compare_obs
from tests.independent.tokens import lines_of, obs_tokens
from tests.independent.generate import (DAMAGE_RULES, FCN_TABLE, MET_211, VERSIONS, ObsGen, met_file,
                                        nav_cut)

from .test_hatanaka import find_crx2rnx

FIRST = int(os.environ.get("RINEX_GEN_FIRST", "0"))
SEEDS = int(os.environ.get("RINEX_GEN_SEEDS", "30"))
PLAIN_RULES = ("OBS.CRX1.EVENT-PLAIN", "OBS.CRX.EVENT-PLAIN", "OBS.CRX.PICOSEC-PLAIN")


def crx_layout(b):
    """CRX2RNX prints '.097' for '0.097' and '-.097' for '-0.097' (docs/HATANAKA.md
    section 9): values, not this formatting, survive a Hatanaka round trip."""
    return re.sub(rb"(?<= )0\.(?=\d)", b" .", b).replace(b" -0.", b"  -.")


def nothing_representable(src, target):
    """Independently of the converter: does no system, or no observation type, of `src`
    exist in `target`? Types are those of the file's type lists (header and flag 4) for the
    systems with data; across layouts (RINEX 2 <-> 3/4) only columns that hold something
    count, as a list is rebuilt from them (compare_obs)."""
    rin, cin = obs_tokens(lines_of(src))
    sv = re.match(rb" *(\d+(?:\.\d*)?)", src[:9]).group(1).decode()
    sv = "%.2f" % float(sv)
    data_sys = {s for s, n in cin.records.items() if n}
    if not data_sys & set(_codes.systems(target)):
        return True
    same_layout = (sv < "3") == (target < "3")
    for k, lst in enumerate(cin.lists):
        for s in data_sys:
            if s not in _codes.systems(target):
                continue
            for c in lst.get(s, lst.get("*", [])):
                if not (same_layout or cin.by_state[(k, s, c)] or cin.flags_by_state[(k, s, c)]):
                    continue
                if not code_not_representable(sv, target, s, c):
                    return False
    return True


def check_one(src, target, fcn, exe, repaired=False):
    """Problems of one conversion (an empty list when it is clean), or None if refused, as
    it may be only when the target can hold no system or no type of the file
    (nothing_representable; Sol round 23: any refusal passed).
    repaired: the input's header counts are wrong on purpose, so HDR.COUNTS must be reported."""
    kw = dict(compression="none", assume_phase_aligned=True, glo_fcn=fcn)
    try:
        outs = convert_data(src, "x.rnx", Options(target, **kw))
    except RinexError as e:
        if isinstance(e, NotRepresentableError) and nothing_representable(src, target):
            return None
        return [f"refused: {type(e).__name__}: {e}"]
    rep = outs[0].report.to_dict()
    p = [f"output invalid: {e}" for e in V.errors(V.validate(outs[0].data))[:3]]
    if repaired and "HDR.COUNTS" not in [r["rule"] for r in rep["repairs"]]:
        p.append("wrong input counts without an HDR.COUNTS repair")
    p += compare_obs(src, outs[0].data, rep)
    p += [f"loss not allowed: {x}" for x in allowed_check(rep)]
    if p:
        return p
    o = convert_data(src, "x.rnx", Options(target, crx=True, **kw))[0]
    back = open_container(o.data).payload
    if not o.report.output.get("crx"):
        if not any(w["rule"] in PLAIN_RULES for w in o.report.warnings):
            return ["crx: written plain without the warning"]
        return [] if back == outs[0].data else ["crx: the plain fallback differs from the plain output"]
    if o.report.losses.get("flags-on-missing-value-dropped"):
        p += ["crx: " + x for x in compare_obs(src, back, o.report.to_dict())]
    elif crx_layout(back) != crx_layout(outs[0].data):
        p.append("crx: decodes to other values than the plain output")
    if exe:
        r = subprocess.run([exe, "-"], input=o.data, capture_output=True, timeout=120)
        if r.returncode != 0 or r.stdout.replace(b"\r\n", b"\n") != back:
            p.append(f"crx: CRX2RNX disagrees with our decoder (exit {r.returncode})")
    return p


class GeneratedFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.fcn = os.path.join(cls.tmp, "fcn.txt")
        with open(cls.fcn, "wb") as fh:
            fh.write(FCN_TABLE.encode("ascii"))
        cls.exe = find_crx2rnx()

    def test_every_version(self):
        for seed in range(FIRST, FIRST + SEEDS):
            g = ObsGen(seed)
            src = g.data()
            with self.subTest(seed=seed, version=g.v, what="generated input"):
                errs = V.errors(V.validate(src))
                self.assertEqual([str(e) for e in errs if not (g.damaged and e.rule in DAMAGE_RULES)], [])
            for t in VERSIONS:
                with self.subTest(seed=seed, source=g.v, target=t):
                    try:
                        p = check_one(src, t, self.fcn, self.exe, repaired=g.damaged)
                    except Exception:                         # PLAN section 1 clause 1
                        p = ["raised: " + traceback.format_exc()[-600:]]
                    self.assertFalse(p, p)


class GeneratedMetFiles(unittest.TestCase):
    """met_file seeds to every version: valid output, compare_met, the loss table; a
    refusal only where no type of the file exists in the target (WD WS RI HI from 2.11)."""

    def test_every_version(self):
        for seed in range(FIRST, FIRST + SEEDS * 3):
            v, src = met_file(seed)
            with self.subTest(seed=seed, version=v, what="generated input"):
                self.assertEqual([str(e) for e in V.errors(V.validate(src))], [])
            types = [x.decode() for line in src.split(b"\n") if line[60:79] == b"# / TYPES OF OBSERV"
                     for x in line[6:60].split()]
            for t in VERSIONS:
                with self.subTest(seed=seed, source=v, target=t):
                    try:
                        outs = convert_data(src, "test1800.26m", Options(t, compression="none"))
                    except NotRepresentableError:
                        self.assertTrue(t < "2.11" and all(x in MET_211 for x in types))
                        continue
                    rep = outs[0].report.to_dict()
                    p = [str(e) for e in V.errors(V.validate(outs[0].data))]
                    p += compare_met(src, outs[0].data, rep)
                    p += [f"loss not allowed: {x}" for x in allowed_check(rep)]
                    self.assertFalse(p, p)


def nav_systems(payload):
    """Systems of a nav file's records, from the text: RINEX 3/4 the satellite letter that
    starts each record; RINEX 2 the file type (rinex211.txt: N GPS, G GLONASS, H SBAS;
    the 2.12 draft and real files: L Galileo)."""
    if float(payload[:9]) >= 3:
        return _nav_systems(payload)
    return {{"N": "G", "G": "R", "H": "S", "L": "E"}.get(chr(payload[20]), "?")}


# the message type of a RINEX 2/3 ephemeris (they have one form per system: rinex305.txt
# Tables A6-A14); RINEX 4 names it on the '> EPH' line (rinex_4.02.txt section 5.4)
_V3_MESSAGE = {"G": "LNAV", "R": "FDMA", "E": "INAV", "C": "D1", "J": "LNAV", "I": "LNAV", "S": "SBAS"}
# "only LNAV, FDMA, INAV/FNAV, D1/D2, SBAS have RINEX 3 forms" (allowed_losses.json, PLAN
# section 3.5); GLONASS L1OC/L3OC and NavIC L1NV only from 4.02 (rinex_4.02.txt section 5.4.4)
_V3_FORMS = {"LNAV", "FDMA", "INAV", "FNAV", "D1", "D2", "SBAS"}
_V402_ONLY = {("R", "L1OC"), ("R", "L3OC"), ("I", "L1NV")}


def nav_messages(payload):
    """(system, message type) of each ephemeris of a nav file, read from the text."""
    if float(payload[:9]) >= 4:
        text = payload.decode("latin-1").split("END OF HEADER", 1)[-1]
        out = set()
        for line in text.split("\n"):
            f = line.split()
            if len(f) >= 4 and f[0] == ">" and f[1] == "EPH":
                out.add((f[2][0], f[3]))
        return out
    return {(s, _V3_MESSAGE.get(s, "?")) for s in nav_systems(payload)}


def nav_holds(target, system, message):
    """Can a target's navigation files hold an ephemeris of this system and message type?"""
    if system not in nav_target_systems(target):
        return False
    if target >= "4":
        return target >= "4.02" or (system, message) not in _V402_ONLY
    return message in _V3_FORMS


def nav_target_systems(target):
    """The systems a target's navigation files hold (allowed_losses.json, cited there)."""
    if target < "3":
        return set(TABLE["nav_v2_systems"]["systems"])
    return set(TABLE["nav_systems"][target])


CORPUS_NAV = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "data", "corpus", "nav")


@unittest.skipUnless(os.path.isdir(CORPUS_NAV), "data/corpus (gitignored) is not here")
class NavCutFromCorpus(unittest.TestCase):
    """The three smallest corpus nav files of each version, cut into random record subsets
    with header corrections dropped at random, sometimes --merge'd with another (and
    --dedupe), to every version: compare_nav and the loss table (the engine validates its
    own output). A cut the validator rejects (a mandatory record dropped) is skipped; a
    refusal must be a NotRepresentableError naming what the target cannot hold."""

    @classmethod
    def setUpClass(cls):
        cls.tpl = []
        for d in sorted(glob.glob(os.path.join(CORPUS_NAV, "v*"))):
            for f in sorted(glob.glob(os.path.join(d, "*")), key=os.path.getsize)[:3]:
                with open(f, "rb") as fh:
                    cls.tpl.append((os.path.basename(f), open_container(fh.read()).payload))
        cls.tmp = tempfile.mkdtemp()

    def test_every_version(self):
        for seed in range(FIRST, FIRST + SEEDS):
            rng = random.Random(seed)
            name, payload = rng.choice(self.tpl)
            src = nav_cut(rng, payload)
            if V.errors(V.validate(src)):
                continue
            merge = []
            if rng.random() < 0.25:
                n2, p2 = rng.choice(self.tpl)
                other = nav_cut(rng, p2)
                if not V.errors(V.validate(other)):
                    path = os.path.join(self.tmp, f"m{seed}_{n2}")
                    with open(path, "wb") as fh:
                        fh.write(other)
                    merge = [(path, other)]
            dedupe = bool(merge) and rng.random() < 0.5
            for t in VERSIONS:
                with self.subTest(seed=seed, file=name, target=t, merge=bool(merge)):
                    try:
                        outs = convert_data(src, name, Options(t, compression="none",
                                                               merge=[p for p, _ in merge], dedupe=dedupe))
                    except NotRepresentableError:
                        # only if no ephemeris of any input (merged ones too) has a form in the
                        # target: its system and message type (Sol round 24: any such refusal
                        # passed; Sonnet round 25: GPS CNAV is no RINEX 2 record)
                        have = set().union(*(nav_messages(d) for d in [src] + [d for _, d in merge]))
                        self.assertFalse([x for x in have if nav_holds(t, *x)], (sorted(have), t))
                        continue
                    rep = outs[0].report.to_dict()
                    p = compare_nav(src, [o.data for o in outs], rep,
                                    merged=[d for _, d in merge] if merge else None)
                    p += [f"loss not allowed: {x}" for x in allowed_check(rep)]
                    self.assertFalse(p, p)


if __name__ == "__main__":
    unittest.main()
