"""diff <=> report check (PLAN §1 clauses 3 and 5a), independent of rinexcore.

compare_obs / compare_nav / compare_met take the input and output payloads
(plain RINEX bytes) and the conversion report (dict) and return a list of
problems; an empty list means every difference is claimed by the report and
every claimed loss actually happened, with equal counts.
"""

import datetime
import re
from collections import Counter, defaultdict
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal

from . import codes as _codes
from .headers import compare_met_meta, compare_nav_meta, compare_obs_meta
from .tokens import has_half_wavelength, lines_of, met_tokens, nav_tokens, obs_tokens, signal_class

_Q7 = Decimal("1e-7")


def _floor7(ep):
    if ep is None:
        return None
    s = ep[5]
    return ep[:5] + ((s // _Q7 * _Q7).normalize(),)


def _bdt_to_gps(inp, target):
    """A RINEX 3/4 input in BDT time, as the GPS-time file a target without BDT must hold: every
    epoch (data and event) and TIME OF FIRST/LAST OBS 14 s later, the time system GPS (BDT is
    14 s behind GPS time: rinex305.txt l.805; the target's time systems: TIME_SYSTEMS_IN).
    Other inputs are returned as they are."""
    from .headers import TIME_SYSTEMS_IN
    import datetime
    L = lines_of(inp)
    if not L or float(L[0][:9]) < 3.02 or "BDT" in TIME_SYSTEMS_IN(target):
        return inp
    ts = next((l[48:51].strip() for l in L if l[60:80].strip() == "TIME OF FIRST OBS"), "")
    if not ts and L[0][40:41] == "C":
        ts = "BDT"                        # the default of a pure BDS file
    if ts != "BDT":
        return inp

    def later(y, mo, d, h, mi, sec):
        sec = Decimal(sec) + 14
        carry = int(sec // 60)
        t = datetime.datetime(int(y), int(mo), int(d), int(h), int(mi)) + datetime.timedelta(minutes=carry)
        return t, sec - 60 * carry
    out = []
    for l in L:
        lab = l[60:80].strip()
        if l.startswith(">") and l[2:6].strip().isdigit():
            t, sec = later(l[2:6], l[7:9], l[10:12], l[13:15], l[16:18], l[18:29])
            l = (f"> {t.year:4d} {t.month:02d} {t.day:02d} {t.hour:02d} {t.minute:02d}"
                 + f"{sec:11.7f}" + l[29:])
        elif lab in ("TIME OF FIRST OBS", "TIME OF LAST OBS") and l[0:6].strip():
            t, sec = later(l[0:6], l[6:12], l[12:18], l[18:24], l[24:30], l[30:43])
            l = (f"{t.year:6d}{t.month:6d}{t.day:6d}{t.hour:6d}{t.minute:6d}{sec:13.7f}"
                 + l[43:48] + "GPS" + l[51:])
        out.append(l)
    return ("\n".join(out) + "\n").encode("latin-1")


def _header_recs(lines):
    out = []
    for l in lines:
        lab = l[60:80].strip()
        if lab == "END OF HEADER":
            break
        out.append((lab, l[:60].ljust(60)))
    return out


def _align_rules(inl, outl, report, target):
    """--align-phases, read from the report and checked against this checker's own reading of
    the files (PLAN section 3.3 rules 2-4): (adjust for obs_tokens or None, 'applied' |
    'removed' | None, problems).
      - rule 2 (3.02-3.05 target): the systems the report's assumptions name (source
        'user:--align-phases ...') must be of unknown alignment in the input (RINEX 2 or 3.00;
        3.01 entries without values; 3.02+ no entry or the system alone), every such system
        with phase types in the output must be named, the input may record no applied
        correction (rule 4), and every output phase code of a named system must have a value in
        the target's table (phase_shift_tables.json); each output phase value is then moved
        back by that value;
      - rule 3 (3.00 target, rule OBS.PHASE.UNALIGN-3.00): each output phase value of a code
        and satellite an input header SYS / PHASE SHIFT entry gives a non-zero value for is
        moved back up by it, the code's values stored under the output's own SYS / SCALE FACTOR
        (a finer factor keeps a 5-decimal correction exact: _unalign_scale_check).
    The rule is chosen by the report's table rule (OBS.PHASE.ALIGN-A19-3.02, -A23-3.03 to
    -A23-3.05) or align assumptions for rule 2 and OBS.PHASE.UNALIGN-3.00 for rule 3, never by a
    name's prefix: OBS.PHASE.ALIGN-CLIPPED comes with either (Astra verify round V2: a 3.00
    conversion that clipped was checked as rule 2)."""
    from .headers import align_systems, phase_entries, table_shift
    p = []
    sv = report["source_version"]
    rules = report.get("rules") or {}
    aligned = align_systems(report)
    table_rule = [k for k in rules if re.fullmatch(r"OBS\.PHASE\.ALIGN-A(19-3\.02|23-3\.0[345])", k)]
    lost = {k.split(":")[1] for k in report.get("losses", {}) if k.startswith(("system-not-representable:",
                                                                               "system-removed-unresolvable:"))}
    ent = phase_entries(_header_recs(inl)) if "3.01" <= sv < "4" else []
    applied = [e for e in ent if e[1] and e[2] is not None and e[2] != 0]
    out_phase = defaultdict(list)
    cur = None
    for lab, c in _header_recs(outl):
        if lab == "SYS / # / OBS TYPES":
            if c[:1].strip():
                cur = c[0]
            out_phase[cur] += [x for x in c[7:60].split() if x[:1] == "L"]

    def unknown(s):
        if sv < "3.01":
            return True
        if sv >= "4":
            return False
        mine = [e for e in ent if e[0] == s]
        return all(e[2] is None for e in mine) if sv < "3.02" else all(not e[1] for e in mine)
    if (aligned or table_rule) and "OBS.PHASE.UNALIGN-3.00" in rules:
        p.append(f"the report gives both an alignment table rule {table_rule} and OBS.PHASE.UNALIGN-3.00")
    if aligned or table_rule:
        want = {"3.02": "OBS.PHASE.ALIGN-A19-3.02"}.get(target, f"OBS.PHASE.ALIGN-A23-{target}")
        if table_rule != [want]:
            p.append(f"--align-phases to RINEX {target}: the report's table rules are {table_rule}, "
                     f"not [{want!r}]")
        if not "3.02" <= target <= "3.05":
            p.append(f"--align-phases shifts reported for a RINEX {target} target (3.02-3.05 have tables)")
        if applied:
            p.append(f"--align-phases on an input whose SYS / PHASE SHIFT records applied corrections "
                     f"{[(e[0], e[1], str(e[2])) for e in applied][:3]} (PLAN 3.3 rule 4: never twice)")
        for s in sorted(aligned):
            if not unknown(s):
                p.append(f"--align-phases shifted {s}, whose alignment the RINEX {sv} input records")
            nogo = [c for c in out_phase.get(s, []) if table_shift(target, s, c) is None]
            if nogo:
                p.append(f"--align-phases for {s}: the RINEX {target} table gives no value for {nogo}")
            # a RINEX 2 code names no tracking mode: an attribute from the converter's table or
            # receiver rule (not the user's --overrides) may not decide a shift where the table's
            # value differs between the attributes the code could stand for (review round 39)
            for x in report.get("assumptions", []) or []:
                if x.get("category") != f"obs-code-attribute:{s}" or x.get("source") == "override":
                    continue
                v2, _, v3 = (x.get("detail") or "").partition("->")
                if v3 in out_phase.get(s, []):
                    cands = [c for c in _codes.codes(target, s) if c[:2] == v3[:2]]
                    if len({table_shift(target, s, c) for c in cands}) > 1:
                        p.append(f"--align-phases for {s} {v2}: written {v3} by {x.get('source')}, but the "
                                 f"table's shift differs among {cands}: a guessed shift")
        for s, codes in out_phase.items():
            if codes and s not in aligned and unknown(s):
                p.append(f"--align-phases left {s} unshifted although its alignment is unknown in the input")
        # the output code of an input phase code: a RINEX 2 code's from the report's attribute
        # assumption, a RINEX 3 code itself (BeiDou B1I in the target's band: 1 in 3.02, else 2)
        v2map = defaultdict(dict)
        for x in report.get("assumptions", []) or []:
            if (x.get("category") or "").startswith("obs-code-attribute:"):
                v2, _, v3 = (x.get("detail") or "").partition("->")
                v2map[x["category"].split(":", 1)[1]][v2] = v3

        def adjust(s, code, sat, ep=None, value=None, fin=None, slip=False, scope=0):
            if slip or s not in aligned or s in lost:
                return None
            if sv < "3":
                tcode = v2map[s].get(code)
                if tcode is None:
                    return None
            elif s == "C" and code[1:2] in "12" and code[2:3] in "IQX":
                tcode = code[0] + ("1" if target == "3.02" else "2") + code[2]
            else:
                tcode = code
            d = table_shift(target, s, tcode)
            return (d, tcode, adjust.factor(ep, sat, tcode, False)) if d else None
        adjust.factor = lambda ep, sat, c, slip: None
        return adjust, "applied", p
    if "OBS.PHASE.UNALIGN-3.00" in rules:
        if target != "3.00":
            p.append(f"recorded phase corrections removed for a RINEX {target} target (rule 3 is for 3.00)")
        # every entry counts, zeros and codes alone (no correction) too, per satellite: one
        # satellite given two different values is no correction the record states (review
        # round 39: a zero entry for G12 was dropped before the other entry was applied)
        recs = defaultdict(list)
        for i, (s, code, v, sats) in enumerate(ent):
            if code:
                recs[(s, code)].append((v if v is not None else Decimal(0), set(sats), i))
        clash = set()

        def adjust(s, code, sat, ep=None, value=None, fin=None, slip=False, scope=0):
            if s in lost or (s, code) not in recs:
                return None
            cover = [] if slip else [(v, i) for v, sats, i in recs[(s, code)] if not sats or sat in sats]
            ds = {v for v, i in cover}
            if len(ds) > 1:
                if (s, code, sat) not in clash:
                    clash.add((s, code, sat))
                    p.append(f"{s} {code} {sat}: the input records two corrections {sorted(map(str, ds))}, "
                             "yet one was removed")
                return None
            d = next(iter(ds)) if ds else Decimal(0)
            fin = Decimal(fin or 1)
            fout = adjust.factor(ep, sat, code, slip)
            k = (fout or fin) / fin               # the output's factor over the input's
            if value is not None and any(v for v, sats, i in recs[(s, code)]):
                # what a finer factor must hold (_unalign_scale_check): every value of a
                # corrected code in one scope of its factor (obs_tokens: the header, then each
                # event naming the code or all its system's types), slips (flag 6) too, less the
                # correction that applies to it
                x = value - d * fin
                if not adjust.frozen:
                    st = adjust.stats.setdefault((s, code, scope), [fin, 0, x, x])
                    st[1] = max(st[1], -x.normalize().as_tuple().exponent)
                    st[2], st[3] = max(st[2], x), min(st[3], x)
                seen = adjust.seen.setdefault((s, code, scope), [False, Decimal(1)])
                seen[0] = seen[0] or x * k != (x * k).quantize(Decimal("0.001"))
                seen[1] = max(seen[1], k)
            if k != 1:
                adjust.scaled += 1                # (OBS.PHASE.UNALIGN-SCALE counts these)
            if slip:
                return None
            if d:
                # (an entry is undone once it changes a value the output keeps: Astra round 39)
                adjust.used.update(i for v, i in cover)
            if not d and k == 1:
                return None
            return -d, code, fout

        def restart():
            """Before the input is read again (columns claimed lost left out): what the output
            holds is counted again; the values a factor must hold stay those of every column,
            as the converter chooses its factor from the whole input."""
            adjust.used.clear()
            adjust.seen.clear()
            adjust.scaled = 0
            adjust.frozen = True
        adjust.used = set()
        adjust.stats = {}
        adjust.seen = {}
        adjust.scaled = 0
        adjust.frozen = False
        adjust.restart = restart
        adjust.factor = lambda ep, sat, c, slip: None
        return adjust, "removed", p
    return None, None, p


def _align_counts(acodes, akind, report):
    """The report's counts must be exactly the values this checker moved: phase-shift-applied /
    phase-shift-removed per system, code and shift (the removed one is the recorded value),
    phase-shift-clipped, and the losses phase-align-precision / phase-unalign-precision."""
    p = []
    norms = report.get("normalisations") or {}
    want = Counter()
    for k, n in norms.items():
        if k.startswith(("phase-shift-applied:", "phase-shift-removed:")):
            kind, s, code, d = k.split(":", 3)
            want[(kind.rsplit("-", 1)[1], s, code, Decimal(d).normalize())] += n
    got = Counter()
    for (s, code, delta), n in getattr(acodes, "adjusted", Counter()).items():
        got[(akind, s, code, (delta if akind == "applied" else -delta).normalize())] += n
    if want != got:
        p.append(f"phase values shifted {dict(got)}, report claims {dict(want)}")
    wclip = Counter({tuple(k.split(":")[1:3]): n for k, n in norms.items() if k.startswith("phase-shift-clipped:")})
    gclip = Counter(getattr(acodes, "adjust_clipped", Counter()))
    if +wclip != +gclip:
        p.append(f"shifted phases past F14.3 clipped by 1e9 {dict(gclip)}, report claims {dict(wclip)}")
    prefix = {"applied": "phase-align-precision:", "removed": "phase-unalign-precision:"}.get(akind, "-")
    losses = report.get("losses") or {}
    wprec = Counter({tuple(k.split(":")[1:3]): e["count"] for k, e in losses.items() if k.startswith(prefix)})
    other = [k for k in losses if k.startswith(("phase-align-precision:", "phase-unalign-precision:"))
             and not k.startswith(prefix)]
    if other:
        p.append(f"report claims {other}, which this conversion's shifts cannot cause")
    gprec = Counter(getattr(acodes, "adjust_rounded", Counter()))
    if +wprec != +gprec:
        p.append(f"shifted phases rounded to 3 decimals {dict(gprec)}, report claims {dict(wprec)}")
    return p


_FACTORS = (1, 10, 100, 1000)     # SYS / SCALE FACTOR values (rinex300.txt Table A1 p.28)
_F14_3 = (Decimal("-999999999.999"), Decimal("9999999999.999"))


def _unalign_scale_check(adjust, report):
    """--align-phases to 3.00 (rule 3): a correction F8.5 has up to 5 decimals (rinex305.txt
    Table A2 p.57), so a value less it may need more than F14.3's 3; 3.00 stores finer values
    under SYS / SCALE FACTOR ('to increase resolution by 10, 100, etc', rinex300.txt section 5.5
    p.12; 1, 10, 100 or 1000, Table A1 p.28). Per system, code and scope of its factor (the
    header, then from each flag 2-5 event whose SYS / SCALE FACTOR names the code or all its
    system's types, rinex305.txt section 6.5: this checker's own reading of the input; Astra
    verify 2, W1: grouped by input factor, a scope where no factor works hid one where a factor
    did), from every value of the code (all satellites; flags 0, 1 and 6) less the correction
    that applies to it: where some k makes the input factor times k allowed, every such value
    exact at 3 decimals once multiplied by k, and every one fitting F14.3, no output value may
    have been rounded (a rounding a factor avoids is a loss, claimed or not: Astra verify round
    V1) and the output factor must be the input's times the smallest such k; where none does,
    the input's own. And OBS.PHASE.UNALIGN-SCALE counts the values (flags 0, 1, 6) written under
    a factor other than the input's."""
    p = []
    for (s, code, scope), (fin, dec, hi, lo) in sorted(adjust.stats.items(), key=str):
        best = next((k for k in _FACTORS if fin * k in _FACTORS and dec <= 2 + len(str(k))
                     and _F14_3[0] <= lo * k and hi * k <= _F14_3[1]), None)
        rounded, kmax = adjust.seen.get((s, code, scope), (False, Decimal(1)))
        where = "the header" if not scope else f"the event at input line {scope}"
        if best is None:
            if kmax != 1:
                p.append(f"{s} {code} ({where}): written under SYS / SCALE FACTOR {fin * kmax}, although "
                         f"no allowed factor holds every value (the input's {fin} stays)")
            continue
        if rounded:
            p.append(f"{s} {code} ({where}): values less their recorded correction rounded to 3 decimals, "
                     f"although SYS / SCALE FACTOR {fin * best} would hold every one exactly (input factor {fin})")
        if kmax > best:
            p.append(f"{s} {code} ({where}): written under SYS / SCALE FACTOR {fin * kmax}, where "
                     f"{fin * best} holds every value exactly (the smallest)")
    n = ((report.get("rules") or {}).get("OBS.PHASE.UNALIGN-SCALE") or {}).get("count", 0)
    if n != adjust.scaled:
        p.append(f"{adjust.scaled} phase values written under a finer factor than the input's, "
                 f"report claims {n} OBS.PHASE.UNALIGN-SCALE")
    return p


def compare_obs(inp, out, report, tin=None):
    problems = []
    target = report["target_version"]
    shifted = _bdt_to_gps(inp, target)
    if shifted is not inp:
        inp, tin = shifted, None          # (a cached tokenisation is of the unshifted input)
    exact = report["source_version"] >= "3" and target >= "3"
    inl = lines_of(inp)
    v3_lli = report["source_version"] < "3" <= target and has_half_wavelength(inl)
    if v3_lli:
        tin = obs_tokens(inl, v3_lli=True)
    elif isinstance(tin, dict):              # a cache shared across targets: {exact: tokens}
        if exact not in tin:
            tin[exact] = obs_tokens(inl, exact=exact)
        tin = tin[exact]
    elif tin is None or exact:
        tin = obs_tokens(inl, exact=exact)
    rin, cin = tin
    adjust, akind, aprob = _align_rules(inl, lines_of(out), report, target)
    acodes = None
    if adjust is not None:
        # --align-phases: the input's phase values moved by the shift the report's assumptions
        # (or the input's own records, to 3.00) and this checker's own tables say, as the
        # output must hold them, and phases compared by value
        # (the output first: each value moved is stored under the output's own factor for it)
        outfac = {}
        rout, cout = obs_tokens(lines_of(out), exact=exact, norm=True, factors=outfac)
        adjust.factor = lambda ep, sat, c, slip: outfac.get((ep, sat, c, slip))
        tin = obs_tokens(inl, v3_lli=v3_lli, exact=exact, adjust=adjust)
        rin, cin = tin
        acodes = cin
    else:
        rout, cout = obs_tokens(lines_of(out), exact=exact)
    losses = report.get("losses", {})
    # text in columns no field covers (only --lenient converts such an input): dropped, one
    # claim per input line, and none in the output (round 32: cut at column 80 unreported)
    c_skip = losses.get("data-text-dropped", {}).get("count", 0)
    if getattr(cin, "skipped", 0) != c_skip:
        problems.append(f"{getattr(cin, 'skipped', 0)} input data lines hold text no field covers, "
                        f"report claims {c_skip} data-text-dropped")
    if getattr(cout, "skipped", 0):
        problems.append(f"{cout.skipped} output data lines hold text no field covers")
    lost_sys = {k.split(":")[1] for k in losses if k.startswith(("system-not-representable:",
                                                                 "system-removed-unresolvable:"))}
    lost_codes = {}
    for k, e in losses.items():
        if k.startswith(("obs-code-not-representable:", "obs-code-collapsed:")):
            _, s, code = k.split(":")
            lost_codes[(s, code)] = e["count"]
    # A code a type list names twice loses either all its values or, when its columns collapse
    # into one, only those of the columns after the first.
    collapsed ={(k.split(":")[1], k.split(":")[2]) for k in losses if k.startswith("obs-code-collapsed:")}
    svk_in = "%.2f" % float(report["source_version"])

    def sig(s, code):
        return signal_class(svk_in, s, code, exact)

    collapse_expect = {}
    drop = {}
    for (s, code), n in lost_codes.items():
        if (s, code) not in collapsed:
            drop[(None, s, code)] = "all"          # not representable: every column of it
    # A collapse needs a collision in the type list in force: columns of one signal that hold
    # values or flag-only fields (a blank value with LLI/SSI is data the converter keeps, so
    # it can win the column; its flags are compared below), of which the output keeps one,
    # or the same code listed twice (its later columns go). Only those lists' values are
    # lost, and the claim counts values and flag-only fields alike. The column kept is
    # decided per list, as a code may win in one list and lose in another (generator round
    # 22: SBAS S5X kept against S5Q in the header's list, dropped against S5I in a flag-4
    # one): it is the only column not claimed collapsed, or, where all are claimed, the
    # choice that makes every claim's count add up. Which column the converter prefers
    # (codemap.collapse_rank) is policy and not checked; the tokens below show that the
    # kept column holds its own values.
    def held(k, s, c):
        return cin.by_state[(k, s, c)] + cin.flags_by_state[(k, s, c)]
    groups = []                                # (list, system, colliding codes with data)
    for k, lst in enumerate(getattr(cin, "lists", [])):
        for s, codes_k in lst.items():
            if s == "*":
                continue
            by_sig = defaultdict(list)
            for c in dict.fromkeys(codes_k):
                if held(k, s, c) and not ((s, c) in lost_codes and (s, c) not in collapsed):
                    by_sig[sig(s, c)].append(c)
            groups += [(k, s, tuple(g)) for g in by_sig.values() if len(g) > 1]
    fixed, open_ = {}, []
    for k, s, g in groups:
        free = [c for c in g if (s, c) not in collapsed]
        if len(free) == 1:
            fixed[(k, s, g)] = free[0]
        elif not free:
            open_.append((k, s, g))
        # (two or more not claimed: the output holds one, the tokens show the other missing)

    def lost_by(winners, out_drop=None):
        """Values each collapsed code loses when `winners` are the columns kept."""
        losers = {(k, s, c) for (k, s, g), w in winners.items() for c in g if c != w}
        exp = Counter()
        for (s, code) in collapsed:
            for k, lst in enumerate(getattr(cin, "lists", [])):
                codes_k = lst.get(s, lst.get("*", []))
                if code not in codes_k or not held(k, s, code):
                    continue
                if (k, s, code) in losers:
                    exp[(s, code)] += held(k, s, code)
                    if out_drop is not None:
                        out_drop[(k, s, code)] = "all"
                elif codes_k.count(code) > 1:
                    exp[(s, code)] += cin.later_by_state[(k, s, code)] + cin.flags_later_by_state[(k, s, code)]
                    if out_drop is not None:
                        out_drop[(k, s, code)] = "later"
        return exp
    choice = dict(fixed)
    if open_:
        import itertools
        first = None
        for combo in itertools.islice(itertools.product(*[g for k, s, g in open_]), 4096):
            w = dict(fixed)
            w.update(zip(open_, combo))
            first = first or w
            exp = lost_by(w)
            if all(exp[(s, c)] == lost_codes[(s, c)] for (s, c) in collapsed):
                choice = w
                break
        else:
            choice = first
    if target < "3" <= report["source_version"]:
        # RINEX 3 -> 2: the column kept must be the best by the user-confirmed priority
        # (docs/DECISIONS.md, confirmed 2026-11-01 answer 7; attribute_defaults.json), where
        # that text orders the two attributes (verify round: the policy was not checked)
        from .headers import ATTR_DEFAULTS

        def rank(order, attr):
            for r, run in enumerate(order.split("|")):
                if attr in run:
                    return r, run.index(attr)
            return None
        for (k, s, g), w in choice.items():
            for c in g:
                if c == w or len(c) != 3 or len(w) != 3 or c[1] != w[1]:
                    continue
                order = ATTR_DEFAULTS["collapse_priority"].get(s + w[1])
                rw, rc = (rank(order, w[2]), rank(order, c[2])) if order else (None, None)
                if rw is not None and rc is not None and rw > rc:
                    problems.append(f"{s} {sig(s, w)}: the output keeps {w} over {c}, against the confirmed "
                                    f"RINEX 3 -> 2 priority {order}")
    for (s, code), exp in lost_by(choice, drop).items():
        collapse_expect[(s, code)] = exp
    for (s, code), n in lost_codes.items():
        if (s, code) not in collapsed:
            continue
        exp = collapse_expect.get((s, code), 0)
        if not exp:
            problems.append(f"report claims {n} obs-code-collapsed:{s}:{code}, but no type list has "
                            f"another column of that signal ({sig(s, code)}) to collapse it into")
    if drop:
        # the input without the columns claimed lost: what is left must be in the output as it
        # is, so a kept column holds its own signal's values (not those of the one dropped)
        if adjust is not None and akind == "removed":
            adjust.restart()                  # (counted again without the dropped columns)
        rin, dcodes = obs_tokens(inl, v3_lli=v3_lli, exact=exact, drop=drop, adjust=adjust)
        if adjust is not None:
            acodes = dcodes
    if adjust is not None:
        problems += aprob                 # (after the tokens: adjust adds what it finds)
        problems += _align_counts(acodes, akind, report)
        if akind == "removed":
            problems += _unalign_scale_check(adjust, report)
        elif "OBS.PHASE.UNALIGN-SCALE" in (report.get("rules") or {}):
            problems.append("the report gives OBS.PHASE.UNALIGN-SCALE for a conversion that adds shifts")
    elif any(k.startswith(("phase-shift-applied:", "phase-shift-removed:", "phase-shift-clipped:"))
             for k in report.get("normalisations") or {}) or any(
            k.startswith(("phase-align-precision:", "phase-unalign-precision:")) for k in losses) or any(
            k.startswith(("OBS.PHASE.ALIGN-", "OBS.PHASE.UNALIGN-")) for k in report.get("rules") or {}):
        problems.append("the report claims phase shifts, but no --align-phases rule or assumption")
    else:
        problems += aprob
    if target < "4.02":
        merged = {}
        for (ep, sat, flag), items in rin.items():
            k = (_floor7(ep), sat, flag)
            merged[k] = items if k not in merged else tuple(sorted(merged[k] + items))
        rin = merged
    if target < "3" <= report["source_version"]:
        # RINEX 2 has no SYS / SCALE FACTOR: a scaled value (tokens hold value / factor) is
        # written in F14.3, rounded half-even; one that rounds to 0.000 is missing
        # (rinex211.txt ~1288). Each rounding of a value the output keeps (its system and
        # signal are not claimed lost) is a loss the report claims under that signal.
        # (rin no longer holds the columns claimed lost)
        svk = "%.2f" % float(report["source_version"])
        n_round = Counter()
        new = {}
        for k, items in rin.items():
            out_items = []
            for (c, v, lli, ssi) in items:
                if "." in v and len(v.split(".")[1]) > 3 and k[1][0] not in lost_sys:
                    n_round[c] += 1
                    q = Decimal(v).quantize(Decimal("0.001"), rounding=ROUND_HALF_EVEN)
                    if not q:
                        if (lli + ssi).strip():
                            out_items.append((c, "", lli, ssi))     # missing, flags kept
                        continue
                    v = f"{q:.3f}"
                out_items.append((c, v, lli, ssi))
            new[k] = tuple(sorted(out_items))
        rin = new
        claimed = Counter()
        for k, e in losses.items():
            if k.startswith("scale-factor-rounding:"):
                _, s_, code = k.split(":")
                claimed[signal_class(svk, s_, code)] += e["count"]
        for c in set(n_round) | set(claimed):
            if claimed[c] != n_round[c]:
                problems.append(f"{n_round[c]} scaled {c} values need rounding for RINEX {target}, "
                                f"report claims {claimed[c]} scale-factor-rounding")
    if "lli-bit2-meaning-differs" in losses:
        # LLI bit 2 is anti-spoofing in 2.x, undefined in 3.00, BOC tracking from 3.01: a
        # converter that does not carry it across clears it (4->0, 5->1, 6->2, 7->3)
        clear = {"4": "0", "5": "1", "6": "2", "7": "3"}
        n = 0
        new = {}
        for k, items in rin.items():
            if k[1][0] in lost_sys:
                new[k] = items              # the whole system goes (counted below)
                continue
            out_items = []
            for (c, v, lli, ssi) in items:
                if lli in clear:
                    lli = clear[lli]
                    n += 1
                out_items.append((c, v, lli, ssi))
            new[k] = tuple(sorted(out_items))
        rin = new
        # rin no longer holds the columns claimed lost: every field left with bit 2 set
        # (flag-only ones included) is one change the claim must count (Sol round 10)
        if losses["lli-bit2-meaning-differs"]["count"] != n:
            problems.append(f"report claims {losses['lli-bit2-meaning-differs']['count']} LLI bit-2 "
                            f"changes, the output keeps {n} fields with bit 2 set")
    if "flags-on-missing-value-dropped" in losses:
        # Compact RINEX 1.0 cannot hold LLI/SSI on a blank value (docs/HATANAKA.md): every
        # flag-only field the output would hold goes, and the claim counts them
        n = 0
        new = {}
        for k, items in rin.items():
            if k[1][0] in lost_sys:
                new[k] = items              # the whole system goes (counted below)
                continue
            kept = tuple(t for t in items if t[1] != "")
            n += len(items) - len(kept)
            new[k] = kept
        rin = new
        if losses["flags-on-missing-value-dropped"]["count"] != n:
            problems.append(f"report claims {losses['flags-on-missing-value-dropped']['count']} "
                            f"flags-on-missing-value-dropped, the output would hold {n} flag-only fields")
    extra = Counter()
    miss_by_sys = Counter()
    for key in set(rin) | set(rout):
        a = rin.get(key, ())
        b = rout.get(key, ())
        if a == b:
            continue
        ca, cb = Counter(a), Counter(b)
        for t, n in (cb - ca).items():
            extra[(key, t)] += n
        miss_by_sys[key[1][0]] += sum((ca - cb).values())
    if extra:
        n = sum(extra.values())
        problems.append(f"{n} output tokens not in the input (moved/changed values), e.g. {list(extra)[:3]}")
    # the columns claimed lost are already left out of rin; a dropped system's values are
    # the only ones still missing (counted from rin itself, so a dropped column of that system
    # is not counted twice)
    exp_by_sys = Counter()
    for key, items in rin.items():
        if key[1][0] in lost_sys:
            exp_by_sys[key[1][0]] += len(items)
    # a dropped system's claim counts its satellite records (Sonnet round 11: the count was
    # never compared)
    for k, e in losses.items():
        if k.startswith(("system-not-representable:", "system-removed-unresolvable:")):
            s = k.split(":")[1]
            if e["count"] != cin.records[s]:
                problems.append(f"report claims {e['count']} {k}, the input has {cin.records[s]} "
                                f"satellite records of {s}")
    for s in set(miss_by_sys) | set(exp_by_sys):
        if miss_by_sys[s] != exp_by_sys[s]:
            problems.append(f"system {s}: {miss_by_sys[s]} input tokens missing from the output, "
                            f"report claims {exp_by_sys[s]}")
    for (s, code), n in lost_codes.items():
        if (s, code) in collapsed:
            have = collapse_expect.get((s, code), 0)
            if have and have != n:
                problems.append(f"report claims {n} obs-code-collapsed:{s}:{code}, the colliding "
                                f"columns hold {have} values")
            continue
        have = cin.get((s, code), 0) + cin.flags.get((s, code), 0)
        if have != n:
            problems.append(f"report claims {n} lost {s}:{code} values and flag-only fields, the "
                            f"input has {have}")
    # Declared types are carried or claimed, values or not, within one layout (2 -> 2,
    # 3/4 -> 3/4), in a file without data, and in a type list no data epoch uses: a type of
    # such a list that no output list holds is claimed, and so is a declared system the
    # output lacks (the claim of a type or system without values, count 0, could be deleted
    # unnoticed: Sol round 13 audit). Across layouts a list that data use is rebuilt from
    # its columns that hold data; a dropped column with values or flags shows as missing
    # tokens above. The systems a list declares: RINEX 3/4 its own (only those with data
    # for a RINEX 2 target, unless the file has none); RINEX 2 the systems with data, or
    # the header's system letter (M read as G) when there are none.
    sv = report["source_version"]
    same_layout = (sv < "3") == (target < "3")
    data_sys = {x for x, n in cin.records.items() if n}
    hs = (inl[0][40:41].strip() or "G") if inl else "G"
    svk_out = "%.2f" % float(target)
    out_lists = {}                       # sys (or '*', a RINEX 2 list) -> codes in any output list
    for lst in cout.lists:
        for s, codes in lst.items():
            out_lists.setdefault(s, set()).update(codes)
    unclaimed = set()
    # each input list is rewritten as the output list at the same place (header, then each
    # flag-4 list in order), so a declared type must be held by that list: the classes of all
    # output lists together let another list's S1W stand for an S1S (GPS L1C, no RINEX 2
    # code) claimed and then deleted unnoticed (generator audit, round 23). Where the lists
    # do not line up (a header list taken from a later one: OBS.HDR.TYPES-FROM-FIRST-DATA-
    # LIST), all output lists count, as before.
    paired = len(cout.lists) == len(cin.lists) and \
        "OBS.HDR.TYPES-FROM-FIRST-DATA-LIST" not in (report.get("rules") or {})
    for k, lst in enumerate(cin.lists):
        if not (same_layout or not data_sys or not cin.records_by_list[k]):
            continue
        if sv >= "3":
            syss = set(lst) if (target >= "3" or not data_sys) else data_sys & set(lst)
        else:
            syss = data_sys or {"G" if hs == "M" else hs}
        if paired:
            outk = {s: set(c) for s, c in cout.lists[k].items()}
        else:
            outk = out_lists
        for s in syss - lost_sys:
            if s not in _codes.systems(target):
                unclaimed.add(f"{s} (system)")
                continue
            # a RINEX 2 output's one list holds a code for a system only if the target defines
            # it for that system (GPS L2 is no SBAS L2), unless the version is unchanged: then
            # a non-standard code is carried as written
            held = {signal_class(svk_out, s, c, exact) for c in outk.get(s, outk.get("*", ()))
                    if s in outk or sv == target or _codes.valid(target, s, c)}
            for code in lst.get(s, lst.get("*", [])):
                # RINEX 2's one list declares a code for every system, but only where the
                # version defines it for the system does it name a signal (SBAS P2 does not:
                # rinex211.txt section 10.1.1); values under such a column are counted with
                # the tokens above, and a claim of them is allowed (allowed.py)
                # (a system the version does not define at all, e.g. SBAS in 2.00, names none)
                if sv < "3" and not _codes.source_valid(sv, s, code):
                    continue
                if (s, code) not in lost_codes and sig(s, code) not in held:
                    unclaimed.add(f"{s}:{code}")
    if unclaimed:
        problems.append(f"input types {sorted(unclaimed)[:6]} are in no output type list and no "
                        "obs-code-not-representable / obs-code-collapsed / system-not-representable "
                        "claim names them")
    # A satellite record of a system left with no target column under its type list is no
    # record (each value claimed above): within one layout every declared type the target
    # cannot hold is claimed, across layouts the columns that hold data count (Sol round 21:
    # an epoch of such records only is emptied, claimed epoch-emptied-by-system-removal)
    def column(k, s, c):
        if (s, c) in lost_codes and (s, c) not in collapsed:
            return False
        if not same_layout and not (cin.by_state[(k, s, c)] or cin.flags_by_state[(k, s, c)]):
            return False
        # RINEX 2 -> 2: a code the target does not define for this system is no column of it
        return not (sv < "3" and target < "3" and sv != target and not _codes.valid(target, s, c))

    kept_sys = (data_sys or {"G" if hs == "M" else hs}) - lost_sys

    def has_columns(k, s):
        lst = cin.lists[k]
        if target < "3":
            # RINEX 2: one list for every system, so a kept system's record stays, blank where
            # its own columns are gone (Sol round 22: a GLONASS C3I/L3I record, to 2.11), while
            # the list has any column at all (else it is left out: OBS.HDR.TYPES-FROM-FIRST-
            # DATA-LIST, a 2.11 C2/C5 list to 2.10)
            return any(column(k, s2, c) for s2 in kept_sys for c in lst.get(s2, lst.get("*", [])))
        return any(column(k, s, c) for c in lst.get(s, lst.get("*", [])))
    by_epoch = defaultdict(list)
    has = {}                                    # (list, system) -> has_columns: per record
    for ek, sat, k in cin.record_lists:
        key = (k, sat[0])
        if key not in has:
            has[key] = has_columns(k, sat[0])
        by_epoch[ek].append(sat[0] in lost_sys or not has[key])
    type_emptied = {(_norm_time(ek[0]), ek[1]) for ek, gone in by_epoch.items() if gone and all(gone)}
    problems.extend(compare_obs_meta(inp, out, report, type_emptied=type_emptied,
                                     unalign_undone=len(adjust.used) if akind == "removed" else None))
    return problems


def _norm_time(t):
    return None if t is None else tuple(t[:5]) + (Decimal(t[5]).normalize(),)


GLO_LINE5_UNKNOWN = [None, Decimal("999999999.999").normalize(), Decimal(15)]

# BeiDou: D1 is the MEO/IGSO message, D2 the GEO one (rinex_4.00.txt p.36, message-type table,
# lines 1885-1887; its example writes 'EPH C05 D2'). Which PRNs are GEO is not in the RINEX
# specs: C01-C05 and C59-C63 are the BDS GEO slots, the same list as navconv.BDS_GEO, so this
# check does not test that list, only that it is applied.
_BDS_GEO = {1, 2, 3, 4, 5, 59, 60, 61, 62, 63}


def v4_message(sat, vals):
    """The RINEX 4 message type a RINEX 2/3 EPH record must get, written here from the spec
    (not from the converter): GPS/QZSS/NavIC LNAV, GLONASS FDMA, SBAS SBAS, BeiDou D1/D2 by
    orbit type, Galileo from the data-source bitmask of BROADCAST ORBIT 5 field 2
    (rinex305.txt Table A8: bit 0 I/NAV E1-B, bit 1 F/NAV E5a-I, bit 2 I/NAV E5b-I; with
    both kinds set, bits 8/9 tell whose clock it is: 8 E5a,E1 = F/NAV, 9 E5b,E1 = I/NAV).
    A set of acceptable types (empty: the record must not reach a RINEX 4 output)."""
    s = sat[0]
    if s in "GJI":
        return {"LNAV"}
    if s == "R":
        return {"FDMA"}
    if s == "S":
        return {"SBAS"}
    if s == "C":
        return {"D2" if int(sat[1:]) in _BDS_GEO else "D1"}
    if s == "E":
        v = vals[20] if len(vals) > 20 else None
        if v is None:
            return set()
        bits = int(v)
        inav, fnav = bool(bits & 5), bool(bits & 2)
        if inav != fnav:
            return {"INAV" if inav else "FNAV"}
        c8, c9 = bool(bits & 256), bool(bits & 512)
        if c8 != c9:
            return {"FNAV" if c8 else "INAV"}
        return set()
    return set()


def _dec(t):
    t = t.strip()
    return Decimal(t.replace("D", "E").replace("d", "e")) if t else None


def _near(a, b):
    """a (an E19.12 input value) written as b in D12.4: 4 significant digits, so within half a
    unit of b's 4th digit (blank, zero and missing alike)."""
    if not a or not b:
        return not a and not b
    return abs(a - b) <= Decimal(5).scaleb(b.adjusted() - 4)


# ---------------------------------------------------------------------------
# value changes the specs define between navigation versions (review round 32), written here
# from the spec text, independently of the converter
# ---------------------------------------------------------------------------
_DAY = Decimal(86400)
_SUNDAY0 = datetime.date(1980, 1, 6)          # GPS (and the UTC weeks counted alike) start on Sunday


def _floor_day(v):
    """v modulo 86400 (also for a negative v): the seconds of day of a seconds-of-week value."""
    return v - _DAY * (v / _DAY).to_integral_value(rounding=ROUND_FLOOR)


def _dow(day):
    return (day.weekday() + 1) % 7


def _near_day(toc, sod):
    """Day offset (0, -1, +1; ties to Toc's own day) that puts `sod` nearest the epoch toc."""
    t = Decimal(toc[3] * 3600 + toc[4] * 60) + Decimal(toc[5])
    best = None
    for k in (0, -1, 1):
        d = abs(sod + _DAY * k - t)
        if best is None or d < best[0]:
            best = (d, k)
    return best[1]


def glo_tk_week(toc, tk):
    """(value, other week) of a RINEX 2 GLONASS tk, '0 .le. tk .lt. 86400 sec of day UTC'
    (rinex211.txt Table A11 l.1718), in RINEX 3/4: '(tk+nd*86400) in seconds of the UTC week'
    (rinex300.txt Table A9 l.2425; rinex305.txt Table A10 p.74; rinex_4.02.txt Table A15 p.87):
    tk on the day nearest Toc, counted from the start of Toc's UTC week (the user's decision of
    2026-11-02, 'Toc week', as the GEO tables say for SBAS: rinex211.txt l.910-915), so it may
    be negative or 604800 and more; other week: the frame is not in Toc's week."""
    day = datetime.date(*toc[:3])
    nd = _dow(day) + _near_day(toc, tk)
    return tk + _DAY * nd, not 0 <= nd < 7


def sbas_week(toc, sod):
    """A 2.10 GEO 'message frame time (sec of day GPS)' (rinex210.txt Table A16 l.1656) as the
    2.11+ 'Transmission Time of Message ... GPS seconds of the week ... has to refer to the same
    GPS week as the Epoch of Ephemerides ... adjusted by - or + 604800' (rinex211.txt l.910-915):
    the instant nearest Toc, from the start of Toc's GPS week (may be < 0 or >= 604800)."""
    day = datetime.date(*toc[:3])
    return sod + _DAY * (_dow(day) + _near_day(toc, sod))


def tk_day_basis(toc, tk):
    """A RINEX 3/4 GLONASS tk clearly written as seconds of the day: below 86400, Toc not on a
    Sunday (both bases agree there), more than 12 h from Toc's seconds of week and, as seconds
    of day, within 12 h of Toc's (circular distances: a week-basis tk lies within about a
    quarter of an hour of Toc)."""
    if tk is None or not 0 <= tk < _DAY:
        return False
    day = datetime.date(*toc[:3])
    if _dow(day) == 0:
        return False
    sod = Decimal(toc[3] * 3600 + toc[4] * 60) + Decimal(toc[5])

    def circ(a, c, m):
        d = abs(a - c) % m
        return min(d, m - d)
    return circ(tk, _DAY * _dow(day) + sod, 7 * _DAY) > _DAY / 2 and circ(tk, sod, _DAY) <= _DAY / 2


# Fields per line a RINEX 4 record defines, line 0 first (its positions: 3, then 4 per line).
# rinex_4.02.txt Table A9 p.79 (GPS LNAV orbit 7: t_tm, fit interval: 4X,2E19.12), A19 p.94
# (QZSS LNAV), A10 p.81 / A20 p.96 (CNAV orbit 8: t_tm, wn_op), A11 p.83 / A21 p.98 (CNV2 orbit 8
# ISC_L1Cd, ISC_L1Cp; orbit 9 t_tm, wn_op), A13 p.85 (Galileo orbit 5: IDOT, data sources, week;
# orbit 7: t_tm), A15 p.87 (GLONASS FDMA), A23 p.100 (BDS D1/D2 orbit 7: t_tm, AODC), A24/A25
# p.102/104 (CNV1/CNV2: spares inside lines are fields), A26 p.106 (CNV3 orbit 8: t_tm), A28
# p.108 (SBAS), A30 p.111 (NavIC orbit 7: t_tm). 4.02 adds the optional integer flags as a
# third field of the CNAV/CNV2 last line (4X,3E19.12; 4.00/4.01: 4X,2E19.12, rinex_4.01.txt
# Table A10 l.4419). STO: line 0 here holds the three A18 identifiers (tokens.nav_tokens), line
# 1 four values (Table A33 p.115); EOP 3/4/4 (A34 p.116); ION Klobuchar line 2: Beta3 and the
# Region code in 4.00/4.01 (rinex_4.00.txt Table A32 p.104), Beta3 only in 4.02 (A35 p.117);
# NeQuick-G line 1: the flags (A36 p.118); BDGIM line 2: two (A37 p.119).
_EPH_FIELDS4 = {
    ("G", "LNAV"): (3, 4, 4, 4, 4, 4, 4, 2), ("J", "LNAV"): (3, 4, 4, 4, 4, 4, 4, 2),
    ("G", "CNAV"): (3, 4, 4, 4, 4, 4, 4, 4, 2), ("J", "CNAV"): (3, 4, 4, 4, 4, 4, 4, 4, 2),
    ("G", "CNV2"): (3, 4, 4, 4, 4, 4, 4, 4, 2, 2), ("J", "CNV2"): (3, 4, 4, 4, 4, 4, 4, 4, 2, 2),
    ("E", "INAV"): (3, 4, 4, 4, 4, 3, 4, 1), ("E", "FNAV"): (3, 4, 4, 4, 4, 3, 4, 1),
    ("R", "FDMA"): (3, 4, 4, 4, 4),
    ("C", "D1"): (3, 4, 4, 4, 4, 4, 4, 2), ("C", "D2"): (3, 4, 4, 4, 4, 4, 4, 2),
    ("C", "CNV1"): (3, 4, 4, 4, 4, 4, 4, 4, 4, 4), ("C", "CNV2"): (3, 4, 4, 4, 4, 4, 4, 4, 4, 4),
    ("C", "CNV3"): (3, 4, 4, 4, 4, 4, 4, 4, 1),
    ("S", "SBAS"): (3, 4, 4, 4), ("I", "LNAV"): (3, 4, 4, 4, 4, 4, 4, 1),
}
_FLAGS402 = {("G", "CNAV"), ("J", "CNAV"), ("G", "CNV2"), ("J", "CNV2")}
_KLOB = {("G", "LNAV"), ("J", "LNAV"), ("I", "LNAV"), ("C", "D1D2"), ("G", "CNVX"), ("J", "CNVX")}


def fields4(version, kind, s, msg):
    if version < "4":
        return None
    if kind == "EPH":
        f = _EPH_FIELDS4.get((s, msg))
        if f is not None and version >= "4.02" and (s, msg) in _FLAGS402:
            f = f[:-1] + (3,)
        return f
    if kind == "STO":
        return (3, 4)
    if kind == "EOP":
        return (3, 4, 4)
    if kind == "ION":
        if (s, msg) in _KLOB:
            return (3, 4, 1 if version >= "4.02" else 2)
        return {("E", "IFNV"): (3, 1), ("C", "CNVX"): (3, 4, 2)}.get((s, msg))
    return None


# Spare fields inside RINEX 4 lines, as value positions (BROADCAST ORBIT k starts at 3 + 4 (k-1)):
# rinex_4.02.txt Tables A16/A17 p.90-91 (GLONASS L1OC/L3OC orbit 8 field 3), A23 p.100 (BDS D1/D2
# orbit 5 fields 2, 4), A24 p.102 (CNV1 orbit 7 field 2, orbit 9 fields 2, 3), A25 p.104 (CNV2
# orbit 7 field 1, orbit 9 fields 2, 3), A30 p.110-111 (NavIC LNAV orbit 5 fields 2, 4, orbit 6
# field 4), A31 p.112 (L1NV orbit 5 field 3), A34 p.116 (EOP line 1 field 1); rinex_4.00.txt the
# same for the types it has (l.5035-5037, 5172, 5187, 5287, 5307, 5686-5690, 5725, 5847)
_SPARES4 = {
    ("EPH", "R", "L1OC"): (3 + 28 + 2,), ("EPH", "R", "L3OC"): (3 + 28 + 2,),
    ("EPH", "C", "D1"): (3 + 16 + 1, 3 + 16 + 3), ("EPH", "C", "D2"): (3 + 16 + 1, 3 + 16 + 3),
    ("EPH", "C", "CNV1"): (3 + 24 + 1, 3 + 32 + 1, 3 + 32 + 2),
    ("EPH", "C", "CNV2"): (3 + 24 + 0, 3 + 32 + 1, 3 + 32 + 2),
    ("EPH", "I", "LNAV"): (3 + 16 + 1, 3 + 16 + 3, 3 + 20 + 3), ("EPH", "I", "L1NV"): (3 + 16 + 2,),
    ("EOP", None, None): (3,),
}


def spares4(version, kind, s, msg):
    if version < "4":
        return ()
    return _SPARES4.get(("EOP", None, None) if kind == "EOP" else (kind, s, msg), ())


# Spare fields of RINEX 2/3 EPH records as value positions, by system (line k's fields at
# 3 + 4 (k-1) ..): GPS orbit 7 fields 3-4 (rinex211.txt Table A4 l.1411-1412, rinex305.txt Table
# A6 p.69); Galileo orbit 5 field 4 and orbit 7 fields 2-4 (rinex305.txt Table A8 p.71-72); QZSS
# orbit 7 fields 3-4, and in 3.02 orbit 5 field 4 (rinex302.txt Table A12 p.71-72; the L2 P
# flag from 3.03, rinex303.txt p.80); BDS orbit 5 fields 2, 4 and orbit 7 fields 3-4
# (rinex305.txt Table A14 p.79-80); NavIC orbit 5 fields 2, 4, orbit 6 field 4, orbit 7 fields
# 2-4 (rinex305.txt Table A18 p.83-84); GEO 2.10 orbit 3 field 4 (rinex210.txt Table A16
# l.1671; the IODN from 2.11, rinex211.txt l.1976); GLONASS none.
def spares23(version, s):
    if version >= "4":
        return ()
    if s == "S":
        return (3 + 8 + 3,) if version < "2.11" else ()
    o5, o6, o7 = 3 + 16, 3 + 20, 3 + 24
    return {"G": (o7 + 2, o7 + 3), "E": (o5 + 3, o7 + 1, o7 + 2, o7 + 3),
            "J": ((o5 + 3,) if version < "3.03" else ()) + (o7 + 2, o7 + 3),
            "C": (o5 + 1, o5 + 3, o7 + 2, o7 + 3),
            "I": (o5 + 1, o5 + 3, o6 + 3, o7 + 1, o7 + 2, o7 + 3)}.get(s, ())


# the field a position holds where it is no spare, as the claims name it
_REAL_NAME = {("S", 3 + 8 + 3): "IODN", ("J", 3 + 16 + 3): "L2P-flag"}
_LEGACY_MSG = {"G": "LNAV", "J": "LNAV", "I": "LNAV", "S": "SBAS", "R": "FDMA", "C": "D1", "E": "INAV"}


def _flags_at(s, msg):
    """Position of the 4.02 CNAV/CNV2 integer flags: the third field of the last line."""
    f = _EPH_FIELDS4[(s, msg)]
    return 3 + 4 * (len(f) - 2) + 2


# the loss categories this file counts (each compared with the report as a whole)
_COUNTED = ("nav-field-not-representable:", "nav-spare-value-dropped:", "nav-sto-system-not-representable:")
# the one UTC ID of these 'UT' offsets: rinex_4.02.txt Table 27 p.43 (4.00/4.01 Table 23 p.40/42)
_TABLE27 = {"GPUT": "UTC(USNO)", "GLUT": "UTC(SU)", "GAUT": "UTCGAL", "BDUT": "UTC(NTSC)", "QZUT": "UTC(NICT)"}


def compare_nav(inp, outs, report, rin=None, merged=None):
    """Positional comparison of every EPH record (rinex211.txt A4/A11/A16 and rinex305.txt
    A6-A14 bodies line up position by position; RINEX 4 EPH bodies are RINEX 3 bodies), with
    the value changes the specs define (GLONASS tk and 2.10 GEO frame time bases, the 2.00
    GLONASS signs, the fields each RINEX 4 line defines, the QZSS ionospheric area).
    outs: list of output payloads (RINEX 2 targets may split one file into several);
    merged: the other inputs of a --merge (their records are the input too)."""
    problems = []
    if "NAV.MERGE" in (report.get("rules") or {}) and merged is None:
        # a merge cannot be checked against its first input alone (Sol round 17: claims about
        # the other inputs' records went unchecked)
        return ["a --merge conversion (rule NAV.MERGE): pass the other inputs (merged=[...])"]
    rin = rin if rin is not None else nav_tokens(lines_of(inp))
    source = report["source_version"]
    svk = "%.2f" % float(source)
    per_input = [(svk, rin)]     # (version, tokens) of each input
    rver = {k: [svk] * len(v) for k, v in rin.items()}     # each record's input version
    payloads = [(svk, inp)]
    if merged:
        rin = {k: list(v) for k, v in rin.items()}
        for m in merged:
            mt = nav_tokens(lines_of(m))
            mv = "%.2f" % float(lines_of(m)[0][:9])
            per_input.append((mv, mt))
            payloads.append((mv, m))
            for k, v in mt.items():
                rin.setdefault(k, []).extend(v)
                rver.setdefault(k, []).extend([mv] * len(v))
    rout = {}
    for o in outs:
        for k, v in nav_tokens(lines_of(o)).items():
            rout.setdefault(k, []).extend(v)
    target = report["target_version"]
    losses = report.get("losses", {})
    rules = report.get("rules") or {}
    assumptions = report.get("assumptions", []) or []
    lost_sys = {k.split(":")[1] for k in losses if k.startswith("system-not-representable:")}
    lost_msgs = {tuple(k.split(":")[1:3]) for k in losses if k.startswith("nav-message-not-representable:")}
    line5_fill = any(a["category"] == "glonass-nav-line5" for a in assumptions)
    dedupe = "nav-duplicate-removed" in losses
    tk_fix = any(r.get("rule") == "NAV.GLO.TK-DAY-BASIS" for r in report.get("repairs", []) or [])
    dropped = Counter()
    claims = Counter()            # loss categories the files show (the _COUNTED ones)
    counts = Counter()            # rules and assumptions the files show
    unknown5 = [Decimal("999999999.999").normalize(), Decimal(15)]
    # RINEX 3/4 nav epochs have whole seconds (I2.2: rinex305.txt Table A6, rinex_4.02.txt
    # Table A8); a RINEX 2 epoch's tenths (F5.1, rinex211.txt Table A4) are floored, one
    # nav-epoch-precision per record kept (was never compared: Sol round 13 audit)
    if target >= "3":
        n_frac = 0
        keyed = {}
        kver = {}
        for key, recs in rin.items():
            t = key[2] if key[0] == "EPH" and len(key) > 2 else None
            if t is not None and t[5] != t[5].to_integral_value():
                n_frac += sum(1 for m, v in recs if key[1][0] not in lost_sys
                              and (key[1][0], m.split(" ")[0]) not in lost_msgs)
                key2 = key[:2] + (t[:5] + (t[5].to_integral_value(rounding=ROUND_FLOOR),),) + key[3:]
            else:
                key2 = key
            keyed.setdefault(key2, []).extend(recs)
            kver.setdefault(key2, []).extend(rver[key])
        rin, rver = keyed, kver
        c = losses.get("nav-epoch-precision", {}).get("count", 0)
        if c != n_frac:
            problems.append(f"{n_frac} nav records with a fractional epoch second, report claims {c} "
                            "nav-epoch-precision")

    def cut(vals, version, vin, kind, s, msg, src_msg):
        """vals as a RINEX `version` line holds them: without the positions its lines do not
        define (fields4) and with its spare fields blank (spares4: 'Spare fields are to be left
        blank', rinex_4.02.txt section 6.4 p.48). What goes is counted as the claim it needs: the
        4.02 CNAV/CNV2 flags, a defined field, whenever written; any other value (a spare, or a
        field no version defines: spares 'hold no defined content', rinex305.txt section 6.4
        p.42) when not zero."""
        fields = fields4(version, kind, s, msg)
        gone = set(spares4(version, kind, s, msg))
        if fields is not None:
            pos = 0
            for line, n in enumerate(fields):
                width = 3 if line == 0 else 4
                gone.update(range(pos + n, pos + width))
                pos += width
        if not gone:
            return vals
        flags = _flags_at(s, src_msg) if kind == "EPH" and vin >= "4.02" and (s, src_msg) in _FLAGS402 else None
        out = list(vals)
        for k in sorted(gone):
            if k < len(out) and out[k] is not None:
                if k == flags:
                    claims[f"nav-field-not-representable:{s}:{src_msg}:flags"] += 1
                elif out[k] != 0:
                    claims[f"nav-spare-value-dropped:{kind}:{s}"] += 1
                out[k] = None
        return out

    def eph_values(sat, toc, vals, vin, src_msg, want_msg):
        s = sat[0]
        if s == "R" and vin == "2.00":
            # 2.00 GLONASS files store -TauN, -GammaN, +TauC; from 2.01 -TauN, +GammaN, -TauC
            # (rinex210.txt l.171-180, section 8.2)
            if len(vals) > 1 and vals[1] is not None:
                vals[1] = -vals[1]
            counts["v200"] += 1
        if len(vals) > 2 and vals[2] is not None:
            if s == "R" and src_msg in ("", "FDMA"):
                if vin < "3" <= target:
                    vals[2], other = glo_tk_week(toc, vals[2])
                    counts["glo-tk"] += 1
                    counts["glo-week"] += other
                elif target < "3" <= vin:
                    vals[2] = _floor_day(vals[2])
                    counts["glo-tk"] += 1
                elif vin >= "3" and target >= "3" and tk_day_basis(toc, vals[2]):
                    counts["tk-day"] += 1
                    if tk_fix:
                        vals[2], other = glo_tk_week(toc, vals[2])
                        counts["glo-week"] += other
            elif s == "S" and (vin < "2.11") != (target < "2.11"):
                vals[2] = sbas_week(toc, vals[2]) if vin < "2.11" else _floor_day(vals[2])
                counts["sbas"] += 1
        if vin >= "4":
            vals = cut(vals, vin, vin, "EPH", s, src_msg, src_msg)
        if target >= "4":
            vals = cut(vals, target, vin, "EPH", s, want_msg, src_msg)
        # RINEX 2/3 spares: a source spare holds no defined content, so it fills no target field
        # (left blank, the 'unknown'), and no value goes into a target spare (rinex305.txt
        # section 6.4 p.42 and revision note p.11 'shall be left blank and skipped when
        # reading/writing'); a real source field with a target spare in its place (the 2.11+
        # IODN to 2.10, the 3.03+ QZSS L2 P flag to 3.02) is a field lost whenever written
        src_sp, tgt_sp = set(spares23(vin, s)), set(spares23(target, s))
        for k in sorted(src_sp | tgt_sp):
            if k < len(vals) and vals[k] is not None:
                if k in src_sp and k in tgt_sp and vals[k] == 0:
                    continue          # a zero spare to a RINEX 2/3 spare: zero and blank say nothing
                if k in src_sp:
                    if vals[k] != 0:
                        claims[f"nav-spare-value-dropped:EPH:{s}"] += 1
                else:
                    claims[f"nav-field-not-representable:{s}:{src_msg or _LEGACY_MSG.get(s, '')}:"
                           f"{_REAL_NAME.get((s, k), f'position-{k}')}"] += 1
                vals[k] = None
        return vals

    def expected(key, recs, vers):
        out = []
        sat = key[1]
        for (msg, vals), vin in zip(recs, vers):
            # the message type: kept between RINEX 4 versions, derived going up (v4_message),
            # absent below RINEX 4
            if target < "4":
                want_msg = None
            elif msg:                       # a RINEX 4 record's own type (merged inputs may mix versions)
                want_msg = msg
            else:
                ok = v4_message(sat, vals)   # empty: no RINEX 4 type, so no output can match
                want_msg = next(iter(ok)) if ok else "(none)"
            # a record whose message type has no RINEX 3 form is booked under the message
            # type even when its system is also dropped
            if (sat[0], msg.split(" ")[0]) in lost_msgs:
                dropped["message"] += 1
                continue
            if sat[0] in lost_sys:
                dropped["system"] += 1
                continue
            vals = list(vals)
            if sat[0] == "R" and len(vals) > 15 and target < "3.05":
                line5 = (vals[15:19] + [None] * 4)[:4]
                if [line5[1], line5[2]] != unknown5 or line5[0] is not None or line5[3] is not None:
                    dropped["line5"] += 1   # real values: a loss the report must claim
                vals = vals[:15]          # RINEX 3.04 and older have no GLONASS line 5
            elif sat[0] == "R" and line5_fill and len(vals) <= 15:
                vals = vals + [None] * (15 - len(vals)) + GLO_LINE5_UNKNOWN
            vals = eph_values(sat, key[2], vals, vin, msg.split(" ")[0] if msg else "",
                              (want_msg or "").split(" ")[0])
            while vals and vals[-1] is None:
                vals.pop()
            out.append((want_msg, tuple(vals)))
        return Counter(out)

    # --dedupe removes exact duplicates of every record kind: the output keeps each record the
    # input has, at most as often, and the removals add up to the claim (Sol round 10)
    removed = 0

    def deduped(want, got):
        nonlocal removed
        if dedupe and set(want) == set(got) and all(got[k] <= want[k] for k in got):
            removed += sum(want.values()) - sum(got.values())
            return True
        return False

    for key in set(k for k in rin if k[0] == "EPH") | set(k for k in rout if k[0] == "EPH"):
        want = expected(key, rin.get(key, []), rver.get(key, []))
        got = Counter((m if target >= "4" else None, tuple(v)) for m, v in rout.get(key, []))
        if want == got or deduped(want, got):
            continue
        problems.append(f"nav record {key}: expected {sum(want.values())} record(s), got "
                        f"{sum(got.values())}; first difference "
                        f"{next(iter((want - got) or (got - want)), None)}")
        if len(problems) > 20:
            break
    subs_dropped = Counter()
    # --qzss-ion-area: the area of QZSS Klobuchar sets whose source names none, written as the
    # 4.00/4.01 Region code; without it the code is blank, which those versions read as wide
    # area (rinex_4.00.txt Table A32 p.104): either is an assumption, counted here and in
    # compare_nav_meta (sets from RINEX 2/3 header records)
    told = {}
    for a in assumptions:
        if a["category"] == "qzss-ion-area":
            told[(a.get("source"), a["detail"])] = a["count"]
    user = [d for (src, d) in told if src == "user"]
    area = user[0] if len(user) == 1 and user[0] in ("WIDE", "JAPN") else None
    if len(user) > 1 or (user and not area):
        problems.append(f"qzss-ion-area assumptions {told}: one user area, WIDE or JAPN, expected")
    area_counts = Counter()       # (source, area) of the sets written without the source's area

    def ion_area(s, vin, m0, sub, v):
        """(message, values) of a Klobuchar ION record in the target, None if it must go:
        4.00/4.01 'Region code: 0 or blank (wide area parameters), 1 (QZSS only - Japan area
        coefficients)' (rinex_4.00.txt Table A32 p.104; rinex_4.01.txt l.6190 p.108); 4.02 the
        subtype WIDE/JAPN, which 'the QZSS ION CNVX message type must have ... for the other
        types the subtype shall be left blank' (rinex_4.02.txt Table 25 p.40, Table A35 note 3*
        p.117)."""
        v = list(v) + [None] * (9 - len(v))
        code_src = "4.00" <= vin < "4.02"
        if code_src:
            said = "WIDE" if v[8] in (None, 0) else ("JAPN" if v[8] == 1 else None)
        else:
            said = sub if sub in ("WIDE", "JAPN") else ""
        if "4.00" <= target < "4.02":
            if code_src:
                if sub:                         # a subtype 4.00/4.01 do not define
                    subs_dropped[f"nav-subtype-not-representable:ION:{s}:{m0}"] += 1
                return m0, v
            if sub and (s != "J" or not said):
                subs_dropped[f"nav-subtype-not-representable:ION:{s}:{m0}"] += 1
            if s != "J":
                v[8] = None
            elif said:
                v[8] = Decimal(0 if said == "WIDE" else 1)
            elif area:
                v[8] = Decimal(0 if area == "WIDE" else 1)
                area_counts[("user", area)] += 1
            else:
                v[8] = None
                area_counts[("spec-default:blank-region-code", "WIDE")] += 1
            return m0, v
        if not code_src:
            return (f"{m0} {sub}" if sub else m0), v
        v[8] = None
        if s == "J" and m0 == "CNVX":
            return (f"CNVX {said}", v) if said else None
        if s == "J" and said:
            # the area as the LNAV subtype too: the user's decision of 2026-11-02, DLR's
            # practice (BRD400DLR), not rinex_4.02.txt Table A35 note 3* (CNVX only)
            return f"{m0} {said}", v
        if s == "J" or said != "WIDE":
            claims[f"nav-ion-area-not-representable:{s}:{m0}"] += 1
        return m0, v

    # RINEX 4 STO/ION/EOP records of the RINEX 4 inputs, each judged by its own input's version
    # (Sol round 19: a merge with a RINEX 3 input skipped them, so a changed EOP value passed).
    # With every input RINEX 4 the output holds exactly these; a merge with a RINEX 2/3 input
    # also writes records made from its header corrections (matched one by one in
    # compare_nav_meta), so there each of these must be in the output, or be a duplicate
    # --dedupe removed.
    v4_in = [(v, t) for v, t in per_input if v >= "4"]
    mixed = len(v4_in) != len(per_input)
    if target >= "4" and v4_in:
        exp = defaultdict(Counter)
        for vin, toks in v4_in:
            for key, recs in toks.items():
                if key[0] == "EPH":
                    continue
                s = key[1][0]
                for m, v in recs:
                    m0, _, sub = m.partition(" ")
                    if (s, m0) in lost_msgs:
                        dropped["message"] += 1
                        continue
                    if key[0] == "STO" and s == "S" and target < "4.02" and vin != target:
                        # STO systems G,R,E,C,J,I in 4.00/4.01 (rinex_4.00.txt Table A30 p.102)
                        claims[f"nav-sto-system-not-representable:S:{(v[0] if v else None) or '?'}"] += 1
                        continue
                    v = cut(list(v), vin, vin, key[0], s, m0, m0)
                    if key[0] == "STO" and v and v[0] in _TABLE27 and len(v) > 2 and v[2] is None:
                        # a 'UT' offset's UTC ID, 'necessary ... for every "UT" time offset
                        # message': the one Table 27 names (rinex_4.02.txt p.43)
                        v[2] = _TABLE27[v[0]]
                        counts["utc-id"] += 1
                    if key[0] == "ION" and (s, m0) in _KLOB:
                        r = ion_area(s, vin, m0, sub, v)
                        if r is None:
                            dropped["cnvx-area"] += 1     # a code that names no area
                            continue
                        m2, v = r
                    elif sub and target < "4.02":
                        # subtypes exist from 4.02 (rinex_4.02.txt Table 25 p.40): the record
                        # stays, its subtype goes, claimed nav-subtype-not-representable
                        subs_dropped[f"nav-subtype-not-representable:{key[0]}:{s}:{m0}"] += 1
                        m2 = m0
                    else:
                        m2 = m
                    v = cut(v, target, vin, key[0], s, m2.partition(" ")[0], m0)
                    while v and v[-1] is None:
                        v.pop()
                    exp[key][(m2, tuple(v))] += 1
        keys = set(exp) | (set() if mixed else {k for k in rout if k[0] != "EPH"})
        for key in keys:
            a = exp.get(key, Counter())
            b = Counter((m, tuple(v)) for m, v in rout.get(key, []))
            if not mixed:
                if a != b and not deduped(a, b):
                    problems.append(f"nav {key[0]} record {key}: values differ (expected "
                                    f"{next(iter(a - b), None)}, got {next(iter(b - a), None)})")
                continue
            missing = a - b
            if missing and dedupe and all(b[k] >= 1 for k in missing):
                removed += sum(missing.values())          # duplicates of a record kept
            elif missing:
                problems.append(f"nav {key[0]} record {key}: {sum(missing.values())} input record(s) "
                                f"missing or changed, e.g. {next(iter(missing))}")
    if dedupe and removed != losses["nav-duplicate-removed"]["count"]:
        problems.append(f"{removed} duplicate records removed, report claims "
                        f"{losses['nav-duplicate-removed']['count']} nav-duplicate-removed")
    n_sys = sum(e["count"] for k, e in losses.items() if k.startswith("system-not-representable:"))
    n_msg = sum(e["count"] for k, e in losses.items() if k.startswith("nav-message-not-representable:"))
    if dropped["system"] != n_sys:
        problems.append(f"{dropped['system']} records of dropped systems, report claims {n_sys}")
    n5 = losses.get("glonass-nav-line5-dropped", {}).get("count", 0)
    if dropped["line5"] != n5:
        problems.append(f"{dropped['line5']} GLONASS records lost a non-default line 5, report claims {n5}")
    if dropped["message"] != n_msg:
        problems.append(f"{dropped['message']} records of dropped message types, report claims {n_msg}")
    sub_claims = {k for k in losses if k.startswith("nav-subtype-not-representable:")}
    area_claims = {k for k in losses if k.startswith("nav-ion-area-not-representable:")}
    if target >= "4":
        for cat in set(subs_dropped) | sub_claims:
            if subs_dropped[cat] != losses.get(cat, {}).get("count", 0):
                problems.append(f"{subs_dropped[cat]} records lost their subtype, report claims "
                                f"{losses.get(cat, {}).get('count', 0)} {cat}")
        for cat in set(k for k in claims if k.startswith("nav-ion-area-not-representable:")) | area_claims:
            if claims[cat] != losses.get(cat, {}).get("count", 0):
                problems.append(f"{claims[cat]} ionospheric sets lose their area, report claims "
                                f"{losses.get(cat, {}).get('count', 0)} {cat}")
    elif any(v >= "4" for v, t in per_input):
        problems += _header_area_claims(rin, rver, outs, losses, target, sub_claims | area_claims)
    n_area = losses.get("nav-correction-not-representable:ION:CNVX-area-unknown:J", {}).get("count", 0)
    if dropped["cnvx-area"] != n_area:
        problems.append(f"{dropped['cnvx-area']} QZSS CNVX ION records whose Region code names no area, "
                        f"report claims {n_area}")
    # fields the target's lines do not define (cut above), and SBAS STO records 4.00/4.01 lack
    got_claims = Counter({k: e["count"] for k, e in losses.items() if k.startswith(_COUNTED)})
    meta_counts = {}
    problems.extend(compare_nav_meta(inp, outs, report, merged=merged, counts=meta_counts))
    claims.update(meta_counts.get("claims", Counter()))
    want_claims = Counter({k: n for k, n in claims.items() if k.startswith(_COUNTED)})
    if +want_claims != +got_claims:
        problems.append(f"values with no field in RINEX {target} {dict(+want_claims)}, report claims "
                        f"{dict(+got_claims)}")
    area_counts.update(meta_counts.get("qzss-ion-area", Counter()))
    if +area_counts != +Counter(told):
        problems.append(f"QZSS ionospheric sets written without their source's area {dict(+area_counts)}, "
                        f"report assumes {told} (qzss-ion-area)")
    # rules and assumptions of the value changes (each a count of the records changed)
    def rule_n(name):
        return (rules.get(name) or {}).get("count", 0)

    def assumed(cat):
        return sum(a["count"] for a in assumptions if a["category"] == cat)
    n_tauc = 0
    for vin, pl in payloads:
        L = lines_of(pl)
        if vin == "2.00" and L[0][20:21] == "G":
            n_tauc += sum(1 for l in L[:next(i for i, x in enumerate(L) if x[60:80].strip() == "END OF HEADER")]
                          if l[60:80].strip() == "CORR TO SYSTEM TIME" and l[21:40].strip())
    for what, have, want in (("NAV.GLO.FRAME-TIME-BASIS", rule_n("NAV.GLO.FRAME-TIME-BASIS"), counts["glo-tk"]),
                             ("NAV.SBAS.FRAME-TIME-BASIS", rule_n("NAV.SBAS.FRAME-TIME-BASIS"), counts["sbas"]),
                             ("glonass-frame-time-week", assumed("glonass-frame-time-week"), counts["glo-week"]),
                             ("NAV.GLO.V2.00-SIGNS", rule_n("NAV.GLO.V2.00-SIGNS"), counts["v200"] + n_tauc),
                             ("glonass-nav-2.00-signs", assumed("glonass-nav-2.00-signs"), counts["v200"] + n_tauc)):
        if have != want:
            problems.append(f"{want} record(s) changed by {what}, the report counts {have}")
    warned = any(w.get("rule") == "NAV.GLO.TK-DAY-BASIS" for w in report.get("warnings", []) or [])
    if counts["tk-day"] and not (warned or tk_fix):
        problems.append(f"{counts['tk-day']} GLONASS records hold tk as seconds of the day, the report "
                        "neither warns (NAV.GLO.TK-DAY-BASIS) nor repairs")
    if (warned or tk_fix) and not counts["tk-day"]:
        problems.append("the report says GLONASS tk is on the day basis, no record kept is")
    return problems


def _header_area_claims(rin, rver, outs, losses, target, claimed):
    """RINEX 4 ionospheric records written into RINEX 2/3 headers: a 4.02 record's subtype
    (rinex_4.02.txt Table 25 p.40) and a 4.00/4.01 Klobuchar set's Region code (rinex_4.00.txt
    Table A32 p.104) have no field there (rinex305.txt Table A5 p.65 'QZSA = QZS alpha0 -
    alpha3'; rinex211.txt Table A3 ION ALPHA/BETA), so each kept set from such a record claims
    nav-subtype-not-representable or nav-ion-area-not-representable. The header keeps one set
    per model and system (from 3.02 per type, time mark and SV: rinex305.txt Table A5 p.64-66);
    the others are claimed nav-correction-extra."""
    problems = []

    def claim_of(key, m, v, vin):
        s = key[1][0]
        m0 = m.split(" ")[0]
        if vin >= "4.02":
            return f"nav-subtype-not-representable:{key[0]}:{s}:{m0}" if " " in m else None
        if "4.00" <= vin < "4.02" and key[0] == "ION" and (s, m0) in _KLOB:
            region = v[8] if len(v) > 8 else None
            if s == "J" or region not in (None, 0):
                return f"nav-ion-area-not-representable:{s}:{m0}"
        return None
    order = [(k, m, v, claim_of(k, m, v, vin)) for k, lst in rin.items() if k[0] != "EPH"
             for (m, v), vin in zip(lst, rver.get(k, []))]
    n_sub = Counter(c for k, m, v, c in order if c)
    prefix = {"G": "GPS", "J": "QZS", "C": "BDS", "I": "IRN", "E": "GAL"}
    head = []
    for o in outs:
        for l in lines_of(o):
            lab = l[60:80].strip()
            if lab == "IONOSPHERIC CORR":
                head.append(l)
            elif lab in ("ION ALPHA", "ION BETA"):
                # RINEX 2 2X,4D12.4 (rinex211.txt Table A3) read as GPSA / GPSB
                head.append(("GPSA " if lab == "ION ALPHA" else "GPSB ") + l[2:50].ljust(49))
    kept = Counter(l[:3] for l in head if l[3:4] in "A ")
    for cat in set(n_sub) | claimed:
        c = losses.get(cat, {}).get("count", 0)
        if c > n_sub[cat]:
            problems.append(f"{n_sub[cat]} input records with a subtype or area, report claims {c} {cat}")
    ion = [(k, m, v, c) for k, m, v, c in order if k[0] == "ION"]
    exact = set()
    if target >= "3.02":
        # from 3.02 a Klobuchar set keeps its own place (type, time mark, SV: rinex305.txt
        # Table A5), so the claims are exact: each kept QZSA/QZSB (GPSA, BDSA, IRNA) pair comes
        # from the first input record, in file order, of its place with its values, and that
        # record's subtype or area is lost (Sonnet round 28)
        for s, p in prefix.items():
            if s == "E":
                continue                      # NeQuick (GAL): one line, bounded below
            exact.add(s)
            want = Counter()
            lines_ab = [l for l in head if l[:3] == p and l[3:4] in "AB"]
            for la in (l for l in lines_ab if l[3:4] == "A"):
                place = (la[54:55].strip(), la[56:58].strip().lstrip("0"))
                lb = next((l for l in lines_ab if l[3:4] == "B" and
                           (l[54:55].strip(), l[56:58].strip().lstrip("0")) == place), None)
                vals = [_dec(la[5 + 12 * j:17 + 12 * j]) for j in range(4)] + (
                    [_dec(lb[5 + 12 * j:17 + 12 * j]) for j in range(4)] if lb else [None] * 4)
                for k, m, v, c in ion:
                    mark = chr(ord("A") + k[2][3]) if k[2] else ""
                    if k[1][0] != s or (mark, k[1][1:].lstrip("0")) != place:
                        continue
                    if all(_near(a, b) for a, b in zip((list(v) + [None] * 8)[:8], vals) if b is not None):
                        if c:
                            want[c] += 1
                        break
            got = Counter({cat: losses[cat]["count"] for cat in claimed if cat.split(":")[-3:-1] == ["ION", s]
                           or cat.split(":")[1:2] == [s]})
            if +want != +got:
                problems.append(f"{s}: kept ION sets from records with a subtype or area {dict(want)}, "
                                f"report claims {dict(got)}")
    for s, p in prefix.items():
        if s in exact:
            continue
        mine = [cat for cat in claimed if cat.split(":")[-3:-1] == ["ION", s] or cat.split(":")[1:2] == [s]]
        c = sum(losses.get(cat, {}).get("count", 0) for cat in mine)
        if c > kept[p]:
            problems.append(f"{s}: {kept[p]} ION set(s) kept, report claims {c} ({mine})")
            continue
        recs_s = [(m, v, cc) for k, m, v, cc in ion if k[1][0] == s]
        if not kept[p] or not recs_s:
            continue
        # which input records the kept set came from: Klobuchar alpha (xxxA) and beta (xxxB)
        # lines, A4,1X,4D12.4 (rinex305.txt Table A5), against each record's 8 values at that
        # precision; NeQuick (GAL) cannot be matched, all-or-none applies
        alpha = next((l for l in head if l[:4] == p + "A"), None)
        beta = next((l for l in head if l[:4] == p + "B"), None)
        if alpha is None or beta is None:
            matched = [cc for m, v, cc in recs_s]
        else:
            want = [_dec(alpha[5 + 12 * j:17 + 12 * j]) for j in range(4)] + \
                   [_dec(beta[5 + 12 * j:17 + 12 * j]) for j in range(4)]
            matched = [cc for m, v, cc in recs_s
                       if all(_near(a, b) for a, b in zip((list(v) + [None] * 8)[:8], want))]
        if matched and all(matched) and not c:
            problems.append(f"{s}: the kept ION set comes from records with a subtype or area "
                            f"({sorted(set(matched))[:2]}), report claims none")
        if matched and not any(matched) and c:
            problems.append(f"{s}: the kept ION set comes from records without a subtype or area, "
                            f"report claims {c}")
    return problems


def compare_met(inp, out, report, tin=None):
    tin = tin if tin is not None else met_tokens(lines_of(inp))
    tout = met_tokens(lines_of(out))
    problems = []
    lost = {k.split(":")[1] for k in report.get("losses", {}) if k.startswith("met-type-not-representable:")}
    extra = tout - tin
    missing = Counter({k: v for k, v in (tin - tout).items() if k[1] not in lost})
    if extra:
        problems.append(f"{sum(extra.values())} met tokens not in the input, e.g. {list(extra)[:3]}")
    if missing:
        problems.append(f"{sum(missing.values())} met tokens lost without a report entry, e.g. {list(missing)[:3]}")
    # each claim counts the type's values (Sol round 13: a count of 999 passed)
    for t in lost:
        n = sum(v for k, v in tin.items() if k[1] == t)
        c = report["losses"][f"met-type-not-representable:{t}"]["count"]
        if c != n:
            problems.append(f"{n} {t} values in the input, report claims {c} met-type-not-representable:{t}")
    problems.extend(compare_met_meta(inp, out, report))
    return problems
