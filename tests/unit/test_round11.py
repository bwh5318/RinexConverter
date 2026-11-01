"""Regression tests for review round 11 (2026-10-31, docs/DECISIONS.md "review round 11 fixes"):
Sonnet's two polish items."""

import copy
import unittest

from rinexcore import validate as V
from tests.independent.compare import compare_obs

from .test_obs_fixtures import F, hdr, lines
from .test_round2 import HEAD, TAIL
from .test_round3 import MIXED, convert


class SystemLossCounted(unittest.TestCase):
    """Sonnet 2: system-not-representable:<s> counts the system's satellite records; the
    checker took the claim's name only."""

    SRC = lines(MIXED, *HEAD[1:], hdr("G    2 C1C L1C", "SYS / # / OBS TYPES"),
                hdr("C    2 C2I L2I", "SYS / # / OBS TYPES"),
                hdr("G L1C", "SYS / PHASE SHIFT"), hdr("C L2I", "SYS / PHASE SHIFT"), *TAIL,
                "> 2026 10 01 00 00  0.0000000  0  3",
                "G05" + F("  22000000.105") + F(" 115000000.405"),
                "C11" + F("  23000000.105") + F(" 120000000.405"),
                "C12" + F("  23100000.105") + F(" 120100000.405"),
                "> 2026 10 01 00 00 30.0000000  0  2",
                "G05" + F("  22000100.105") + F(" 115000500.405"),
                "C11" + F("  23000100.105") + F(" 120000500.405"), width=None)

    def test_count_compared(self):
        self.assertEqual(V.errors(V.validate(self.SRC)), [])
        outs, rep = convert(self.SRC, "2.11", assume_phase_aligned=True)
        self.assertEqual(rep["losses"]["system-not-representable:C"]["count"], 3)
        self.assertEqual(compare_obs(self.SRC, outs[0].data, rep), [])
        for n in (2, 4):
            with self.subTest(forged=n):
                bad = copy.deepcopy(rep)
                bad["losses"]["system-not-representable:C"]["count"] = n
                self.assertTrue(compare_obs(self.SRC, outs[0].data, bad))


class CycleSlipEpochInCompactRinex1(unittest.TestCase):
    """Sonnet 1: after an event flag above 1, flag 6 included, RNX2CRX and CRX2RNX copy as
    many lines as the epoch line's count (rnx2crx.c put_event_data). A RINEX 2 flag-6 epoch
    has one record per satellite of ceil(types / 5) lines, so with more than 5 types (or more
    than 12 satellites, whose list continues) Compact RINEX 1.0 cannot hold it. Was:
    refused-corrupt on a valid file."""

    @staticmethod
    def src(ntypes):
        def fo(v, fl="  "):
            return ("%14.3f" % v if v is not None else " " * 14) + fl
        codes = ["C1C", "C2W", "C2X", "L1C", "L2W", "S1C"][:ntypes]      # distinct in RINEX 2 too
        rows = [("G01", [20000000.1, 20000100.2, 20000200.3, 100000.1, 100100.2, 45.0][:ntypes])]
        body = []
        for t in (" 0", "30"):
            body.append(f"> 2020 06 28 00 00 {t}.0000000  0  1")
            body += [sat + "".join(fo(x) for x in v) for sat, v in rows]
        body += ["> 2020 06 28 00 01  0.0000000  6  1", "G01" + fo(None) + fo(None, "1 ") + fo(None) * (ntypes - 2)]
        return lines(*HEAD, hdr(f"G {ntypes:4d} " + " ".join(codes), "SYS / # / OBS TYPES"),
                     hdr("G L1C", "SYS / PHASE SHIFT"), *TAIL[:-1],
                     hdr("", "END OF HEADER"), *body, width=None).replace(b"2026    10     1", b"2020     6    28")

    def test_written_plain(self):
        # round 11 refused it (was: CorruptError CRX.ENC.EPOCH); since round 13 the file is
        # written as plain RINEX 2 with a warning (the user's choice): test_round13.py
        from rinexconv.engine import Options, convert_data
        src = self.src(6)                    # 6 RINEX 2 types: two lines per record
        outs = convert_data(src, "x.rnx", Options("2.11", compression="none", crx=False))
        self.assertEqual(compare_obs(src, outs[0].data, outs[0].report.to_dict()), [])
        crx = convert_data(src, "x.rnx", Options("2.11", compression="none", crx=True))
        self.assertEqual(crx[0].data, outs[0].data)
        outs = convert_data(self.src(4), "x.rnx", Options("2.11", compression="none", crx=True))
        self.assertTrue(outs[0].data.startswith(b"1.0"))           # one line per record: fine


class SolRound11(unittest.TestCase):
    """Sol round 11, 2 and 3 and polish 1 and 2, each from the reviewer's reproduction."""

    def test_eop_duplicates(self):
        from tests.independent.compare import compare_nav
        from .test_validate import nav_v4, payload
        b = nav_v4("4.02")
        i = b.index("> EOP G01 LNAV")
        j = next(k for k in range(i + 1, len(b)) if b[k].startswith(">"))
        src = payload(b[:j] + b[i:j] + b[j:])           # the EOP record twice
        outs, rep = convert(src, "4.02", dedupe=True)
        self.assertEqual(outs[0].data.decode().count("> EOP G01 LNAV"), 1)
        self.assertEqual(rep["losses"]["nav-duplicate-removed"]["count"], 1)
        self.assertEqual(compare_nav(src, [o.data for o in outs], rep), [])     # was: EOP loss demanded
        out = outs[0].data.decode().split("\n")
        k = out.index("> EOP G01 LNAV")
        gone = "\n".join(out[:k] + out[k + 4:]).encode()                    # the unique record deleted
        self.assertTrue(compare_nav(src, [gone], rep))

    def test_repeated_identical_type_list(self):
        types = hdr("G    3 C1C L1C L1W", "SYS / # / OBS TYPES")
        src = lines(*HEAD, types, hdr("G L1C", "SYS / PHASE SHIFT"), hdr("G L1W", "SYS / PHASE SHIFT"), *TAIL,
                    "> 2026 10 01 00 00  0.0000000  0  1",
                    "G05" + F("  22000000.105") + F(" 115000000.405") + F(" " * 14),
                    "> 2026 10 01 00 00 15.0000000  4  1", types,
                    "> 2026 10 01 00 00 30.0000000  0  1",
                    "G05" + F("  22000100.105") + F(" " * 14) + F(" 115000500.909"), width=None)
        self.assertEqual(V.errors(V.validate(src)), [])
        outs, rep = convert(src, "2.11")
        self.assertEqual(rep["losses"]["obs-code-collapsed:G:L1W"]["count"], 1)
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])          # was: no collision found

    def test_factor_2_lli_6(self):
        src = lines(
            hdr("     2.11           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"),
            hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
            hdr("TEST", "MARKER NAME"), hdr("     2     2", "WAVELENGTH FACT L1/2"),
            hdr("     2    C1    L1", "# / TYPES OF OBSERV"),
            hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
            hdr("", "END OF HEADER"),
            " 26 10  1  0  0  0.0000000  0  1G05", F("  22000000.105") + F(" 115000000.405", "6"))
        outs, rep = convert(src, "3.05", assume_phase_aligned=True)
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])          # was: '0' expected, ' ' written

    def test_same_version_duplicate_flag_only_column(self):
        from tests.independent.allowed import check as allowed_check
        src = lines(*HEAD, hdr("G    3 C1C L1C L1C", "SYS / # / OBS TYPES"), hdr("G L1C", "SYS / PHASE SHIFT"),
                    *TAIL, "> 2026 10 01 00 00  0.0000000  0  1",
                    "G05" + F("  22000000.105") + F(" 115000000.405") + F(" " * 14, "1"), width=None)
        outs, rep = convert(src, "3.05")
        self.assertNotIn("obs-code-collapsed:G:L1C", rep["losses"])        # was: a same-version loss
        self.assertIn("OBS.DUPLICATE-CODE-KEPT", [w["rule"] for w in rep["warnings"]])
        self.assertEqual(allowed_check(rep), [])
        self.assertEqual(compare_obs(src, outs[0].data, rep), [])


class WrapperLegWithDroppedFlags(unittest.TestCase):
    """Sol round 11, 1: the corpus harness skipped the Compact RINEX leg's content check when
    the leg claimed flags-on-missing-value-dropped, so a changed value passed."""

    def test_tampered_value_caught(self):
        import os
        import sys
        from rinexconv.engine import Options, convert_loaded, load_bytes
        from rinexcore.io import compress, hatanaka
        from rinexcore.rinexfile import open_container
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
        import corpus_run as CR
        from .test_round9 import FlagOnlyFields
        src = FlagOnlyFields.SRC                      # a flag-only L1C: dropped in CRINEX 1.0
        ld = load_bytes(src)
        plain = [o.data for o in convert_loaded(ld, "x.rnx", Options(
            "2.11", assume_phase_aligned=True, crx=False, compression="none"))]
        self.assertEqual(CR._wrapper_leg(ld, "x.rnx", "obs", "2.11", plain, [], with_z=False), [])
        real = CR.convert_loaded

        def tampered(*a, **k):
            outs = real(*a, **k)
            for o in outs:
                if o.report.losses.get("flags-on-missing-value-dropped"):
                    rnx = open_container(o.data).payload.replace(b"22000000.105", b"22000999.105")
                    o.data = compress.gzip_bytes(hatanaka.rnx_to_crx(rnx))
            return outs
        CR.convert_loaded = tampered
        try:
            probs = CR._wrapper_leg(ld, "x.rnx", "obs", "2.11", plain, [], with_z=False)
        finally:
            CR.convert_loaded = real
        self.assertTrue(probs)                        # was: [] (the leg was skipped)


if __name__ == "__main__":
    unittest.main()
