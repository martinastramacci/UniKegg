"""Shared biological identifier parsing (no partial-token matches)."""

import re

# Preserve complete, incomplete and preliminary EC identifiers. In particular,
# 3.5.1.n3 is not the same annotation as 3.5.1.- and must not be dropped.
EC_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])[0-9]+\.(?:[0-9]+|-)\.(?:[0-9]+|-)\."
    r"(?:[0-9]+|n[0-9]+|-)(?![A-Za-z0-9_.-])"
)


def without_ec_annotations(text):
    """Remove only complete EC annotation blocks, preserving biological parentheses."""
    def replace(match):
        content = match[1] if match[1] is not None else match[2]
        content = re.sub(r"\bEC[: ]+(?=[0-9])", "", content)
        if EC_RE.search(content) and not EC_RE.sub("", content).strip(" ;,"):
            return ""
        return match[0]

    cleaned = re.sub(r"\(EC[: ]+([^()]*)\)|\[EC:([^\[\]]*)\]", replace, text)
    if cleaned == text:
        return text
    cleaned = re.sub(r" +(?=[;,\]])", "", cleaned)
    return re.sub(r" {2,}", " ", cleaned).strip()
