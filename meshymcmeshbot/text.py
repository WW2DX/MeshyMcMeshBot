"""Helpers for fitting text into MeshCore's small message payloads.

MeshCore caps a text payload at ~160 bytes, and on a channel the firmware
prepends "<node name>: ", so we budget in UTF-8 *bytes*, not characters.
"""

ELLIPSIS = "…"


def blen(s: str) -> int:
    return len(s.encode("utf-8"))


def truncate(s: str, max_bytes: int) -> str:
    """Cut s to fit max_bytes, adding an ellipsis if anything was dropped."""
    if blen(s) <= max_bytes:
        return s
    budget = max_bytes - blen(ELLIPSIS)
    out = s.encode("utf-8")[:budget].decode("utf-8", "ignore")
    return out.rstrip() + ELLIPSIS


def chunk(s: str, max_bytes: int) -> list[str]:
    """Split s into pieces of at most max_bytes, preferring word boundaries.

    Explicit newlines are treated as preferred break points too.
    """
    s = s.strip()
    if not s:
        return []
    if blen(s) <= max_bytes:
        return [s]

    parts: list[str] = []
    current = ""
    for line in s.split("\n"):
        for word in line.split(" "):
            if not word:
                continue
            candidate = f"{current} {word}" if current else word
            if blen(candidate) <= max_bytes:
                current = candidate
                continue
            if current:
                parts.append(current)
            # A single word longer than the budget gets hard-split.
            while blen(word) > max_bytes:
                head = word.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")
                parts.append(head)
                word = word[len(head):]
            current = word
        # Newline: close the current piece if the next line won't fit with it.
        if current:
            parts.append(current)
            current = ""
    if current:
        parts.append(current)

    # Re-merge tiny adjacent pieces produced by newline breaks.
    merged: list[str] = []
    for p in parts:
        if merged and blen(merged[-1] + " | " + p) <= max_bytes:
            merged[-1] = merged[-1] + " | " + p
        else:
            merged.append(p)
    return merged


def paginate(s: str, max_bytes: int, max_parts: int) -> list[str]:
    """chunk() with numbered parts ("1/3 ...") and a hard cap on part count."""
    # Reserve room for a "n/m " prefix.
    pieces = chunk(s, max_bytes - 5)
    if len(pieces) <= 1:
        return pieces
    if len(pieces) > max_parts:
        pieces = pieces[:max_parts]
        more = " (DM me for more)"
        pieces[-1] = truncate(pieces[-1], max_bytes - 5 - blen(more)) + more
    total = len(pieces)
    return [f"{i}/{total} {p}" for i, p in enumerate(pieces, 1)]
