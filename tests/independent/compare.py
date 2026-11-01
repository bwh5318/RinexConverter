"""diff <=> report check (PLAN §1 clauses 3 and 5a), independent of rinexcore.

compare_obs / compare_nav / compare_met take the input and output payloads
(plain RINEX bytes) and the conversion report (dict) and return a list of
problems; an empty list means every difference is claimed by the report and
every claimed loss actually happened, with equal counts.
"""

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
    rout, cout = obs_tokens(lines_of(out), exact=exact)
    losses = report.get("losses", {})
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
        rin = obs_tokens(inl, v3_lli=v3_lli, exact=exact, drop=drop)[0]
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
    problems.extend(compare_obs_meta(inp, out, report, type_emptied=type_emptied))
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


def compare_nav(inp, outs, report, rin=None, merged=None):
    """Positional comparison of every EPH record (rinex211.txt A4/A11/A16 and rinex305.txt
    A6-A14 bodies line up position by position; RINEX 4 EPH bodies are RINEX 3 bodies).
    outs: list of output payloads (RINEX 2 targets may split one file into several);
    merged: the other inputs of a --merge (their records are the input too)."""
    problems = []
    if "NAV.MERGE" in (report.get("rules") or {}) and merged is None:
        # a merge cannot be checked against its first input alone (Sol round 17: claims about
        # the other inputs' records went unchecked)
        return ["a --merge conversion (rule NAV.MERGE): pass the other inputs (merged=[...])"]
    rin = rin if rin is not None else nav_tokens(lines_of(inp))
    per_input = [("%.2f" % float(report["source_version"]), rin)]     # (version, tokens) of each input
    if merged:
        rin = {k: list(v) for k, v in rin.items()}
        for m in merged:
            mt = nav_tokens(lines_of(m))
            per_input.append(("%.2f" % float(lines_of(m)[0][:9]), mt))
            for k, v in mt.items():
                rin.setdefault(k, []).extend(v)
    rout = {}
    for o in outs:
        for k, v in nav_tokens(lines_of(o)).items():
            rout.setdefault(k, []).extend(v)
    target = report["target_version"]
    source = report["source_version"]
    losses = report.get("losses", {})
    lost_sys = {k.split(":")[1] for k in losses if k.startswith("system-not-representable:")}
    lost_msgs = {tuple(k.split(":")[1:3]) for k in losses if k.startswith("nav-message-not-representable:")}
    line5_drop = "glonass-nav-line5-dropped" in losses
    line5_fill = any(a["category"] == "glonass-nav-line5" for a in report.get("assumptions", []))
    dedupe = "nav-duplicate-removed" in losses
    dropped = Counter()
    unknown5 = [Decimal("999999999.999").normalize(), Decimal(15)]
    # RINEX 3/4 nav epochs have whole seconds (I2.2: rinex305.txt Table A6, rinex_4.02.txt
    # Table A8); a RINEX 2 epoch's tenths (F5.1, rinex211.txt Table A4) are floored, one
    # nav-epoch-precision per record kept (was never compared: Sol round 13 audit)
    if target >= "3":
        n_frac = 0
        keyed = {}
        for key, recs in rin.items():
            t = key[2] if key[0] == "EPH" and len(key) > 2 else None
            if t is not None and t[5] != t[5].to_integral_value():
                n_frac += sum(1 for m, v in recs if key[1][0] not in lost_sys
                              and (key[1][0], m.split(" ")[0]) not in lost_msgs)
                key = key[:2] + (t[:5] + (t[5].to_integral_value(rounding=ROUND_FLOOR),),) + key[3:]
            keyed.setdefault(key, []).extend(recs)
        rin = keyed
        c = losses.get("nav-epoch-precision", {}).get("count", 0)
        if c != n_frac:
            problems.append(f"{n_frac} nav records with a fractional epoch second, report claims {c} "
                            "nav-epoch-precision")

    def expected(key, recs):
        out = []
        sat = key[1]
        for msg, vals in recs:
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
        want = expected(key, rin.get(key, []))
        got = Counter((m if target >= "4" else None, tuple(v)) for m, v in rout.get(key, []))
        if want == got or deduped(want, got):
            continue
        problems.append(f"nav record {key}: expected {sum(want.values())} record(s), got "
                        f"{sum(got.values())}; first difference "
                        f"{next(iter((want - got) or (got - want)), None)}")
        if len(problems) > 20:
            break
    subs_dropped = Counter()
    # --qzss-ion-area: the user names the area the 4.02 CNVX records need; one area per file
    told = {a["detail"]: a["count"] for a in report.get("assumptions", []) or []
            if a["category"] == "qzss-ion-area" and a.get("source") == "user"}
    area = next(iter(told)) if len(told) == 1 and set(told) <= {"WIDE", "JAPN"} else None
    if told and not area:
        problems.append(f"qzss-ion-area assumptions {told}: one area, WIDE or JAPN, expected")
    n_given = 0
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
                for m, v in recs:
                    m0, _, sub = m.partition(" ")
                    if (key[1][0], m0) in lost_msgs:
                        dropped["message"] += 1
                    elif key[0] == "ION" and key[1][0] == "J" and m == "CNVX" and vin < "4.02" <= target:
                        if area:                      # the user's area, kept with the values
                            n_given += 1
                            exp[key][(f"CNVX {area}", tuple(v))] += 1
                        else:
                            dropped["cnvx-area"] += 1     # needs WIDE/JAPN from 4.02 (rinex_4.02.txt Table 25)
                    elif sub and target < "4.02":
                        # subtypes exist from 4.02 (rinex_4.02.txt Table 25 p.40): the record
                        # stays, its subtype goes, claimed nav-subtype-not-representable
                        subs_dropped[f"nav-subtype-not-representable:{key[0]}:{key[1][0]}:{m0}"] += 1
                        exp[key][(m0, tuple(v))] += 1
                    else:
                        exp[key][(m, tuple(v))] += 1
        keys = set(exp) | (set() if mixed else {k for k in rout if k[0] != "EPH"})
        for key in keys:
            a = exp.get(key, Counter())
            b = Counter((m, tuple(v)) for m, v in rout.get(key, []))
            if not mixed:
                if a != b and not deduped(a, b):
                    problems.append(f"nav {key[0]} record {key}: values differ")
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
    if target >= "4":
        for cat in set(subs_dropped) | sub_claims:
            if subs_dropped[cat] != losses.get(cat, {}).get("count", 0):
                problems.append(f"{subs_dropped[cat]} records lost their subtype, report claims "
                                f"{losses.get(cat, {}).get('count', 0)} {cat}")
    elif source >= "4.02":
        # RINEX 2/3 header corrections have no subtype. The header keeps one set per model and
        # system (the others are claimed nav-correction-extra), so a system's subtype claims
        # add up to at most its kept sets (one per 'A' line: GPSA, QZSA, BDSA, IRNA, or GAL),
        # each at most its subtyped input records; when every ION record of a system has a
        # subtype and the header keeps a set of it, that set's subtype is claimed.
        n_sub = Counter(f"nav-subtype-not-representable:{k[0]}:{k[1][0]}:{m.split(' ')[0]}"
                        for k, lst in rin.items() if k[0] != "EPH" for m, v in lst if " " in m)
        ion_all = Counter(k[1][0] for k, lst in rin.items() if k[0] == "ION" for m, v in lst)
        ion_sub = Counter(k[1][0] for k, lst in rin.items() if k[0] == "ION" for m, v in lst if " " in m)
        prefix = {"G": "GPS", "J": "QZS", "C": "BDS", "I": "IRN", "E": "GAL"}
        head = [l for o in outs for l in lines_of(o) if l[60:80].strip() == "IONOSPHERIC CORR"]
        kept = Counter(l[:3] for l in head if l[3:4] in "A ")
        for cat in set(n_sub) | sub_claims:
            c = losses.get(cat, {}).get("count", 0)
            if c > n_sub[cat]:
                problems.append(f"{n_sub[cat]} subtyped input records, report claims {c} {cat}")
        exact = set()
        if target >= "3.02":
            # from 3.02 a Klobuchar set keeps its own place (type, time mark, SV: rinex305.txt
            # Table A5), so the claims are exact: each kept QZSA/QZSB (GPSA, BDSA, IRNA) pair
            # comes from the first input record, in file order, of its place with its values,
            # and that record's subtype is lost (Sonnet round 28: a deleted claim passed on
            # BRD400DLR, now that several QZSS sets are kept)
            order = [(k, m, v) for k, lst in rin.items() if k[0] == "ION" for m, v in lst]
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
                    for k, m, v in order:
                        mark = chr(ord("A") + k[2][3]) if k[2] else ""
                        if k[1][0] != s or (mark, k[1][1:].lstrip("0")) != place:
                            continue
                        if all(_near(a, b) for a, b in zip((list(v) + [None] * 8)[:8], vals) if b is not None):
                            if " " in m:
                                want[f"nav-subtype-not-representable:ION:{s}:{m.split(' ')[0]}"] += 1
                            break
                got = Counter({cat: losses[cat]["count"] for cat in sub_claims
                               if cat.split(":")[1:3] == ["ION", s]})
                if +want != +got:
                    problems.append(f"{s}: kept ION sets from subtyped records {dict(want)}, report claims "
                                    f"{dict(got)} nav-subtype-not-representable")
        for s, p in prefix.items():
            if s in exact:
                continue
            c = sum(losses.get(cat, {}).get("count", 0) for cat in sub_claims
                    if cat.split(":")[1:3] == ["ION", s])
            if c > kept[p]:
                problems.append(f"{s}: {kept[p]} ION set(s) kept, report claims {c} "
                                f"nav-subtype-not-representable:ION:{s}:*")
                continue
            if not kept[p] or not ion_all[s]:
                continue
            # which input records the kept set came from: Klobuchar alpha (xxxA) and beta
            # (xxxB) lines, A4,1X,4D12.4 (rinex305.txt Table A5), against each record's 8
            # values at that precision; NeQuick (GAL) cannot be matched, all-or-none applies
            alpha = next((l for l in head if l[:4] == p + "A"), None)
            beta = next((l for l in head if l[:4] == p + "B"), None)
            if alpha is None or beta is None:
                matched = [m for k, lst in rin.items() if k[0] == "ION" and k[1][0] == s for m, v in lst]
            else:
                want = [_dec(alpha[5 + 12 * j:17 + 12 * j]) for j in range(4)] + \
                       [_dec(beta[5 + 12 * j:17 + 12 * j]) for j in range(4)]
                matched = [m for k, lst in rin.items() if k[0] == "ION" and k[1][0] == s for m, v in lst
                           if all(_near(a, b) for a, b in zip((list(v) + [None] * 8)[:8], want))]
            if matched and all(" " in m for m in matched) and not c:
                problems.append(f"{s}: the kept ION set comes from subtyped record(s) ({sorted(set(matched))[:2]}), "
                                f"report claims no nav-subtype-not-representable:ION:{s}:*")
            if matched and not any(" " in m for m in matched) and c:
                problems.append(f"{s}: the kept ION set comes from records without a subtype, report "
                                f"claims {c} nav-subtype-not-representable:ION:{s}:*")
    n_area = losses.get("nav-correction-not-representable:ION:CNVX-area-unknown:J", {}).get("count", 0)
    if dropped["cnvx-area"] != n_area:
        problems.append(f"{dropped['cnvx-area']} QZSS CNVX ION records without an area, report claims {n_area}")
    if area and told[area] != n_given:
        problems.append(f"{n_given} QZSS CNVX ION records given the area {area}, report assumes {told[area]}")
    problems.extend(compare_nav_meta(inp, outs, report, merged=merged))
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
