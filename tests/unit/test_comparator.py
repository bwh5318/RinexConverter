"""The independent comparator must fail a wrong converter (PLAN §1: "the checks must not be
able to pass a wrong converter"). Each test damages a correct output and expects a problem."""

import copy
import unittest

from rinexconv.engine import Options, convert_data
from tests.independent.allowed import check as allowed_check
from tests.independent.compare import compare_met, compare_nav, compare_obs

from .test_nav_fixtures import SPEC_211
from .test_obs_fixtures import V211, table_file


class Comparator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        fcn = table_file(tempfile.mkdtemp(), "R07 5\n")
        outs = convert_data(V211, "t0010.26o", Options("3.05", glo_fcn=fcn, compression="none"))
        cls.out = outs[0].data
        cls.rep = outs[0].report.to_dict()

    def test_correct_output_passes(self):
        self.assertEqual(compare_obs(V211, self.out, self.rep), [])

    def test_swapped_signals_fail(self):
        lines = self.out.decode("latin-1").split("\n")
        k = next(i for i, l in enumerate(lines) if l.startswith("G05"))
        l = lines[k]
        # swap the C1C and C2W fields (16 columns each after the satellite id)
        f = [l[3 + 16 * j:3 + 16 * j + 16] for j in range(7)]
        f[0], f[2] = f[2], f[0]
        lines[k] = "G05" + "".join(f)
        bad = "\n".join(lines).encode("latin-1")
        self.assertTrue(compare_obs(V211, bad, self.rep))

    def test_dropped_record_fails(self):
        lines = self.out.decode("latin-1").split("\n")
        k = next(i for i, l in enumerate(lines) if l.startswith("R07"))
        e = next(i for i in range(k, -1, -1) if lines[i].startswith(">"))
        lines[e] = lines[e][:32] + "%3d" % (int(lines[e][32:35]) - 1) + lines[e][35:]
        del lines[k]
        bad = "\n".join(lines).encode("latin-1")
        self.assertTrue(compare_obs(V211, bad, self.rep))

    def test_changed_value_fails(self):
        bad = self.out.replace(b"22000000.105", b"22000000.106")
        self.assertTrue(compare_obs(V211, bad, self.rep))

    def test_overclaimed_loss_fails(self):
        rep = copy.deepcopy(self.rep)
        rep["losses"]["obs-code-not-representable:G:S2"] = {"count": 2, "detail": {}}
        self.assertTrue(compare_obs(V211, self.out, rep))

    def test_unclaimed_loss_fails(self):
        out = convert_data(V211, "t0010.26o", Options("3.05", drop_unresolvable=True, compression="none"))
        rep = out[0].report.to_dict()
        self.assertEqual(compare_obs(V211, out[0].data, rep), [])
        rep["losses"] = {}
        self.assertTrue(compare_obs(V211, out[0].data, rep))

    def test_loss_table_rejects_unlisted_loss(self):
        rep = copy.deepcopy(self.rep)
        # a representable code claimed as "not representable" (reviewer's C1C case): rejected
        rep["losses"]["obs-code-not-representable:G:C1"] = {"count": 1, "detail": {}}
        self.assertTrue(allowed_check(rep))
        # a code the target really lacks: GLONASS has no band 5 in RINEX 3.05
        rep["losses"] = {"obs-code-not-representable:R:C5": {"count": 1, "detail": {}}}
        self.assertEqual(allowed_check(rep), [])
        rep["target_version"] = rep["source_version"]
        self.assertTrue(allowed_check(rep))               # same version: not allowed
        rep["losses"] = {"made-up-loss": {"count": 1}}
        self.assertTrue(allowed_check(rep))

    def test_nav_changed_value_fails(self):
        outs = convert_data(SPEC_211, "b.99n", Options("3.05", compression="none"))
        rep = outs[0].report.to_dict()
        self.assertEqual(compare_nav(SPEC_211, [outs[0].data], rep), [])
        bad = outs[0].data.replace(b".910000000000D+02  .934062500000D+02",
                                   b".934062500000D+02  .910000000000D+02")
        self.assertTrue(compare_nav(SPEC_211, [bad], rep))        # positional: a swap is a difference
        bad = outs[0].data.replace(b".934062500000D+02", b".934062500001D+02")
        self.assertTrue(compare_nav(SPEC_211, [bad], rep))


if __name__ == "__main__":
    unittest.main()
