"""Shared biological identifier parsing (no partial-token matches)."""

import re

# Preserve complete, incomplete and preliminary EC identifiers. In particular,
# 3.5.1.n3 is not the same annotation as 3.5.1.- and must not be dropped.
EC_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])[0-9]+\.(?:[0-9]+|-)\.(?:[0-9]+|-)\."
    r"(?:[0-9]+|n[0-9]+|-)(?![A-Za-z0-9_.-])"
)
