"""Sanity tests for rinexcore.spec (observation codes and header labels).

Standard library unittest only. The tests read the spec text extractions in
specs/text/ and check the hand-transcribed tables against them:

- every observation code of a version and system is printed in the cited
  table, and the codes printed in that table are exactly the codes listed
  (apart from a few signal names that look like codes);
- the known version gates (BeiDou B1I, BDS-3, QZSS, NavIC L1, header records);
- every header label is printed at its cited page or line, and the table's
  optional marker (*) agrees with the transcribed status.

Run from the repository root:
    python -m unittest tests.unit.test_spec_tables -v
"""

import re
import unittest
from pathlib import Path

from rinexcore.spec import obscodes as oc
from rinexcore.spec import obsheader as oh

ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = ROOT / "specs" / "text"

V3V4 = oc.VERSIONS[2:]
TOKEN_V3 = re.compile(r"(?<![A-Za-z0-9])[CLDS][0-9][A-Z](?![A-Za-z0-9])")
TOKEN_V2 = re.compile(r"(?<![A-Za-z0-9])[CLDSPT][0-9](?![A-Za-z0-9])")

_LINES = {}


def spec_lines(name):
    """Lines of a spec text file (UTF-8 text extraction; read as bytes)."""
    if name not in _LINES:
        data = (SPEC_DIR / name).read_bytes()
        _LINES[name] = data.decode("utf-8", errors="replace").splitlines()
    return _LINES[name]


def line_range(name, first, last):
    return spec_lines(name)[first - 1:last]


def page_lines(name, page):
    """(line_number, text) pairs on one '===== page N =====' page."""
    out, current = [], None
    for number, text in enumerate(spec_lines(name), 1):
        m = re.match(r"===== page (\d+) =====", text)
        if m:
            current = int(m.group(1))
            continue
        if current == page:
            out.append((number, text))
    return out


def page_text(name, first, last=None):
    last = first if last is None else last
    return "\n".join(t for p in range(first, last + 1) for _, t in page_lines(name, p))


def has_token(text, code):
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(code) + r"(?![A-Za-z0-9])", text) is not None


def despace(text):
    return re.sub(r"\s+", "", text)


# Label column of a header table line: optional '*', optional '|', then a
# label-like fragment ended by '|', two spaces, a dash separator or end of line.
_LABEL_HEAD = re.compile(
    r"^\s*(?P<star>\*?)\s*\|?\s*(?P<frag>[A-Z#][^|]*?)\s*(?:\||\s{2,}|\s[−-]\s|$)")


def label_fragments(name, page):
    frags = []
    for number, text in page_lines(name, page):
        m = _LABEL_HEAD.match(text)
        if m:
            frags.append((number, m.group("star") == "*", m.group("frag")))
    return frags


def find_label_row(name, page, label):
    """Return (line_number, starred) for ``label`` on ``page``, or None.

    Handles labels wrapped over two or three table lines (3.02 Table A2).
    """
    want = despace(label)
    frags = label_fragments(name, page)
    for i, (number, starred, frag) in enumerate(frags):
        joined = ""
        for j in range(i, min(i + 3, len(frags))):
            if j > i and frags[j][0] != frags[j - 1][0] + 1:
                break
            joined += despace(frags[j][2])
            if joined == want:
                return number, starred
            if not want.startswith(joined):
                break
    return None


class TestObsCodeStructure(unittest.TestCase):

    def test_version_keys(self):
        self.assertEqual(tuple(oc.SYSTEMS), oc.VERSIONS)
        self.assertEqual(set(oc.OBS_CODES), set(oc.VERSIONS))
        self.assertEqual(set(oc.CITATIONS), set(oc.VERSIONS))
        self.assertEqual(set(oc.SOURCE_SPANS), set(oc.VERSIONS))
        self.assertEqual(set(oc.SIGNAL_ROWS), set(V3V4))
        self.assertEqual(set(oc.PSEUDO_OBS), set(V3V4))
        self.assertEqual(set(oc.BLANK_ATTRIBUTE), set(V3V4))

    def test_systems_match_code_tables(self):
        for ver in oc.VERSIONS:
            with self.subTest(ver=ver):
                self.assertEqual(set(oc.SYSTEMS[ver]), set(oc.OBS_CODES[ver]))
                self.assertEqual(set(oc.SYSTEMS[ver]), set(oc.CITATIONS[ver]))
                self.assertEqual(set(oc.SYSTEMS[ver]), set(oc.SOURCE_SPANS[ver]))
                self.assertNotIn("M", oc.SYSTEMS[ver])
                for system in oc.SYSTEMS[ver]:
                    self.assertTrue(oc.OBS_CODES[ver][system], (ver, system))

    def test_code_shapes(self):
        for ver in oc.VERSIONS:
            for system, codes in oc.OBS_CODES[ver].items():
                for code in codes:
                    with self.subTest(ver=ver, system=system, code=code):
                        if ver.startswith("2."):
                            self.assertRegex(code, r"^[CLDSPT][1-8]$")
                        else:
                            self.assertRegex(code, r"^[CLDS][1-9][A-Z]$")

    def test_rows_have_no_duplicates(self):
        for ver, by_sys in oc.SIGNAL_ROWS.items():
            for system, rows in by_sys.items():
                keys = [(band, attr) for band, attr, _types, _sig in rows]
                with self.subTest(ver=ver, system=system):
                    self.assertEqual(len(keys), len(set(keys)))
                    for band, attr, types, _sig in rows:
                        self.assertIn(types, ("CLDS", "LDS"))

    def test_codeless_rows_have_no_pseudorange(self):
        # Codeless rows print "--" (or nothing) in the pseudorange column.
        for ver in V3V4:
            with self.subTest(ver=ver):
                self.assertNotIn("C1N", oc.OBS_CODES[ver]["G"])
                self.assertNotIn("C2N", oc.OBS_CODES[ver]["G"])
                self.assertIn("L1N", oc.OBS_CODES[ver]["G"])
                self.assertIn("L2N", oc.OBS_CODES[ver]["G"])
        self.assertIn("L1N", oc.OBS_CODES["3.04"]["C"])
        self.assertNotIn("C1N", oc.OBS_CODES["3.04"]["C"])


class TestObsCodesAgainstSpecText(unittest.TestCase):

    def test_rinex3_4_table_spans_exact(self):
        """Codes printed in each system's table == codes transcribed."""
        for ver in V3V4:
            for system, span in oc.SOURCE_SPANS[ver].items():
                with self.subTest(ver=ver, system=system):
                    text = "\n".join(line_range(span["file"], *span["lines"]))
                    printed = set(TOKEN_V3.findall(text))
                    printed -= oc.SIGNAL_NAME_TOKENS.get(system, frozenset())
                    self.assertEqual(printed, set(oc.OBS_CODES[ver][system]))

    def test_rinex303_original_text_has_same_codes(self):
        for system, span in oc.ALT_SOURCE_SPANS["3.03"].items():
            with self.subTest(system=system):
                text = "\n".join(line_range(span["file"], *span["lines"]))
                printed = set(TOKEN_V3.findall(text))
                printed -= oc.SIGNAL_NAME_TOKENS.get(system, frozenset())
                self.assertEqual(printed, set(oc.OBS_CODES["3.03"][system]))

    def test_codes_on_cited_pages(self):
        """Every code is printed on the page range its citation gives."""
        for ver in V3V4:
            for system, span in oc.SOURCE_SPANS[ver].items():
                text = page_text(span["file"], *span["pages"])
                for code in oc.OBS_CODES[ver][system]:
                    with self.subTest(ver=ver, system=system, code=code):
                        self.assertTrue(has_token(text, code))
                with self.subTest(ver=ver, system=system, check="span inside pages"):
                    first, last = span["lines"]
                    lines_on_pages = {n for p in range(span["pages"][0], span["pages"][1] + 1)
                                      for n, _ in page_lines(span["file"], p)}
                    rows = [n for n in range(first, last + 1)
                            if TOKEN_V3.search(spec_lines(span["file"])[n - 1])]
                    self.assertTrue(rows)
                    self.assertTrue(set(rows) <= lines_on_pages)

    def test_every_code_literally_in_version_text(self):
        for ver in oc.VERSIONS:
            files = {span["file"] for span in oc.SOURCE_SPANS[ver].values()}
            if ver == "3.03":
                files.add("rinex303.txt")
            for name in files:
                whole = "\n".join(spec_lines(name))
                for system, codes in oc.OBS_CODES[ver].items():
                    for code in codes:
                        with self.subTest(ver=ver, file=name, code=code):
                            self.assertTrue(has_token(whole, code))

    def test_rinex2_codes(self):
        # 2.10: one global list (l.886-897); every per-system set is a subset.
        span = oc.SOURCE_SPANS["2.10"]["G"]
        printed = set(TOKEN_V2.findall("\n".join(line_range(span["file"], *span["lines"]))))
        self.assertEqual(printed, set(oc.V2_HEADER_CODES["2.10"]))
        union = set()
        for system, codes in oc.OBS_CODES["2.10"].items():
            self.assertTrue(codes <= oc.V2_HEADER_CODES["2.10"], system)
            union |= codes
        self.assertEqual(union, set(oc.V2_HEADER_CODES["2.10"]))
        # 2.11: per-system rows of the sec. 10.1.1 table.
        union = set()
        for system, span in oc.SOURCE_SPANS["2.11"].items():
            with self.subTest(system=system):
                text = "\n".join(line_range(span["file"], *span["lines"]))
                self.assertEqual(set(TOKEN_V2.findall(text)), set(oc.OBS_CODES["2.11"][system]))
                union |= oc.OBS_CODES["2.11"][system]
        self.assertEqual(union, set(oc.V2_HEADER_CODES["2.11"]))
        self.assertEqual(set(oc.INFERRED["2.10"]), set(oc.SYSTEMS["2.10"]))

    def test_system_letters_printed(self):
        for ver in V3V4:
            name = oh.SOURCE_FILES[ver]
            page = oh.LABEL_LOCATIONS[ver]["RINEX VERSION / TYPE"]
            text = page_text(name, page)
            for system in oc.SYSTEMS[ver]:
                if ver == "3.01" and system == "C":
                    continue        # Table A1 omits C; Table 1 has it (checked below)
                with self.subTest(ver=ver, system=system):
                    self.assertRegex(text, r"(?<![A-Za-z])" + system + r" ?:\s+[A-Z]")
        self.assertRegex(page_text("rinex301.txt", 8), r"C : Compass")
        self.assertNotRegex(page_text("rinex301.txt", 29), r"C: Compass")
        for ver, letters in (("2.10", "GRSTM"), ("2.11", "GRSEM")):
            name = oh.SOURCE_FILES[ver]
            first = oh.LABEL_LOCATIONS[ver]["RINEX VERSION / TYPE"]
            text = "\n".join(line_range(name, first, first + 8))
            for system in letters:
                with self.subTest(ver=ver, system=system):
                    self.assertIn(f"'{system}':", text)


class TestObsCodeGates(unittest.TestCase):

    def test_beidou_b1i(self):
        self.assertTrue(oc.is_valid("3.02", "C", "C1I"))
        self.assertFalse(oc.is_valid("3.02", "C", "C2I"))
        for ver in ("3.01",) + oc.VERSIONS[5:]:
            with self.subTest(ver=ver):
                self.assertTrue(oc.is_valid(ver, "C", "C2I"))
                self.assertFalse(oc.is_valid(ver, "C", "C1I"))
        self.assertEqual(oc.valid_codes("3.00", "C"), frozenset())

    def test_bds3_signals(self):
        bds3 = ("C1D", "C1P", "C5D", "C5P", "C5X", "C7D", "C7Z", "C8D", "C8X")
        for code in bds3:
            self.assertFalse(oc.is_valid("3.03", "C", code), code)
            for ver in oc.VERSIONS[6:]:
                self.assertTrue(oc.is_valid(ver, "C", code), (ver, code))
        # 3.04-only BDS codes, re-coded in 3.05.
        for code in ("C1A", "C6A", "L1N"):
            self.assertTrue(oc.is_valid("3.04", "C", code), code)
            for ver in oc.VERSIONS[7:]:
                self.assertFalse(oc.is_valid(ver, "C", code), (ver, code))
        for code in ("C1S", "C1L", "C1Z", "C6D", "C6P", "C6Z"):
            self.assertFalse(oc.is_valid("3.04", "C", code), code)
            for ver in oc.VERSIONS[7:]:
                self.assertTrue(oc.is_valid(ver, "C", code), (ver, code))

    def test_glonass(self):
        self.assertFalse(oc.is_valid("3.01", "R", "C3I"))
        self.assertTrue(oc.is_valid("3.02", "R", "C3I"))
        for code in ("C4A", "C4B", "C4X", "C6A", "C6B", "C6X"):
            self.assertFalse(oc.is_valid("3.03", "R", code), code)
            for ver in oc.VERSIONS[6:]:
                self.assertTrue(oc.is_valid(ver, "R", code), (ver, code))

    def test_qzss(self):
        self.assertNotIn("J", oc.SYSTEMS["3.01"])
        self.assertIn("J", oc.SYSTEMS["3.02"])
        self.assertFalse(oc.is_valid("3.03", "J", "C5D"))
        self.assertTrue(oc.is_valid("3.04", "J", "C5D"))
        self.assertTrue(oc.is_valid("3.04", "J", "C6E"))
        # L1Sb (1B): 3.05 to 4.01 only.
        for ver in oc.VERSIONS:
            expected = ver in ("3.05", "4.00", "4.01")
            if "J" in oc.SYSTEMS[ver]:
                self.assertEqual(oc.is_valid(ver, "J", "C1B"), expected, ver)
        # C/B (1E) from 4.00.
        self.assertFalse(oc.is_valid("3.05", "J", "C1E"))
        for ver in oc.VERSIONS[8:]:
            self.assertTrue(oc.is_valid(ver, "J", "C1E"), ver)

    def test_navic(self):
        self.assertNotIn("I", oc.SYSTEMS["3.02"])
        self.assertIn("I", oc.SYSTEMS["3.03"])
        self.assertTrue(oc.is_valid("3.03", "I", "C9A"))
        self.assertFalse(oc.is_valid("4.00", "I", "C1D"))
        self.assertTrue(oc.is_valid("4.01", "I", "C1D"))
        self.assertTrue(oc.is_valid("4.02", "I", "C1X"))

    def test_gps(self):
        self.assertFalse(oc.is_valid("3.00", "G", "C1L"))
        self.assertTrue(oc.is_valid("3.01", "G", "C1L"))
        self.assertFalse(oc.is_valid("4.00", "G", "C1R"))
        self.assertTrue(oc.is_valid("4.01", "G", "C1R"))
        self.assertTrue(oc.is_valid("4.02", "G", "L2R"))

    def test_rinex2(self):
        self.assertIn("T", oc.SYSTEMS["2.10"])
        self.assertNotIn("T", oc.SYSTEMS["2.11"])
        self.assertNotIn("E", oc.SYSTEMS["2.10"])
        self.assertIn("E", oc.SYSTEMS["2.11"])
        self.assertFalse(oc.is_valid("2.10", "G", "C2"))
        self.assertTrue(oc.is_valid("2.11", "G", "C2"))
        self.assertTrue(oc.is_valid("2.10", "T", "T1"))
        self.assertFalse(oc.is_valid("2.11", "E", "P1"))
        self.assertTrue(oc.is_valid("2.11", "E", "C8"))

    def test_galileo_and_sbas_unchanged(self):
        for ver in oc.VERSIONS[3:]:
            self.assertEqual(oc.OBS_CODES[ver]["E"], oc.OBS_CODES["3.00"]["E"], ver)
            self.assertEqual(oc.OBS_CODES[ver]["S"], oc.OBS_CODES["3.00"]["S"], ver)


class TestPseudoObservables(unittest.TestCase):

    def test_ionosphere_removed_in_305(self):
        for ver in ("3.00", "3.01", "3.02", "3.03", "3.04"):
            self.assertIn("I", oc.PSEUDO_OBS[ver], ver)
        for ver in oc.VERSIONS[7:]:
            self.assertNotIn("I", oc.PSEUDO_OBS[ver], ver)
            self.assertNotIn("I1 ", oc.pseudo_obs_codes(ver))
        self.assertIn("I9 ", oc.pseudo_obs_codes("3.04"))
        self.assertNotIn("I9 ", oc.pseudo_obs_codes("3.03"))

    def test_channel_band(self):
        self.assertEqual(oc.PSEUDO_OBS["3.00"]["X"]["bands"], "0")
        self.assertEqual(oc.PSEUDO_OBS["3.01"]["X"]["bands"], "0")
        for ver in ("3.02", "3.03", "3.04"):
            self.assertEqual(oc.PSEUDO_OBS[ver]["X"]["bands"], "01", ver)
        for ver in oc.VERSIONS[7:]:
            self.assertNotIn("X0 ", oc.pseudo_obs_codes(ver), ver)
            self.assertIn("X9 ", oc.pseudo_obs_codes(ver), ver)
        self.assertEqual(oc.pseudo_obs_codes("2.11"), frozenset())

    def test_blank_attribute(self):
        self.assertTrue(oc.blank_attribute_allowed("3.00"))
        self.assertTrue(oc.blank_attribute_allowed("3.01"))
        for ver in oc.VERSIONS[4:]:
            self.assertFalse(oc.blank_attribute_allowed(ver), ver)
        self.assertFalse(oc.blank_attribute_allowed("2.11"))
        self.assertIn("Unknown tracking mode", page_text("rinex300.txt", 11))
        self.assertIn("Unknown tracking modes are not supported",
                      page_text("rinex303_update1.txt", 20))


class TestHelpers(unittest.TestCase):

    def test_normalize_version(self):
        self.assertEqual(oc.normalize_version("2.1"), "2.10")
        self.assertEqual(oc.normalize_version("2.11"), "2.11")
        self.assertEqual(oc.normalize_version(" 3.05 "), "3.05")
        self.assertEqual(oc.normalize_version(3), "3.00")
        self.assertEqual(oc.normalize_version(4.02), "4.02")
        for bad in ("", "abc", None, True, -1, "3.05x"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    oc.normalize_version(bad)

    def test_valid_codes_and_is_valid(self):
        self.assertIn("C1C", oc.valid_codes("3.04", "G"))
        # Versions are numbers: "3.4" is 3.40, not 3.04.
        self.assertEqual(oc.normalize_version("3.4"), "3.40")
        self.assertTrue(oc.is_valid("3.05", "E", "L8Q"))
        self.assertFalse(oc.is_valid("3.05", "E", "L8Z"))
        self.assertFalse(oc.is_valid("3.05", "G", "C1"))
        self.assertTrue(oc.is_valid("2.1", "G", "P2"))
        self.assertEqual(oc.valid_codes("3.02", "I"), frozenset())
        with self.assertRaises(ValueError):
            oc.valid_codes("3.06", "G")
        with self.assertRaises(ValueError):
            oc.valid_codes("2.00", "G")


class TestObsHeader(unittest.TestCase):

    # Rows with status "C": whether the table prints them with the optional '*'.
    CONDITIONAL_STARRED = {
        "MARKER TYPE": False,
        "APPROX POSITION XYZ": False,
        "RCV CLOCK OFFS APPL": True,
    }

    def test_structure(self):
        for label, entry in oh.OBS_HEADER.items():
            for ver, status in entry["versions"].items():
                with self.subTest(label=label, ver=ver):
                    self.assertIn(ver, oh.VERSIONS)
                    self.assertIn(status, oh.STATUS_CODES)
                    self.assertIn(ver, entry["cite"])
                    self.assertIn(ver, entry["format"])
                    self.assertIn(label, oh.LABEL_LOCATIONS[ver])
                    if status == "C":
                        self.assertTrue(entry["conditions"].get(ver))
            for key in ("format", "conditions", "notes", "spelling", "continuation", "cite"):
                self.assertTrue(set(entry[key]) <= set(entry["versions"]), (label, key))
        for ver in oh.VERSIONS:
            self.assertEqual(set(oh.labels_for(ver)), set(oh.LABEL_LOCATIONS[ver]), ver)

    def test_labels_fit_columns_61_80(self):
        for label, entry in oh.OBS_HEADER.items():
            for ver in entry["versions"]:
                self.assertLessEqual(len(oh.label_text(ver, label)), 20, (label, ver))
        self.assertEqual(len("ANTENNA: PHASECENTER"), 20)

    def test_label_rows_and_stars_in_rinex3_4_tables(self):
        for ver in V3V4:
            name = oh.SOURCE_FILES[ver]
            for label in oh.labels_for(ver):
                text = oh.label_text(ver, label)
                page = oh.LABEL_LOCATIONS[ver][label]
                with self.subTest(ver=ver, label=text, page=page):
                    found = find_label_row(name, page, text)
                    self.assertIsNotNone(found, "label row not found on cited page")
                    status = oh.status(ver, label)
                    starred = found[1]
                    if status == "C":
                        self.assertEqual(starred, self.CONDITIONAL_STARRED[label])
                    else:
                        self.assertEqual(starred, status in ("O", "O-deprecated"))

    def test_label_rows_and_stars_in_rinex2_tables(self):
        for ver in oh.V2:
            name = oh.SOURCE_FILES[ver]
            for label in oh.labels_for(ver):
                number = oh.LABEL_LOCATIONS[ver][label]
                line = spec_lines(name)[number - 1]
                with self.subTest(ver=ver, label=label, line=number):
                    self.assertIn(label, line)
                    starred = line.lstrip().startswith("*")
                    status = oh.status(ver, label)
                    if status == "C":
                        self.assertEqual(starred, self.CONDITIONAL_STARRED[label])
                    else:
                        self.assertEqual(starred, status == "O")

    def test_phase_shift_spelling(self):
        page = oh.LABEL_LOCATIONS["3.01"]["SYS / PHASE SHIFT"]
        self.assertIsNotNone(find_label_row("rinex301.txt", page, "SYS / PHASE SHIFTS"))
        self.assertIsNone(find_label_row("rinex301.txt", page, "SYS / PHASE SHIFT"))
        self.assertEqual(oh.label_text("3.01", "SYS / PHASE SHIFT"), "SYS / PHASE SHIFTS")
        self.assertEqual(oh.label_text("3.02", "SYS / PHASE SHIFT"), "SYS / PHASE SHIFT")
        self.assertEqual(oh.canonical_label("SYS / PHASE SHIFTS  "), "SYS / PHASE SHIFT")
        self.assertEqual(oh.canonical_label("NOT A LABEL"), "NOT A LABEL")

    def test_gates(self):
        st = oh.status
        # GLONASS SLOT / FRQ #: optional in 3.01, mandatory from 3.02.
        self.assertIsNone(st("3.00", "GLONASS SLOT / FRQ #"))
        self.assertEqual(st("3.01", "GLONASS SLOT / FRQ #"), "O")
        for ver in oh.VERSIONS[4:]:
            self.assertEqual(st(ver, "GLONASS SLOT / FRQ #"), "M", ver)
        # SYS / PHASE SHIFT: not in 2.x or 3.00; mandatory 3.01-3.05; deprecated in 4.
        for ver in ("2.10", "2.11", "3.00"):
            self.assertIsNone(st(ver, "SYS / PHASE SHIFT"), ver)
        for ver in ("3.01", "3.02", "3.03", "3.04", "3.05"):
            self.assertEqual(st(ver, "SYS / PHASE SHIFT"), "M", ver)
        for ver in oh.V4:
            self.assertEqual(st(ver, "SYS / PHASE SHIFT"), "O-deprecated", ver)
        # GLONASS COD/PHS/BIS: 3.02-3.05 mandatory, deprecated in 4.
        self.assertIsNone(st("3.01", "GLONASS COD/PHS/BIS"))
        for ver in ("3.02", "3.03", "3.04", "3.05"):
            self.assertEqual(st(ver, "GLONASS COD/PHS/BIS"), "M", ver)
        for ver in oh.V4:
            self.assertEqual(st(ver, "GLONASS COD/PHS/BIS"), "O-deprecated", ver)
        # RINEX 2 only.
        self.assertEqual(st("2.10", "WAVELENGTH FACT L1/2"), "M")
        self.assertEqual(st("2.11", "WAVELENGTH FACT L1/2"), "O")
        for ver in V3V4:
            self.assertIsNone(st(ver, "WAVELENGTH FACT L1/2"), ver)
            self.assertIsNone(st(ver, "# / TYPES OF OBSERV"), ver)
            self.assertEqual(st(ver, "SYS / # / OBS TYPES"), "M", ver)
            self.assertEqual(st(ver, "MARKER TYPE"), "C", ver)
        for ver in oh.V2:
            self.assertEqual(st(ver, "# / TYPES OF OBSERV"), "M", ver)
            self.assertIsNone(st(ver, "SYS / # / OBS TYPES"), ver)
            self.assertIsNone(st(ver, "MARKER TYPE"), ver)
        # RINEX 4 FAIR records.
        for label in ("DOI", "LICENSE OF USE", "STATION INFORMATION"):
            self.assertIsNone(st("3.05", label))
            for ver in oh.V4:
                self.assertEqual(st(ver, label), "O", (ver, label))

    def test_formats_that_change(self):
        fmt = lambda label, ver: oh.OBS_HEADER[label]["format"][ver]
        self.assertEqual(fmt("LEAP SECONDS", "2.11"), "I6")
        self.assertEqual(fmt("LEAP SECONDS", "3.00"), "I6")
        self.assertEqual(fmt("LEAP SECONDS", "3.01"), "4I6")
        self.assertEqual(fmt("LEAP SECONDS", "3.03"), "4I6,A3")
        self.assertEqual(fmt("LEAP SECONDS", "4.02"), "4I6,A3")
        self.assertEqual(fmt("GLONASS SLOT / FRQ #", "3.01"), "I3,1X,8(A1,I2.2,1X,I2)")
        self.assertEqual(fmt("GLONASS SLOT / FRQ #", "3.02"), "I3,1X,8(A1,I2.2,1X,I2,1X)")
        self.assertEqual(fmt("PRN / # OF OBS", "2.11"), "3X,A1,I2,9I6")
        self.assertEqual(fmt("PRN / # OF OBS", "3.00"), "3X,A1,I2.2,9I6")
        self.assertEqual(fmt("# / TYPES OF OBSERV", "2.10"), "I6,9(4X,A2)")
        # LEAP SECONDS pages: time-system identifier field only from 3.03.
        ident = r"(Time system|System time) identifier"
        for ver in ("3.01", "3.02"):
            text = page_text(oh.SOURCE_FILES[ver], oh.LABEL_LOCATIONS[ver]["LEAP SECONDS"])
            self.assertNotRegex(text, ident, ver)
        for ver in ("3.03", "3.04", "3.05") + oh.V4:
            text = page_text(oh.SOURCE_FILES[ver], oh.LABEL_LOCATIONS[ver]["LEAP SECONDS"])
            self.assertRegex(text, ident, ver)

    def test_condition_and_deprecation_wording_on_cited_pages(self):
        for ver in V3V4:
            name = oh.SOURCE_FILES[ver]
            loc = oh.LABEL_LOCATIONS[ver]
            with self.subTest(ver=ver, label="APPROX POSITION XYZ"):
                text = despace(page_text(name, loc["APPROX POSITION XYZ"],
                                         loc["APPROX POSITION XYZ"] + 1))
                self.assertIn("Optionalformovingplatforms", text)
            with self.subTest(ver=ver, label="MARKER TYPE"):
                text = despace(page_text(name, loc["MARKER TYPE"], loc["MARKER TYPE"] + 1))
                self.assertIn("RecordrequiredexceptforGEODETIC", text)
        for ver in oh.V4:
            name = oh.SOURCE_FILES[ver]
            for label in ("SYS / PHASE SHIFT", "GLONASS COD/PHS/BIS"):
                with self.subTest(ver=ver, label=label):
                    text = page_text(name, oh.LABEL_LOCATIONS[ver][label])
                    self.assertIn("strongly deprecated", text)

    def test_pgm_run_by_date(self):
        repeat = oh.PGM_RUN_BY_DATE["may_repeat"]
        self.assertEqual(set(repeat), set(oh.VERSIONS))
        for ver in oh.VERSIONS:
            self.assertEqual(repeat[ver][0], ver in oh.V4, ver)
        for ver in oh.V4:
            text = despace(page_text(oh.SOURCE_FILES[ver],
                                     oh.LABEL_LOCATIONS[ver]["PGM / RUN BY / DATE"]))
            self.assertIn("Additionallinesofthistypecanappear", text, ver)
        fmt = oh.PGM_RUN_BY_DATE["date_format"]
        self.assertIsNone(fmt["2.11"][0])
        self.assertEqual(fmt["3.00"][0], "yyyymmdd hhmmss zone")
        self.assertIn("yyyymmdd hhmmss zone", page_text("rinex300.txt", 13))


if __name__ == "__main__":
    unittest.main()
