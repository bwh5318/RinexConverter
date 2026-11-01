"""Two transcriptions of the observation-code tables, made separately from specs/text
(rinexcore/spec/obscodes.py for the converter; tests/expectations/code_validity.json for
the independent checks, PLAN §3.1/§1.5), must agree. A difference is resolved against
the PDF by the user, not by editing either side to match the other."""

import unittest

from rinexcore.spec import obscodes as conv
from tests.independent import codes as indep

VERSIONS = ("2.10", "2.11", "3.00", "3.01", "3.02", "3.03", "3.04", "3.05", "4.00", "4.01", "4.02")


class TablesAgree(unittest.TestCase):
    def test_systems(self):
        for v in VERSIONS:
            with self.subTest(version=v):
                self.assertEqual(set(conv.SYSTEMS[v]), set(indep.systems(v)))

    def test_codes(self):
        for v in VERSIONS:
            for s in conv.SYSTEMS[v]:
                with self.subTest(version=v, system=s):
                    self.assertEqual(set(conv.valid_codes(v, s)), set(indep.codes(v, s)))


if __name__ == "__main__":
    unittest.main()
