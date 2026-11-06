"""The nav and met readers' and writers' speed paths (2026-11-03: per-file memos of checked
fields and epochs, the fmt_token fast path, memoised formatting) give what the plain code
gives: the same tokens, the same refusal at the same line and column when a bad text repeats,
the same blank-line notes, the same formatted fields for canonical and unusual exponents."""

import unittest

from rinexcore.errors import CorruptError
from rinexcore.met import read_met, write_met
from rinexcore.nav import NavFile, NavRecord, fmt_token, read_nav, write_nav
from rinexcore.rinexfile import sniff


def hdr(content, label):
    return content.ljust(60) + label


def f19(*toks):
    return "".join(t.rjust(19) for t in toks)


V3_HEAD = [hdr("     3.05           N: GNSS NAV DATA    G: GPS", "RINEX VERSION / TYPE"),
           hdr("", "END OF HEADER")]
V2_HEAD = [hdr("     2.11           N: GPS NAV DATA", "RINEX VERSION / TYPE"),
           hdr("", "END OF HEADER")]
V4_HEAD = [hdr("     4.02           N: GNSS NAV DATA    M: MIXED", "RINEX VERSION / TYPE"),
           hdr("", "END OF HEADER")]
Z = "0.000000000000E+00"
A = "1.234567890123E-04"


def v3_record(sat="G01", epoch="2026 01 01 00 00 00", lines=7, tok=A):
    return [f"{sat} {epoch}" + f19(tok, Z, Z)] + ["    " + f19(Z, tok, Z, tok)] * lines


def read(lines):
    return read_nav(lines, sniff(lines))


class NavReaderMemo(unittest.TestCase):
    def test_repeated_fields_and_epochs(self):
        f = read(V3_HEAD + v3_record("G01") + v3_record("G02"))
        self.assertEqual([r.sat for r in f.records], ["G01", "G02"])
        self.assertEqual(f.records[0].vals, [A, Z, Z] + [Z, A, Z, A] * 7)
        self.assertEqual(f.records[0].vals, f.records[1].vals)
        self.assertEqual(f.records[0].time, f.records[1].time)
        self.assertEqual([r.lineno for r in f.records], [3, 11])

    def test_bad_field_refused_where_it_first_is(self):
        bad = "1.2.3E+00"
        lines = V3_HEAD + v3_record("G01") + v3_record("G02", tok=bad)
        with self.assertRaises(CorruptError) as e:
            read(lines)
        # first line of G02 (line 11), field 1 starting in column 24
        self.assertEqual((e.exception.line, e.exception.column, e.exception.rule), (11, 24, "NAV.NUMBER"))
        lines = V3_HEAD + v3_record("G01") + ["G02 2026 01 01 00 00 00" + f19(A, Z, Z),
                                              "    " + f19(Z, bad, Z, bad), "    " + f19(bad)]
        with self.assertRaises(CorruptError) as e:
            read(lines)
        self.assertEqual((e.exception.line, e.exception.column), (12, 24))

    def test_bad_epoch_refused_each_time(self):
        lines = V3_HEAD + v3_record("G01") + v3_record("G02", epoch="2026 02 30 00 00 00")
        with self.assertRaises(CorruptError) as e:
            read(lines)
        self.assertEqual((e.exception.line, e.exception.rule), (11, "NAV.EPOCH"))

    def test_v2_and_v4_columns(self):
        v2 = V2_HEAD + [" 1 26  1  1  0  0  0.0" + f19(A, Z, Z), "   " + f19(Z, A, Z, "x")]
        with self.assertRaises(CorruptError) as e:
            read(v2)
        self.assertEqual((e.exception.line, e.exception.column), (4, 61))
        v4 = V4_HEAD + ["> EPH G01 LNAV", "G01 2026 01 01 00 00 00" + f19(A, Z, Z),
                        "    " + f19(Z, A, Z, A), "> EPH G01 LNAV", "G01 2026 01 01 02 00 00" + f19(A, Z, Z),
                        "    " + f19(Z, "1.0Q+00")]
        with self.assertRaises(CorruptError) as e:
            read(v4)
        self.assertEqual((e.exception.line, e.exception.column), (8, 24))

    def test_short_continuation_lines(self):
        f = read(V3_HEAD + ["G01 2026 01 01 00 00 00" + f19(A, Z, Z), "    " + f19(Z, A)])
        self.assertEqual(f.records[0].vals, [A, Z, Z, Z, A, "", ""])

    def test_blank_line_notes(self):
        # inside the data: a note; whitespace that str.strip() removes ('\t', '\xa0') is blank
        f = read(V3_HEAD + v3_record("G01") + ["\t\xa0 "] + v3_record("G02"))
        self.assertEqual([(n["rule"], n["line"]) for n in f.notes], [("NAV.BLANKLINE", 11)])
        # after the last record: none
        f = read(V3_HEAD + v3_record("G01") + ["", "  "])
        self.assertEqual(f.notes, [])
        f = read(V4_HEAD + ["> EPH G01 LNAV", "G01 2026 01 01 00 00 00" + f19(A, Z, Z), "",
                            "> EPH G02 LNAV", "G02 2026 01 01 00 00 00" + f19(A, Z, Z), ""])
        self.assertEqual([n["line"] for n in f.notes], [5])


class FmtToken(unittest.TestCase):
    def test_canonical_and_unusual_exponents(self):
        cases = {"-1.234567890123D-04": "-1.234567890123E-04", ".1676D-07": ".1676E-07",
                 "1.0D+5": "1.0E+05", "1.0e05": "1.0E+05", "1.0D+005": "1.0E+05", "1.0D+123": "1.0E+123",
                 "1.0D-0": "1.0E-00", "1.0D+-5": "1.0E+05", "1.0d+05": "1.0E+05", "1": "1", "1.0D": "1.0E+00"}
        for tok, want in cases.items():
            self.assertEqual(fmt_token(tok, "E"), want.rjust(19), tok)
            self.assertEqual(fmt_token(tok, "D"), want.replace("E", "D").rjust(19), tok)
        self.assertEqual(fmt_token("", "D"), " " * 19)
        with self.assertRaises(OverflowError):
            fmt_token("-1.2345678901234567E-04", "E")


class WriteNavMemo(unittest.TestCase):
    def nav(self, recs):
        f = NavFile()
        f.version = "4.02"
        f.ftype = "N"
        f.records = recs
        return f

    def test_overflow_raised_at_every_use(self):
        long = "-1.2345678901234567E-04"
        t = (2026, 1, 1, 0, 0, 0)
        # GPS LNAV: 3 + 6 x 4 + 2 fields (rinex_4.02.txt Table A9)
        recs = [NavRecord("EPH", "G01", "LNAV", "", t, [A, Z, Z] + [Z] * 24 + [A, Z]),
                NavRecord("EPH", "G02", "LNAV", "", t, [A, long, Z] + [Z] * 24 + [A, Z])]
        lines = write_nav(self.nav(recs[:1]), "4.02")
        self.assertEqual(lines[2], "G01 2026 01 01 00 00 00" + f19(A, Z, Z))
        for _ in range(2):
            with self.assertRaises(OverflowError):
                write_nav(self.nav(recs + recs), "4.02")

    def test_sto_record(self):
        t = (2026, 1, 1, 0, 0, 0)
        sto = NavRecord("STO", "G01", "LNAV", "", t, ["", "", "", Z, A, "1.0D-5", ""], " GPUT")
        lines = write_nav(self.nav([sto, sto]), "4.02")
        self.assertEqual(lines[1:], ["> STO G01 LNAV", "    2026 01 01 00 00 00 GPUT",
                                     "    " + f19(Z, A, "1.0E-05")] * 2)


MET_HEAD = [hdr("     2.11           METEOROLOGICAL DATA", "RINEX VERSION / TYPE"),
            hdr("     3    PR    TD    HR", "# / TYPES OF OBSERV"),
            hdr("", "END OF HEADER")]


def met(lines):
    return read_met(lines, sniff(lines))


class MetReader(unittest.TestCase):
    def test_epoch_forms(self):
        f = met(MET_HEAD + [" 26  1  1  0  0 15  987.1   10.6   89.5",
                            " 26 1   1  0 0  15  987.1   10.6   89.5",      # left-justified fields
                            " 26\t1  1  0  0 15  987.1   10.6   89.5"])    # a tab: read as blank
        self.assertEqual([e.time[:5] for e in f.epochs], [(2026, 1, 1, 0, 0)] * 3)
        with self.assertRaises(CorruptError) as e:
            met(MET_HEAD + [" 26  1  1  0  0 15  987.1   10.6   89.5", " 26  1 x1  0  0 15  987.1"])
        self.assertEqual((e.exception.line, e.exception.column, e.exception.rule), (5, 8, "MET.EPOCH"))

    def test_repeated_values_and_bad_value(self):
        good = " 26  1  1  0  0 15  987.1   10.6   89.5"
        f = met(MET_HEAD + [good, good.replace(" 15 ", " 30 ")])
        self.assertEqual(f.epochs[0].vals, f.epochs[1].vals)
        with self.assertRaises(CorruptError) as e:
            met(MET_HEAD + [good, " 26  1  1  0  1 15  987.1   1x.6   89.5"])
        self.assertEqual((e.exception.line, e.exception.rule), (5, "MET.VALUE"))

    def test_blank_line_notes(self):
        good = " 26  1  1  0  0 15  987.1   10.6   89.5"
        f = met(MET_HEAD + [good, "", good])
        self.assertEqual([(n["rule"], n["line"]) for n in f.notes], [("MET.BLANKLINE", 5)])
        self.assertEqual(met(MET_HEAD + [good, "", " "]).notes, [])

    def test_write_repeated_values(self):
        f = met(MET_HEAD + [" 26  1  1  0  0 15  987.1   10.6   89.5", " 26  1  1  0  0 30  987.1          89.5"])
        self.assertEqual(write_met(f, "2.11")[-2:], [" 26  1  1  0  0 15  987.1   10.6   89.5",
                                                      " 26  1  1  0  0 30  987.1          89.5"])


if __name__ == "__main__":
    unittest.main()
