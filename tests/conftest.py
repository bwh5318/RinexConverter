"""Opt-in mutation audit of the independent checks (Sol round 13).

With RINEX_MUTATION_AUDIT=<file> set, every compare_obs / compare_nav / compare_met call a
test makes that finds no problem is repeated with each loss claim of its report deleted, and
with its count raised by one. A mutation the check accepts ("caught": false) is a loss it does
not count exactly; every mutation is written to <file> as a JSON line (test, check, mutation,
caught), so the file also shows which loss kinds the suite reaches. Off by default:
it multiplies the comparison work. tools/corpus_run.py-sized inputs are audited the same way
by a scratch script; this covers the loss kinds only unit fixtures have.

Test modules import the checks by name, so the wrappers are installed here, before any test
module is collected.
"""

import copy
import json
import os

_OUT = os.environ.get("RINEX_MUTATION_AUDIT")

if _OUT:
    from tests.independent import compare as _compare

    def _audited(name, real):
        def check(inp, out, report, *a, **k):
            probs = real(inp, out, report, *a, **k)
            if probs or not report.get("losses"):
                return probs
            for cat, e in report["losses"].items():
                for how in ("del", "plus1"):
                    bad = copy.deepcopy(report)
                    if how == "del":
                        del bad["losses"][cat]
                    else:
                        bad["losses"][cat]["count"] = e["count"] + 1
                    try:
                        caught = bool(real(inp, out, bad, *a, **k))
                    except Exception:          # noqa: BLE001 - a crash is not acceptance
                        caught = True
                    with open(_OUT, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps({"test": os.environ.get("PYTEST_CURRENT_TEST", "?"),
                                             "check": name, "mutation": f"{how} {cat}",
                                             "count": e["count"], "caught": caught}) + "\n")
            return probs
        return check

    for _name in ("compare_obs", "compare_nav", "compare_met"):
        setattr(_compare, _name, _audited(_name, getattr(_compare, _name)))
