# Oracles

Outside programs the tests may run to cross-check (CLAUDE.md rule 2): never run by shipped
code, and a test that needs a missing one is skipped. Each sits in `tools/oracles/<name>/`
(gitignored); this file is the record.

| Name | Version | Source | Retrieved | sha256 |
|---|---|---|---|---|
| RNXCMP package (zip) | 4.2.0, Windows mingw 64-bit | `https://terras.gsi.go.jp/ja/crx2rnx/RNXCMP_4.2.0_Windows_mingw_64bit.zip` (GSI), 203,557 bytes | 2026-11-01 | `58080794cda5a14d7088b921fd75728257e70182d242573e6926d7f8efaa3eae` |
| `rnxcmp/RNX2CRX.exe` | 4.2.0 (`-h`: "ver.4.2.0") | from that zip, 545,044 bytes | 2026-11-01 | `087236f907544016bfc858d855ce10aa0ca69075b2ed8293b0f9b9b2be37f2ae` |
| `rnxcmp/CRX2RNX.exe` | 4.2.0 | from that zip, 338,911 bytes | 2026-11-01 | `bd8f57ce6a314764305a038816e643d9b7d8759f702197108e65fb732e7f1cca` |

The zip's sha256 is the `package_sha256` recorded in
`reference/tools/rnxcmp-4.2.0/provenance.json` (retrieved 2026-09-06), and CRX2RNX.exe is
byte-identical to the copy there, so both programs come from the package the project already
used. The zip holds only the two executables; the GSI licence is in
`reference/tools/rnxcmp-4.2.0/LICENSE.txt`. Citation (GSI licence): Hatanaka, Y. (2008), A
Compression Format and Tools for GNSS Observation Data, Bulletin of the Geospatial
Information Authority of Japan, 55, 21-30.

Not here (2026-11-01, the user's answers): RTKLIB and Anubis come when rinexqc starts;
gfzrnx not now (it needs the user's licence); no teqc copy.
