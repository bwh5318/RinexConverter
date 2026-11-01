"""Conversion report (PLAN §3.6): one JSON document per output.

Entries are aggregated by key so a daily file produces a compact report:
  rules       {rule: {"count": n, "examples": [line numbers]}}
  assumptions [{"category", "detail", "source", "count"}]
  losses      {category: {"count": n, "detail": {...}}}
  repairs     [{"rule", "message", "line"}]
"""

import copy
import json

SCHEMA = "rinexconv-report/1"
MAX_EXAMPLES = 5


class Report:
    def __init__(self):
        self.input = {}
        self.output = {}
        self.source_version = None
        self.target_version = None
        self.file_kind = None
        self.outcome = None
        self.message = None
        self.rules = {}
        self.assumptions = {}
        self.losses = {}
        self.repairs = []
        self.normalisations = {}
        self.warnings = []
        self.validation = None

    # -- recording -----------------------------------------------------------
    def rule(self, name, line=None, n=1):
        r = self.rules.setdefault(name, {"count": 0, "examples": []})
        r["count"] += n
        if line is not None and len(r["examples"]) < MAX_EXAMPLES:
            r["examples"].append(line)

    def assume(self, category, detail, source, n=1):
        key = (category, detail, source)
        a = self.assumptions.setdefault(key, {"category": category, "detail": detail,
                                              "source": source, "count": 0})
        a["count"] += n

    def loss(self, category, n=1, **detail):
        """category is the allowed_losses key, e.g. 'system-not-representable:C'."""
        e = self.losses.setdefault(category, {"count": 0, "detail": {}})
        e["count"] += n
        for k, v in detail.items():
            if isinstance(v, int) and not isinstance(v, bool):
                e["detail"][k] = e["detail"].get(k, 0) + v
            else:
                e["detail"][k] = v

    def repair(self, rule, message, line=None):
        self.repairs.append({"rule": rule, "message": message, "line": line})

    def normalise(self, name, n=1):
        self.normalisations[name] = self.normalisations.get(name, 0) + n

    def warn(self, rule, message):
        self.warnings.append({"rule": rule, "message": message})

    _ENTRIES = ("rules", "assumptions", "losses", "repairs", "normalisations", "warnings")

    def snapshot(self):
        """A copy of the recorded entries, so an attempt that is retried (restore) is not
        counted twice."""
        return {k: copy.deepcopy(getattr(self, k)) for k in self._ENTRIES}

    def restore(self, snap):
        for k, v in snap.items():
            setattr(self, k, copy.deepcopy(v))

    # -- output --------------------------------------------------------------
    def to_dict(self):
        return {
            "schema": SCHEMA,
            "input": self.input,
            "output": self.output,
            "file_kind": self.file_kind,
            "source_version": self.source_version,
            "target_version": self.target_version,
            "outcome": self.outcome,
            "message": self.message,
            "rules": self.rules,
            "assumptions": sorted(self.assumptions.values(),
                                  key=lambda a: (a["category"], a["detail"])),
            "losses": dict(sorted(self.losses.items())),
            "repairs": self.repairs,
            "normalisations": self.normalisations,
            "warnings": self.warnings,
            "validation": self.validation,
        }

    def to_json(self):
        return json.dumps(self.to_dict(), indent=1, sort_keys=False, default=str)

    def summary(self):
        nl = sum(e["count"] for e in self.losses.values())
        return (f"{self.input.get('path', '?')}: RINEX {self.source_version} -> {self.target_version} "
                f"{self.file_kind}: {self.outcome}; {len(self.losses)} loss categories ({nl} items), "
                f"{len(self.assumptions)} assumptions, {len(self.repairs)} repairs"
                + (f"; {self.message}" if self.message else "")
                + (f"; the output keeps {self.validation['errors']} validator error(s) the input "
                   f"already had ({', '.join(self.validation['inherited'])})"
                   if self.validation and self.validation.get("inherited") else ""))
