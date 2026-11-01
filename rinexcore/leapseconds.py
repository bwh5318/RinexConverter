"""GPS - UTC leap seconds, a dated table (PLAN §1 clause 8, source 3).

Steps from the IERS Bulletin C series (UTC - TAI = -37 s since 2017-01-01, so
GPS - UTC = 18 s). Bulletin C 72 (6 July 2026) announced no leap second at the
end of December 2026; the next possible step is at the end of June 2027, so the
table is valid up to and including 2027-06-30. Later dates return None: the
caller must ask for the value (--leap-seconds) rather than guess.
"""

import datetime

SOURCE = "table:IERS Bulletin C (no step after 2017-01-01; Bulletin C 72, 2026-07-06)"
VALID_UNTIL = datetime.date(2027, 6, 30)

# (first day the value applies, GPS - UTC in seconds)
STEPS = [
    (datetime.date(1980, 1, 6), 0), (datetime.date(1981, 7, 1), 1), (datetime.date(1982, 7, 1), 2),
    (datetime.date(1983, 7, 1), 3), (datetime.date(1985, 7, 1), 4), (datetime.date(1988, 1, 1), 5),
    (datetime.date(1990, 1, 1), 6), (datetime.date(1991, 1, 1), 7), (datetime.date(1992, 7, 1), 8),
    (datetime.date(1993, 7, 1), 9), (datetime.date(1994, 7, 1), 10), (datetime.date(1996, 1, 1), 11),
    (datetime.date(1997, 7, 1), 12), (datetime.date(1999, 1, 1), 13), (datetime.date(2006, 1, 1), 14),
    (datetime.date(2009, 1, 1), 15), (datetime.date(2012, 7, 1), 16), (datetime.date(2015, 7, 1), 17),
    (datetime.date(2017, 1, 1), 18),
]


def gps_utc(day):
    """GPS - UTC leap seconds on `day` (a date), or None outside the table's validity."""
    if day < STEPS[0][0] or day > VALID_UNTIL:
        return None
    n = 0
    for start, v in STEPS:
        if day >= start:
            n = v
    return n
