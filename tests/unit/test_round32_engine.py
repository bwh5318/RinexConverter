"""Regression tests for review round 32 (2026-11-02, docs/DECISIONS.md "review round 32"):
the engine and CLI items of the checks reviewer: a split output written in part, a report
overwritten unchecked, and a merge input's refusal reported as refused-corrupt."""

import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rinexconv import engine
from rinexconv.cli import main as cli_main
from rinexconv.engine import Options, Output, convert_data, write_outputs
from rinexcore.errors import (InvocationError, MissingInformationError, NotRepresentableError,
                              REFUSED_MISSING, REFUSED_NOT_REPRESENTABLE)

MIXED = Path(__file__).resolve().parents[1] / "fixtures" / "spec_examples" / "3.05" / "a11_nav_mixed.rnx"


def is_new_file(src):
    """The rename of a new output from its temporary file (not a file put aside or back)."""
    name = os.path.basename(str(src))
    return name.startswith(".rinexconv-") and not name.endswith(".old")


def run_cli(args):
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        rc = cli_main(args)
    return rc, err.getvalue()


class SplitOutputWrittenAsASet(unittest.TestCase):
    """PLAN §1 clause 1: "A partial output is deleted, never left looking complete." A RINEX 3
    mixed nav file to RINEX 2 is a set of files (n, g); one that exists stops the whole set."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, MIXED.name)
        shutil.copy(MIXED, self.src)
        self.out = os.path.join(self.tmp, "out")
        names = [o.name for o in convert_data(MIXED.read_bytes(), MIXED.name,
                                              Options(target="2.11", auto_nav=False))]
        self.assertEqual(len(names), 2, names)
        self.names = names

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_second_output_exists(self):
        os.makedirs(self.out)
        Path(self.out, self.names[1]).write_bytes(b"old")
        rc, err = run_cli([self.src, "--to", "2.11", "--out", self.out, "--no-auto-nav"])
        self.assertEqual(rc, 5, err)
        self.assertIn("exists", err)
        self.assertEqual(sorted(os.listdir(self.out)), [self.names[1]])      # nothing new
        self.assertEqual(Path(self.out, self.names[1]).read_bytes(), b"old")

    def test_force_writes_both(self):
        os.makedirs(self.out)
        Path(self.out, self.names[1]).write_bytes(b"old")
        rc, err = run_cli([self.src, "--to", "2.11", "--out", self.out, "--no-auto-nav", "--force"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(sorted(os.listdir(self.out)), sorted(self.names))

    def test_rename_failure_removes_the_set(self):
        outs = [Output("a.26n", b"n", None), Output("a.26g", b"g", None)]
        real = os.replace
        calls = []

        def fail_second(src, dst):
            calls.append(dst)
            if len(calls) == 2:
                raise OSError("disk full")
            return real(src, dst)
        with mock.patch.object(engine.os, "replace", fail_second):
            with self.assertRaises(InvocationError) as cm:
                write_outputs(outs, self.out)
        self.assertIn("already written were removed", str(cm.exception))
        self.assertEqual(os.listdir(self.out), [])                            # no temp file either

    def test_forced_rollback_puts_old_files_back(self):
        """Round 33 (Sol): with --force, a failed rename deleted an old file the set had already
        replaced. Now every replaced file is put back as it was."""
        os.makedirs(self.out)
        Path(self.out, "a.26n").write_bytes(b"OLD-N")
        Path(self.out, "a.26g").write_bytes(b"OLD-G")
        outs = [Output("a.26n", b"NEW-N", None), Output("a.26g", b"NEW-G", None)]
        real = os.replace

        def fail_new_g(src, dst):
            if str(dst).endswith("a.26g") and is_new_file(src):
                raise OSError("disk full")
            return real(src, dst)
        with mock.patch.object(engine.os, "replace", fail_new_g):
            with self.assertRaises(InvocationError):
                write_outputs(outs, self.out, force=True)
        self.assertEqual(Path(self.out, "a.26n").read_bytes(), b"OLD-N")
        self.assertEqual(Path(self.out, "a.26g").read_bytes(), b"OLD-G")
        self.assertEqual(sorted(os.listdir(self.out)), ["a.26g", "a.26n"])     # nothing left aside

    def test_forced_set_replaces_and_cleans_up(self):
        os.makedirs(self.out)
        Path(self.out, "a.26n").write_bytes(b"OLD-N")
        write_outputs([Output("a.26n", b"NEW-N", None), Output("a.26g", b"NEW-G", None)], self.out, force=True)
        self.assertEqual(Path(self.out, "a.26n").read_bytes(), b"NEW-N")
        self.assertEqual(sorted(os.listdir(self.out)), ["a.26g", "a.26n"])

    def test_folder_with_an_output_name_is_never_replaced(self):
        """Round 33 (checks reviewer): with --force, a folder named like an output was moved
        aside with its contents; it is refused, and nothing of the set is written."""
        os.makedirs(os.path.join(self.out, "a.26g"))
        Path(self.out, "a.26g", "userfile.txt").write_bytes(b"keep")
        for force in (False, True):
            with self.subTest(force=force), self.assertRaises(InvocationError) as cm:
                write_outputs([Output("a.26n", b"N", None), Output("a.26g", b"G", None)], self.out, force=force)
            self.assertIn("not a file", str(cm.exception))
        self.assertEqual(sorted(os.listdir(self.out)), ["a.26g"])
        self.assertEqual(Path(self.out, "a.26g", "userfile.txt").read_bytes(), b"keep")

    def test_concurrent_job_with_the_same_name(self):
        """Round 34/35 (Sol): job 2 tries to write the same name while job 1 is between its
        checks and its renames. Job 2 (another thread here, another process in --jobs) waits for
        the folder lock, then finds job 1's file: without --force it gets 'exists', and job 1's
        bytes stay."""
        import threading
        real = engine._output_target
        result = {}

        def job2():
            try:
                write_outputs([Output("same.26o", b"JOB-2", None)], self.out)
                result["job2"] = "written"
            except InvocationError as e:
                result["job2"] = str(e)

        def target_then_other_job(out, d, force, inputs):
            t = real(out, d, force, inputs)
            if "thread" not in result:
                result["thread"] = threading.Thread(target=job2)
                result["thread"].start()
                result["thread"].join(1.0)        # it must be waiting on the lock
                result["waited"] = result["thread"].is_alive()
            return t
        with mock.patch.object(engine, "_output_target", target_then_other_job):
            write_outputs([Output("same.26o", b"JOB-1", None)], self.out)
        result["thread"].join(30)
        self.assertTrue(result["waited"])
        self.assertIn("exists", result["job2"])
        self.assertEqual(Path(self.out, "same.26o").read_bytes(), b"JOB-1")
        self.assertEqual(os.listdir(self.out), ["same.26o"])

    def test_reservation_released_when_a_later_name_exists(self):
        os.makedirs(self.out)
        Path(self.out, "a.26g").write_bytes(b"old")
        # skip the up-front checks, as if a.26g appeared between them and the reservation
        with mock.patch.object(engine, "_output_target", lambda o, d, f, i: d / o.name):
            with self.assertRaises(InvocationError):
                write_outputs([Output("a.26n", b"N", None), Output("a.26g", b"G", None)], self.out)
        self.assertEqual(sorted(os.listdir(self.out)), ["a.26g"])               # a.26n reservation removed
        self.assertEqual(Path(self.out, "a.26g").read_bytes(), b"old")

    def test_folder_lock_serialises_writers(self):
        """Round 35 (Sol): two forced transactions in one folder must not interleave. The lock
        is an OS lock, so a second holder (another handle, as another process would have) waits
        until the first lets go."""
        import threading
        os.makedirs(self.out)
        order = []
        with engine.output_lock(self.out):
            t = threading.Thread(target=lambda: (engine.output_lock(self.out).__enter__(), order.append("B")))
            t.start()
            t.join(0.5)
            order.append("A-done")
        t.join(15)
        self.assertEqual(order, ["A-done", "B"])
        self.assertNotIn(engine.lock_path(self.out).name, os.listdir(self.out))  # the folder stays clean

    def test_interrupt_during_renames_rolls_back(self):
        """Round 35 (checks reviewer): Ctrl-C between two renames left the first file of the set."""
        os.makedirs(self.out)
        Path(self.out, "a.26n").write_bytes(b"OLD-N")
        real = os.replace
        seen = []

        def interrupt_second_new_file(src, dst):
            if is_new_file(src):
                seen.append(dst)
                if len(seen) == 2:
                    raise KeyboardInterrupt
            return real(src, dst)
        for force in (True, False):
            seen.clear()
            with self.subTest(force=force):
                outs = [Output("a.26n" if force else "b.26n", b"NEW-N", None), Output("a.26g", b"NEW-G", None)]
                with mock.patch.object(engine.os, "replace", interrupt_second_new_file):
                    with self.assertRaises(KeyboardInterrupt):
                        write_outputs(outs, self.out, force=force)
                self.assertEqual(sorted(os.listdir(self.out)), ["a.26n"])
                self.assertEqual(Path(self.out, "a.26n").read_bytes(), b"OLD-N")

    def test_interrupt_after_every_rename(self):
        """Round 36 (Sol, checks reviewer): an interruption right after any rename has taken
        effect (the old file moved aside, a new file placed, ...) leaves the folder exactly as it
        was: every old file back under its name, nothing new, nothing aside."""
        real = os.replace
        for force in (True, False):
            for k in range(1, 7):
                with self.subTest(force=force, after_rename=k):
                    shutil.rmtree(self.out, ignore_errors=True)
                    os.makedirs(self.out)
                    before = {"a.26n": b"OLD-N", "keep.txt": b"K"}
                    if force:
                        before["a.26g"] = b"OLD-G"
                    for n, b in before.items():
                        Path(self.out, n).write_bytes(b)
                    calls = []

                    def interrupt_after(src, dst):
                        real(src, dst)
                        calls.append(dst)
                        if len(calls) == k:
                            raise KeyboardInterrupt
                    outs = [Output("a.26n" if force else "b.26n", b"NEW-N", None),
                            Output("a.26g" if force else "b.26g", b"NEW-G", None),
                            Output("a.26h" if force else "b.26h", b"NEW-H", None)]
                    with mock.patch.object(engine.os, "replace", interrupt_after):
                        try:
                            write_outputs(outs, self.out, force=force)
                        except KeyboardInterrupt:
                            pass
                    after = {n: Path(self.out, n).read_bytes() for n in os.listdir(self.out)}
                    if len(calls) >= k:           # the interruption happened: nothing changed
                        self.assertEqual(after, before)

    def test_interrupt_at_every_line(self):
        """Round 37 (Sol): an interruption between two Python statements (not only right after a
        rename) undid one step twice and deleted the old file it had just put back. Here a
        KeyboardInterrupt is raised at every line the write code executes, one run per line:
        each run must leave the folder either exactly as it was or holding the whole new set,
        with no old data lost."""
        import linecache
        import sys
        names_ = ("_write_set", "_undo_step", "_undo_all", "_reserve", "write_outputs")
        for force in (True, False):
            k = 0
            while True:
                k += 1
                # a fresh folder per run: an interruption right between mkstemp and fdopen can
                # leave a hidden temporary file open (Windows will not delete it until exit)
                out = os.path.join(self.tmp, f"every-{force}-{k}")
                os.makedirs(out)
                before = {"keep.txt": b"K"}
                if force:
                    before.update({"a.26n": b"OLD-N", "a.26g": b"OLD-G"})
                for n, b in before.items():
                    Path(out, n).write_bytes(b)
                pre = "a" if force else "b"
                outs = [Output(f"{pre}.26n", b"NEW-N", None), Output(f"{pre}.26g", b"NEW-G", None),
                        Output(f"{pre}.26h", b"NEW-H", None)]
                after_ok = dict(before, **{o.name: o.data for o in outs})
                count = [0]

                def tracer(frame, event, arg):
                    if frame.f_code.co_name not in names_ or frame.f_globals.get("__name__") != engine.__name__:
                        return None

                    def local(frame, event, arg):
                        # not on a 'try:' line: an exception raised by a trace function there
                        # skips the enclosing except and finally (CPython 3.12 artifact, shown by
                        # a 12-line toy function); a real Ctrl-C arrives only at calls and loop
                        # jumps (the eval breaker), never on that line
                        if event == "line" and linecache.getline(frame.f_code.co_filename,
                                                                 frame.f_lineno).strip() != "try:":
                            count[0] += 1
                            if count[0] == k:
                                raise KeyboardInterrupt
                        return local
                    return local
                interrupted = False
                sys.settrace(tracer)
                try:
                    write_outputs(outs, out, force=force)
                except KeyboardInterrupt:
                    interrupted = True
                finally:
                    sys.settrace(None)
                visible = {n: Path(out, n).read_bytes() for n in os.listdir(out) if not n.startswith(".")}
                with self.subTest(force=force, line=k):
                    self.assertIn(visible, (before, after_ok))
                if not interrupted:
                    break
            self.assertGreater(k, 20)                 # the code was really walked line by line

    def test_duplicate_names_in_one_set(self):
        with self.assertRaises(InvocationError):
            write_outputs([Output("a.26n", b"1", None), Output("a.26n", b"2", None)], self.out)
        self.assertFalse(os.path.exists(self.out) and os.listdir(self.out))


class ReportNotOverwritten(unittest.TestCase):
    """Like an output, an existing <name>.report.json is not overwritten without --force, and
    it is checked before any output of the input is written."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, MIXED.name)
        shutil.copy(MIXED, self.src)
        self.out = os.path.join(self.tmp, "out")
        self.rep = os.path.join(self.tmp, "rep")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_existing_report(self):
        os.makedirs(self.rep)
        Path(self.rep, MIXED.name + ".report.json").write_bytes(b"{}")
        rc, err = run_cli([self.src, "--to", "3.04", "--out", self.out, "--report", self.rep, "--no-auto-nav"])
        self.assertEqual(rc, 5, err)
        self.assertIn("report", err)
        self.assertFalse(os.path.exists(self.out) and os.listdir(self.out))
        self.assertEqual(Path(self.rep, MIXED.name + ".report.json").read_bytes(), b"{}")
        rc, err = run_cli([self.src, "--to", "3.04", "--out", self.out, "--report", self.rep, "--no-auto-nav",
                           "--force"])
        self.assertEqual(rc, 0, err)
        self.assertNotEqual(Path(self.rep, MIXED.name + ".report.json").read_bytes(), b"{}")


class MergeInputRefusalKeepsItsOutcome(unittest.TestCase):
    """A merge input refused for missing information or as not representable is reported with
    that outcome, not as refused-corrupt."""

    def test_classes(self):
        data = MIXED.read_bytes()
        real = engine.load_bytes
        for exc, outcome in ((MissingInformationError("no channel", missing="x"), REFUSED_MISSING),
                             (NotRepresentableError("nothing to hold"), REFUSED_NOT_REPRESENTABLE)):
            calls = []

            def load(d, lenient=False, exc=exc):
                calls.append(1)
                if len(calls) > 1:              # the first call loads the primary input
                    raise exc
                return real(d, lenient)
            with self.subTest(outcome=outcome), mock.patch.object(engine, "load_bytes", load), \
                    mock.patch.object(engine, "read_path", lambda p: data):
                try:
                    convert_data(data, MIXED.name, Options(target="3.05", merge=["other.rnx"], auto_nav=False))
                except Exception as e:  # noqa: BLE001
                    self.assertEqual(getattr(e, "outcome", None), outcome, repr(e))
                    self.assertIn("merge input other.rnx", str(e))
                else:
                    self.fail("the merge input's refusal was not raised")


if __name__ == "__main__":
    unittest.main()
