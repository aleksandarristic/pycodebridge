"""Utilities for parsing Codex `/models` output into a list of model ids."""

from __future__ import annotations

import re
from typing import Iterable, List


_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,63}$")


def parse_models_from_lines(lines: Iterable[str]) -> List[str]:
    """Parse model ids from Codex `/models` output lines.

    The output format may vary, so this uses conservative heuristics:
    - Prefer values wrapped in backticks.
    - Otherwise, strip common bullets/numbering and take the first token.
    - Keep ids in first-seen order and de-duplicate.
    """
    seen: dict[str, None] = {}
    for raw in lines:
        line = (raw or "").strip()
        if not line:
            continue

        for token in re.findall(r"`([^`]+)`", line):
            token = token.strip()
            if _looks_like_model_id(token):
                seen.setdefault(token, None)

        line = re.sub(r"^[-*•]\s+", "", line)
        line = re.sub(r"^\d+[.)]\s+", "", line)
        token = re.split(r"[\s(,:]", line, maxsplit=1)[0].strip()
        if _looks_like_model_id(token):
            seen.setdefault(token, None)

    return list(seen.keys())


def _looks_like_model_id(token: str) -> bool:
    token = (token or "").strip()
    if not token:
        return False
    if len(token) < 3:
        return False
    if not _MODEL_ID_RE.match(token):
        return False
    # Avoid listing common words that happen to match the charset.
    if token.lower() in {"models", "model", "available", "default", "openai_api_key"}:
        return False
    if "api_key" in token.lower():
        return False
    # Model ids usually include a separator.
    if not any(ch in token for ch in "-._:"):
        return False
    return True
