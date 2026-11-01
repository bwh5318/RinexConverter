"""rinexcore.spec: RINEX specification tables, transcribed by hand as data.

Everything here is data taken from the official RINEX documents in
``specs/text/`` (plain-text extractions of the PDFs in ``specs/``). Every row
cites the spec file and the page from its ``===== page N =====`` marker (or,
for the RINEX 2 texts, which have no page markers, the line number), plus the
printed table number. There is no RINEX parsing logic in this package.

Modules:

- :mod:`rinexcore.spec.obscodes`: satellite systems and observation codes per
  version and system, the pseudo-observables (``I``, ``X``) and the
  blank-attribute rule.
- :mod:`rinexcore.spec.obsheader`: observation-file header labels with their
  per-version status (mandatory, optional, conditional, deprecated), field
  formats and notes.

Ambiguities found while transcribing are listed in ``docs/SPEC_TABLES.md``.
Standard library only (PLAN.md section 0).
"""
