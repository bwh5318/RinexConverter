"""The faster forms of the observation path give what the forms they replaced gave (the speed
work of 2026-11-03). Each test runs the old form, kept here as the reference, and the new one on
the same inputs, random and edge cases."""

import random
import re
import unittest
from unittest import mock

from rinexconv import obsconv
from rinexconv.engine import WRITE_VERSIONS, Options, convert_data
from rinexcore import obs
from rinexcore.errors import CorruptError, RinexError
from rinexcore.io import compress, spool

from .test_obs_fixtures import V211, V305

_FIELDS_OK = re.compile(r"(?:[ 0-9.+-]{14}[ 0-9]{2})*(?:[ 0-9.+-]{0,14}|[ 0-9.+-]{14}[ 0-9]{0,2})")
# characters an observation field may hold, and some it may not (whitespace of other kinds, a
# letter, a character beyond latin-1)
CHARS = " 0123456789.+-" * 4 + "0" * 10 + " " * 20 + "4567" + "E\t\xa0\x1c\x85x Ā"


def rnd_text(r, n):
    return "".join(r.choice(CHARS) for _ in range(n))


class FieldCheck(unittest.TestCase):
    def test_fields_ok_is_the_regex(self):
        r = random.Random(7)
        for _ in range(20000):
            s = rnd_text(r, r.randrange(0, 70))
            if r.random() < 0.5:          # mostly valid text, so both answers occur often
                s = "".join(c if c in " 0123456789.+-" else "1" for c in s)
            self.assertEqual(obs._fields_ok(s), bool(_FIELDS_OK.fullmatch(s)), repr(s))

    def test_reread_checks_after_a_partial_first_read(self):
        # the check is skipped only after a first read that ran to its end
        bad = V305.replace(b"  19000100.107", b"  19000100.1x7", 1)       # the last epoch
        self.assertNotEqual(bad, V305)
        from rinexcore.rinexfile import first_line, sniff
        f = obs.read_obs_payload(bad, sniff(first_line(bad)))
        it = f.iter_epochs()
        try:
            next(it)
        except CorruptError:
            pass
        it.close()
        with self.assertRaises(CorruptError):
            for _ in f.iter_epochs():
                pass


def ref_fields(rec, n):
    """The per-field loop of obsconv.survey and convert_epochs before field masks."""
    vals, fos, kinds = [], [], 0
    for i in range(n):
        f = rec[16 * i:16 * i + 16]
        if f[:14].strip(obs._ZERO_CHARS):
            vals.append(i)
        elif f[14:16].strip():
            fos.append(i)
        p = f.ljust(16)
        if p[13] in "0." and not p[:14].strip(obs._ZERO_CHARS):
            kinds |= obsconv._KIND_ZERO
        if p[14] in "4567":
            kinds |= obsconv._KIND_B2
    return vals, fos, kinds | (obsconv._KIND_FLAGONLY if fos else 0)


class FieldMasks(unittest.TestCase):
    def test_masks_are_the_field_loop(self):
        r = random.Random(11)
        for _ in range(6000):
            n = r.randrange(0, 9)
            rec = "".join(r.choice([" " * 16, rnd_text(r, 16), " " * 10 + "0.000" + r.choice("  145"),
                                    "  12345678.9" + r.choice("00 ") + "0" + rnd_text(r, 2)])
                          for _ in range(n))
            rec = rec[:max(0, len(rec) - r.choice([0, 0, 0, 3, 17]))]      # short records too
            y = obsconv._field_mask(rec, n)
            vals, fos, kinds = ref_fields(rec, n)
            self.assertEqual(obsconv._mask_fields(y, n), (vals, fos), repr(rec))
            self.assertEqual(obsconv._mask_kinds(y, n), kinds, repr(rec))


def old_unlzw(data):
    """compress.unlzw before the group-wise reader (2026-11-03)."""
    if data[:2] != compress.Z_MAGIC:
        raise CorruptError("not a .Z stream", rule="IO.LZW")
    if len(data) < 3:
        raise CorruptError(".Z stream has no header byte", rule="IO.LZW")
    maxbits = data[2] & 0x1F
    block = bool(data[2] & 0x80)
    if not 9 <= maxbits <= 16:
        raise CorruptError(f".Z stream has bad maxbits {maxbits}", rule="IO.LZW")
    stream = data[3:]
    total_bits = len(stream) * 8
    first_free = 257 if block else 256
    table = [bytes([i]) for i in range(256)] + ([b""] if block else [])
    nbits, pos, seg_start = 9, 0, 0
    prev = None
    out = bytearray()
    limit = 1 << maxbits
    while pos + nbits <= total_bits:
        byte, bit = divmod(pos, 8)
        word = int.from_bytes(stream[byte:byte + 3], "little")
        code = (word >> bit) & ((1 << nbits) - 1)
        pos += nbits
        if block and code == 256:
            group = nbits * 8
            pos = seg_start + -(-(pos - seg_start) // group) * group
            seg_start = pos
            del table[first_free:]
            nbits, prev = 9, None
            continue
        if prev is None:
            if code >= 256:
                raise CorruptError(".Z stream has a bad first code", rule="IO.LZW")
            entry = table[code]
        elif code < len(table):
            entry = table[code]
            if len(table) < limit:
                table.append(table[prev] + entry[:1])
        elif code == len(table):
            entry = table[prev] + table[prev][:1]
            table.append(entry)
        else:
            raise CorruptError(f".Z stream has a bad code {code} at bit {pos}", rule="IO.LZW")
        out += entry
        prev = code
        if len(table) > (1 << nbits) - 1 and nbits < maxbits:
            group = nbits * 8
            pos = seg_start + -(-(pos - seg_start) // group) * group
            seg_start = pos
            nbits += 1
    return bytes(out)


def old_lzw(data, maxbits=16):
    """compress.lzw before group packing (2026-11-03): a bit-at-a-time writer."""
    out, st = bytearray(), [0, 0, 0]          # acc, nacc, seg_bits

    def put(code, nbits):
        st[0] |= code << st[1]
        st[1] += nbits
        st[2] += nbits
        while st[1] >= 8:
            out.append(st[0] & 0xFF)
            st[0] >>= 8
            st[1] -= 8

    def pad_group(nbits):
        rem = st[2] % (nbits * 8)
        if rem:
            put(0, nbits * 8 - rem)
        st[2] = 0
    header = compress.Z_MAGIC + bytes([0x80 | maxbits])
    if not data:
        return header
    limit, table, free, nbits = 1 << maxbits, {}, 257, 9
    checkpoint, ratio, out_bits_at_clear, total_out_bits = 10000, 0, 0, 0
    ent, in_count = data[0], 1
    for c in data[1:]:
        in_count += 1
        key = (ent << 8) | c
        code = table.get(key)
        if code is not None:
            ent = code
            continue
        put(ent, nbits)
        total_out_bits += nbits
        if free > (1 << nbits) - 1 and nbits < maxbits:
            pad_group(nbits)
            nbits += 1
        if free < limit:
            table[key] = free
            free += 1
        elif in_count >= checkpoint:
            checkpoint = in_count + 10000
            rat = (in_count << 8) // max(1, (total_out_bits - out_bits_at_clear) // 8)
            if rat > ratio:
                ratio = rat
            else:
                ratio = 0
                put(256, nbits)
                pad_group(nbits)
                table.clear()
                free, nbits, out_bits_at_clear, in_count, checkpoint = 257, 9, total_out_bits, 0, 10000
        ent = c
    put(ent, nbits)
    if st[1]:
        out.append(st[0] & 0xFF)
    return header + bytes(out)


class Lzw(unittest.TestCase):
    def samples(self):
        r = random.Random(3)
        out = [b"", b"a", b"ab", b"abababab" * 500, bytes(range(256)) * 40, V211, V305 * 30]
        for n in (50, 3000, 40000, 120000):
            out.append(bytes(r.choice(b"0123456789  .\n") for _ in range(n)))
            out.append(r.randbytes(n))
        return out

    def test_encoder_and_decoder_bytes(self):
        for maxbits in (9, 10, 12, 16):          # small tables: table full, ratio checks, CLEARs
            for d in self.samples():
                z = compress.lzw(d, maxbits)
                self.assertEqual(z, old_lzw(d, maxbits), (maxbits, len(d)))
                self.assertEqual(compress.unlzw(z), d)

    def test_damaged_streams_fail_alike(self):
        r = random.Random(5)
        for d in self.samples()[3:9]:
            z = compress.lzw(d, r.choice((9, 12, 16)))
            for _ in range(60):
                b = bytearray(z)
                for _ in range(r.randrange(1, 4)):
                    b[r.randrange(2, len(b))] = r.randrange(256)
                b = bytes(b[:r.randrange(2, len(b) + 1)])
                got = []
                for fn in (old_unlzw, compress.unlzw):
                    try:
                        got.append(fn(b))
                    except CorruptError as e:
                        got.append(("error", str(e), e.rule))
                self.assertEqual(got[0], got[1])


class SpoolWrites(unittest.TestCase):
    def test_spilled_small_pieces(self):
        r = random.Random(9)
        with mock.patch.object(spool, "SPILL_BYTES", 5000), mock.patch.object(spool, "WRITE_BYTES", 700):
            for _ in range(30):
                pieces = [r.randbytes(r.choice([0, 1, 50, 300, 699, 700, 701, 2500])) for _ in range(60)]
                self.assertEqual(spool.join_bytes(iter(pieces)), b"".join(pieces))


def outcome(data, name, target, **kw):
    """The outputs and report of a conversion, or its refusal."""
    try:
        outs = convert_data(data, name, Options(target, compression="none", **kw))
        return [(o.name, o.data) for o in outs], outs[0].report.to_json()
    except RinexError as e:
        return type(e).__name__, str(e)


class CopyPlans(unittest.TestCase):
    """convert_epochs copies a record whole only where its per-field path would change nothing:
    outputs and reports with and without the copy plans are the same."""

    def outcome(self, data, name, target, **kw):
        return outcome(data, name, target, **kw)

    def test_plans_change_nothing(self):
        zeros = V211.replace(b"  21000002.312", b"         0.000", 1)    # a zero value to blank
        for data, name in ((V211, "test0010.26o"), (zeros, "test0010.26o"),
                           (V305, "TEST00XXX_R_20262740000_01D_30S_MO.rnx")):
            for target in WRITE_VERSIONS:
                for kw in ({}, {"crx": True}, {"assume_phase_aligned": True}, {"keep_lli_bit2": True}):
                    with self.subTest(name=name, target=target, kw=kw):
                        a = self.outcome(data, name, target, **kw)
                        with mock.patch.object(obsconv._ObsConverter, "_copy_plan", lambda *a: False):
                            b = self.outcome(data, name, target, **kw)
                        self.assertEqual(a, b)


_MASK_FIELDS = [" " * 16, "         1.234  ", "         1.2344 ", "         0.000  ", " " * 14 + "4 "]


def distinct_masks(n_epochs, n_sats=30, events=False):
    """A RINEX 3.05 GPS file whose records hold almost all distinct field masks (Sol, xhigh review
    of the optimisation): each field one of blank, a value, a value with LLI 4, 0.000 and an LLI
    alone, chosen by a hash of (epoch, satellite). With `events`: a flag-6 cycle-slip epoch every
    seventh epoch and, halfway, a flag-4 event that changes the type list (eight types to six)."""
    def hdr(text, label):
        return f"{text:<60}{label}"
    t8 = "C1C L1C D1C S1C C2W L2W D2W S2W"
    head = [hdr("     3.05           OBSERVATION DATA    G (GPS)", "RINEX VERSION / TYPE"),
            hdr("TESTGEN 1.0         TEST                20261030 120000 UTC", "PGM / RUN BY / DATE"),
            hdr("TEST", "MARKER NAME"),
            hdr("  4027894.0060   307045.6000  4919474.9100", "APPROX POSITION XYZ"),
            hdr("G    8 " + t8, "SYS / # / OBS TYPES"),
            hdr("G L1C", "SYS / PHASE SHIFT"), hdr("G L2W", "SYS / PHASE SHIFT"),
            hdr("     1.000", "INTERVAL"),
            hdr("  2026    10     1     0     0    0.0000000     GPS", "TIME OF FIRST OBS"),
            hdr("", "END OF HEADER")]
    body = []
    n_types = 8
    for i in range(n_epochs):
        m, s = divmod(i, 60)
        h, m = divmod(m, 60)
        stamp = f"> 2026 10 01 {h:02d} {m:02d}{s:3d}.0000000"
        if events and i == n_epochs // 2:
            body += [f"{stamp}  4  1", hdr("G    6 C1C L1C D1C S1C C2W L2W", "SYS / # / OBS TYPES")]
            n_types = 6
        flag = 6 if events and i % 7 == 3 else 0
        body.append(f"{stamp}  {flag}{n_sats:3d}")
        for s_ in range(1, n_sats + 1):
            v = ((30 * i + s_) * 2654435761) % 5 ** 8
            rec = ""
            for _ in range(n_types):
                v, d = divmod(v, 5)
                rec += _MASK_FIELDS[d]
            body.append(f"G{s_:02d}" + rec.rstrip())
    return ("\n".join(head + body) + "\n").encode("latin-1")


class SurveyFolding(unittest.TestCase):
    """The survey folds a satellite's mask counts into its field counts past _SURVEY_MASKS
    distinct masks (Sol, xhigh review of the optimisation: memory). Folding at any point gives
    the survey, the outputs and the reports of never folding, including the order of the
    flag-only fields and of the systems."""

    NAME = "SYNT00XXX_R_20262740000_01H_01S_GO.rnx"

    def run_with(self, limit, data, name, targets):
        from rinexconv.engine import load_bytes
        with mock.patch.object(obsconv, "_SURVEY_MASKS", limit):
            src = load_bytes(data).model
            st = src._survey
            survey = repr((sorted(st[0]),) + st[1:])
            outs = [outcome(data, name, t) for t in targets]
        return survey, outs

    def test_folding_changes_nothing(self):
        cases = [(distinct_masks(120, 12, events=True), self.NAME, ("2.11", "3.04", "4.02")),
                 (distinct_masks(60, 30), self.NAME, ("2.11", "3.05")),
                 (V211, "test0010.26o", ("2.11", "3.05")),
                 (V305, "TEST00XXX_R_20262740000_01D_30S_MO.rnx", ("2.11", "4.02"))]
        for data, name, targets in cases:
            ref = self.run_with(10 ** 9, data, name, targets)
            for limit in (1, 2, obsconv._SURVEY_MASKS):
                with self.subTest(name=name, size=len(data), limit=limit):
                    self.assertEqual(self.run_with(limit, data, name, targets), ref)


if __name__ == "__main__":
    unittest.main()
