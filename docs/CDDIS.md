# Getting RINEX files from CDDIS

CDDIS is NASA's Crustal Dynamics Data Information System. It hosts the IGS archive and
needs a free **NASA Earthdata** login. Everything below was checked against the live
archive on **2026-10-30**, by listing directories and screening 2,362 file headers. The
archive does change, so if a path stops working, list the parent directory before you
assume anything.

## 1. The login file

A two-line text file: the Earthdata username on line 1, the password on line 2. The
user's file travels on the F: drive at `F:\RINEXConvert_Analysis_secrets\cddislogin.txt`.

The code looks for it in this order (`tools/build_corpus.py:credential_paths`; use the
same order in `rinexcore/cddis.py`):

1. The path in the `RINEX_CDDIS_LOGIN` environment variable.
2. `..\RINEXConvert_Analysis_secrets\cddislogin.txt`, **beside** the repository, not
   inside it.
3. `%USERPROFILE%\.cddis\cddislogin.txt`.

Rules:

- Never print it, log it, copy it into the repository, or paste it into a message,
  a commit or a Codex brief.
- Send it **only** to the exact host `urs.earthdata.nasa.gov`. The `EarthdataAuth` class
  compares the hostname exactly, so a redirect to a look-alike host never gets the
  password.
- If a download returns HTML instead of data, or a 401 from `urs.earthdata.nasa.gov`, the
  login failed. Ask the user to check the account at <https://urs.earthdata.nasa.gov>.
  Don't retry in a loop.

Check that the login works with:

```
python tools/build_corpus.py --check-login
```

## 2. How the HTTPS access works

The base URL is `https://cddis.nasa.gov/archive/gnss/`.

- **Login redirects.** A GET to CDDIS redirects to `urs.earthdata.nasa.gov`, which
  redirects back with a token, and then on to the file. `requests` drops the session
  auth on redirects, so follow them **hop by hop** with `allow_redirects=False`. Upgrade
  any `http://` hop to `https://`. Keep one `requests.Session` per thread, so the login
  cookie is reused. `tools/build_corpus.py:get` is a working example, ported from the
  desktop's `autocomparesp3` downloader (`reference/cddis_https/`).
- **Listing a directory.** Append `*?list` to the directory URL. You get plain text:
  one `name size` line per **file** (subdirectories are not listed), plus two `# Total
  …` lines. Example: `https://cddis.nasa.gov/archive/gnss/data/daily/2026/274/26d/*?list`.
- **Partial downloads.** A `Range: bytes=0-24575` header is honoured through the redirect
  chain. That's enough to decompress the start of a `.gz`, `.Z` or Hatanaka file and read
  its whole RINEX header (`fetch_head` and `unwrap_head` in `tools/build_corpus.py`).
- **Checksums.** Most data directories contain `SHA512SUMS` and `MD5SUMS`. Use them to
  verify downloads.
- **Politeness.** At most 4 parallel connections, a descriptive `User-Agent`, and a local
  cache: never download the same file twice.

## 3. Where things are

`YYYY` is the 4-digit year, `YY` the 2-digit year, `DDD` the day of year, `HH` the hour
and `WWWW` the GPS week. "Seen" lists the RINEX versions the screen actually found there.

| What | Directory under `/archive/gnss/` | File names | Seen |
|---|---|---|---|
| Daily obs, Hatanaka | `data/daily/YYYY/DDD/YYd/` | `SSSS00CCC_R_YYYYDDD0000_01D_30S_MO.crx.gz` (v3/v4) **and** `ssssDDD0.YYd.gz` (v2, still published in 2026: 160 stations on 2026-274) | 2.00–4.02 |
| Daily obs, plain | `data/daily/YYYY/DDD/YYo/` | `…_MO.rnx.gz`, `ssssDDD0.YYo.gz` | 2.00, 2.11, 3.04, 3.05 |
| Per-station nav, mixed | `data/daily/YYYY/DDD/YYp/` | `…_01D_MN.rnx.gz` | 3.02–4.02 |
| Per-station nav by system | `…/YYn/` GPS, `YYg/` GLONASS, `YYl/` Galileo, `YYf/` BeiDou, `YYq/` QZSS, `YYh/` SBAS, `YYi/` NavIC | short v2 names, or `…_GN`, `_RN`, `_EN`, `_CN`, `_JN`, `_SN`, `_IN.rnx.gz` | 2.00–4.00 (one SBAS 2.11 file uses type letter `S`, not `H`) |
| Daily met | `data/daily/YYYY/DDD/YYm/` | `…_01D_05M_MM.rnx.gz`, `ssssDDD0.YYm.Z` | 2.00–3.05, 4.00 |
| **Merged broadcast nav** | `data/daily/YYYY/brdc/` | `brdcDDD0.YYn.gz` (GPS, **2.00**), `brdcDDD0.YYg.gz` (GLONASS, **2.01**), `BRDC00IGS_R_YYYYDDD0000_01D_MN.rnx.gz` (v3), `BRDM00DLR_S_…_MN.rnx.gz` (v3), **`BRD400DLR_S_…_MN.rnx.gz` (RINEX 4, currently 4.02)** | 2.00–4.02 |
| High-rate 1 Hz obs | `data/highrate/YYYY/DDD/YYd/HH/` | `…_R_YYYYDDDHHMM_15M_01S_MO.crx.gz` (four 15-min files per hour) | 2.11–4.01 |
| Hourly obs and nav | `data/hourly/YYYY/DDD/HH/` | `…_01H_30S_MO.crx.gz`, `…_01H_MN.rnx.gz` | 2.11–4.01 |
| Products (orbits, clocks) | `products/WWWW/` | `IGS0OPSFIN_YYYYDDD0000_01D_15M_ORB.SP3.gz`, `…_05M_CLK.CLK.gz`, `IGS0OPSRAP_…` | — |

**Rare versions.** The few real RINEX 3.00 and 3.01 obs files in the corpus came from the
ordinary daily `YYd/` directories of 2017 and 2020: `STK200JPN`, `KOKV00USA`, `USN900USA`
and `WUHN00CHN`. To find more, screen more stations and days there. A guessed MGEX campaign
path (`data/campaign/mgex/daily/rinex3/…`) listed nothing, so don't rely on it.

Notes:

- **Compression era.** Files from before about 2021 are Unix-compress **`.Z`**. Newer
  ones are **`.gz`**. Both occur in the same tree, so a reader must handle both.
- **The version field varies.** Old programs write `2` or `2.1` in the version field
  (columns 1–9). Parse it as a number.
- **Hatanaka** applies to obs files only: CRINEX 1.0 for RINEX 2, 3.0 for RINEX 3–4.01,
  and 3.1 for RINEX 4.02+.
- `data/daily/YYYY/DDD/` itself lists only `YYDDD.status`, `YYDDD.V3status` and the
  checksum files; the data lives in the subdirectories.

## 4. A minimal client

```python
from urllib.parse import urljoin, urlparse
import requests

EARTHDATA = "urs.earthdata.nasa.gov"
BASE = "https://cddis.nasa.gov/archive/gnss/"

class EarthdataAuth(requests.auth.AuthBase):
    def __init__(self, user, password):
        self._basic = requests.auth.HTTPBasicAuth(user, password)
    def __call__(self, r):
        return self._basic(r) if urlparse(r.url).hostname == EARTHDATA else r

def get(session, url, **kw):
    for _ in range(10):
        r = session.get(url, allow_redirects=False, timeout=120, **kw)
        if r.status_code not in (301, 302, 303, 307, 308):
            return r
        url = urljoin(url, r.headers["Location"]).replace("http://", "https://", 1)
    raise RuntimeError("too many redirects")

user, password = open(cred_path).read().strip().splitlines()[:2]
s = requests.Session()
s.auth = EarthdataAuth(user.strip(), password.strip())
s.headers["User-Agent"] = "rinexconvert/0.1"
listing = get(s, BASE + "data/daily/2026/brdc/*?list").text
data = get(s, BASE + "data/daily/2026/brdc/BRD400DLR_S_20262740000_01D_MN.rnx.gz").content
```

Always check that `data` isn't HTML (`b"<html"` in the first 500 bytes) before you use it.

## 5. Fallbacks

- **Anonymous FTPS:** host `gdc.cddis.eosdis.nasa.gov`, user `anonymous`, password = the
  user's e-mail, then `prot_p()`. It has the same tree under `/gnss/`. See
  `reference/squidy/fetch_data.py:connect`.
- **BKG mirror, no login:** `https://igs.bkg.bund.de/root_ftp/IGS/`, laid out as
  `obs/YYYY/DDD/`, `BRDC/YYYY/DDD/` and `products/WWWW/` (see
  `reference/customkf/bkg_fetch.py`). It holds IGS stations only, not all of CDDIS.

## 6. The test corpus

`tools/build_corpus.py` built `data/corpus/` from these paths: 480 files, organised as
`<obs|nav|met>/v<version>/`. To extend it, add days or directories to `OBS_DIRS`,
`NAV_DIRS`, `MET_DIRS` or `BRDC_DAYS` and re-run it. Files already present are skipped. To
check a copied corpus offline:

```
python tools/build_corpus.py --verify
```
