"""Batch-mode speed changes in the CLI (2026-11-03, after Codex Sol's optimisation plan): the
cached parse of nav companion names and the memory-aware parallel scheduler. Neither may
change a result: companions are the files a fresh folder listing finds, and a parallel run
gives the results of a serial run, in input order."""

import os
import random
import shutil
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from rinexconv import cli
from rinexconv.engine import Options
from rinexcore import names

SPEC = Path(__file__).resolve().parents[1] / "fixtures" / "spec_examples"


def original_sibling_nav(path):
    """sibling_nav before the speed work (commit 361218b): the reference."""
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
        return []
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


class Companions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cli._NAV_DAY.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def touch(self, name):
        Path(self.tmp, name).write_bytes(b"x")
        return os.path.join(self.tmp, name)

    def test_same_companions_as_a_listing(self):
        g = self.touch("abcd2740.26g")
        self.touch("abcd2750.26g")                       # another day
        self.touch("abcd2740.26n")                       # GPS only: no channels
        m = self.touch("XXXX00XXX_R_20262740000_01D_MN.rnx")
        obs = self.touch("abcd2740.26o")
        self.assertEqual(cli.sibling_nav(obs), sorted([g, m]))
        self.assertEqual(cli.sibling_nav(obs), sorted([g, m]))      # names parsed from the cache

    def test_changes_are_seen_whatever_the_folder_time(self):
        # Sol, xhigh review: a listing kept while the folder's modification time was unchanged
        # missed a companion added within the time's resolution (FAT: 2 s; network shares)
        obs = self.touch("abcd2740.26o")
        stat = os.stat(self.tmp)
        with mock.patch.object(cli.os, "stat", lambda p, *a, **k: stat):     # the time never moves
            self.assertEqual(cli.sibling_nav(obs), [])
            g = self.touch("abcd2740.26g")
            self.assertEqual(cli.sibling_nav(obs), [g])
            os.rename(g, os.path.join(self.tmp, "abcd2740.26p"))          # renamed: the new name
            self.assertEqual(cli.sibling_nav(obs), [os.path.join(self.tmp, "abcd2740.26p")])
            os.remove(os.path.join(self.tmp, "abcd2740.26p"))
            self.assertEqual(cli.sibling_nav(obs), [])

    def test_random_folders_match_the_original(self):
        r = random.Random(5)
        pool = ["abcd2740.26g", "abcd2740.26p", "abcd2740.26n", "ABCD2740.26G", "abcd2740.26g.Z",
                "abcd2741.26g", "abcd274a.26g.gz", "abcd2740.86g", "abcd2740.79p", "abcd2741.26o",
                "XXXX00XXX_R_20262740000_01D_MN.rnx", "XXXX00XXX_R_20262740000_01D_RN.rnx.gz",
                "XXXX00XXX_R_20262740000_01D_GN.rnx", "XXXX00XXX_R_20262750000_01D_MN.rnx",
                "XXXX00XXX_R_20262740000_01D_mn.rnx", "notes.txt", "abcd2740.26o"]
        obs_names = ["abcd2740.26o", "abcd2741.26o", "XXXX00XXX_R_20262740000_01D_30S_MO.crx.gz",
                     "abcd2740.86o", "zz.txt"]
        for _ in range(60):
            for f in os.listdir(self.tmp):
                os.remove(os.path.join(self.tmp, f))
            for n in r.sample(pool, r.randrange(0, len(pool))):
                self.touch(n)
            for o in obs_names:
                p = os.path.join(self.tmp, o)
                self.assertEqual(cli.sibling_nav(p), original_sibling_nav(p), (o, os.listdir(self.tmp)))

    def test_unreadable_folder(self):
        self.assertEqual(cli.sibling_nav(os.path.join(self.tmp, "nope", "abcd2740.26o")), [])


class ParallelLikeSerial(unittest.TestCase):
    """run_parallel returns what a serial run returns, in input order, under any budget."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inputs = []
        for i, f in enumerate(sorted((SPEC / "3.05").glob("a*_nav_*.rnx"))[:4]
                              + sorted((SPEC / "2.11").glob("a*_obs*.rnx"))[:2]):
            p = Path(self.tmp, "in", f"{i}_{f.name}")
            p.parent.mkdir(exist_ok=True)
            p.write_bytes(f.read_bytes() * (1 if i % 2 else 1))
            self.inputs.append(str(p))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_mode(self, sub, jobs, budget=None):
        a = Namespace(out=os.path.join(self.tmp, sub, "out"), report=os.path.join(self.tmp, sub, "rep"),
                      force=False)
        opts = Options(target="3.04", auto_nav=False, assume_phase_aligned=True)
        if jobs == 1:
            rows = [r for p in self.inputs for r in cli.run_input(p, opts, a.out, a.report, a.force)]
        else:
            rows = cli.run_parallel(self.inputs, opts, a, jobs, budget=budget)
        # the folders differ per mode; compare what each input produced
        return [(os.path.basename(r[0]), r[1], r[2].replace(self.tmp, ""), [os.path.basename(w) for w in r[3]])
                for r in rows]

    def test_parallel_equals_serial(self):
        serial = self.run_mode("s", 1)
        self.assertEqual(self.run_mode("p", 3), serial)
        self.assertEqual(self.run_mode("b", 3, budget=1), serial)      # one input at a time

    def test_estimated_peak(self):
        p = Path(self.tmp, "abcd2740.26d.gz")
        p.write_bytes(b"x" * 1000)
        q = Path(self.tmp, "abcd2740.26o")
        q.write_bytes(b"x" * 1000)
        self.assertEqual(cli._estimated_peak(str(p)), 1000 * 8 * 4 * 2.5)
        self.assertEqual(cli._estimated_peak(str(q)), 1000 * 2.5)
        self.assertGreater(cli._physical_memory() or 1, 0)


if __name__ == "__main__":
    unittest.main()
