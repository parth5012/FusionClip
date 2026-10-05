"""Shared catalog-key path helpers for router validators.

The character class lives here as the single source of truth
(`SAFE_REFERENCE_PATTERN`). Spaces are permitted at the predicate level
because uploads keep the user's original filename as the object key
(e.g. ``uploads/my photo.png``) — callers check
``value.replace(" ", "")`` so the pattern itself never drifts.
Traversal/prefix/length rules stay in each router's validator so their
400 messages and None/empty semantics do not change.
"""

import re

#: Allowed characters in a relative catalog key: alphanumerics plus
#: dot, underscore, slash, parentheses and hyphen. No spaces here —
#: use :func:`has_safe_catalog_chars` which strips spaces first.
SAFE_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9._/()-]+$")

MAX_CATALOG_KEY_LENGTH = 256


def has_safe_catalog_chars(value: str) -> bool:
    """Character-class check against the shared pattern (spaces allowed)."""
    return bool(SAFE_REFERENCE_PATTERN.match(value.replace(" ", "")))


def has_path_traversal(value: str) -> bool:
    """True when a catalog key contains traversal or absolute-path shapes."""
    return ".." in value or value.startswith("/") or "\\" in value
