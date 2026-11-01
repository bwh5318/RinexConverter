"""rinexcore: the shared RINEX core used by rinexconv and rinexqc.

Standard library only (PLAN.md §0). RINEX is handled as bytes and decoded as
latin-1, so every byte survives a read/write cycle (CLAUDE.md rule 7).
"""

__version__ = "0.1.0"
