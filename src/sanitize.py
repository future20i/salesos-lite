"""
Data sanitization for AI pipeline.

Replaces PII (emails, phone numbers, URLs) with placeholders before
sending content to an LLM, and restores the original text afterwards.
"""

import re
from typing import Dict

# Regex patterns for PII detection
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"\+?[\d\s\-()]{7,}")
URL_RE = re.compile(r"https?://[^\s]+")

PLACEHOLDER_NAMES: Dict[str, str] = {
    "email": "EMAIL",
    "phone": "PHONE",
    "url": "URL",
}


def _replace_with_placeholder(
    text: str, pattern: re.Pattern, placeholder_name: str
) -> tuple[str, dict[int, str], int]:
    """Replace all occurrences of *pattern* in *text* with indexed placeholders.

    Returns (sanitized_text, mapping_dict, next_index).
    Each mapping dict entry maps the placeholder index -> original match string.
    """
    mapping: dict[int, str] = {}
    idx = 0

    def replacer(m: re.Match) -> str:
        nonlocal idx
        mapping[idx] = m.group(0)
        placeholder = f"[{placeholder_name}_{idx}]"
        idx += 1
        return placeholder

    sanitized = pattern.sub(replacer, text)
    return sanitized, mapping, idx


def sanitize(text: str, rules: list[str] | None = None) -> tuple[str, dict[str, dict[int, str]]]:
    """Replace PII in *text* with placeholders.

    Parameters
    ----------
    text : str
        Raw message content.
    rules : list[str] | None
        Which rules to apply. Defaults to ``["email", "phone", "url"]``.
        Set to a subset to limit sanitisation, e.g. ``["email"]``.

    Returns
    -------
    (sanitized_text, placeholder_mapping)
        *sanitized_text* has placeholders instead of the original PII.
        *placeholder_mapping* is a dict keyed by rule name, each value
        being a dict of ``{index: original_string}``.
    """
    if rules is None:
        rules = ["email", "phone", "url"]

    full_mapping: dict[str, dict[int, str]] = {}
    current_text = text

    for rule in rules:
        if rule == "email":
            current_text, mapping, _ = _replace_with_placeholder(
                current_text, EMAIL_RE, "EMAIL"
            )
            full_mapping["email"] = mapping
        elif rule == "phone":
            current_text, mapping, _ = _replace_with_placeholder(
                current_text, PHONE_RE, "PHONE"
            )
            full_mapping["phone"] = mapping
        elif rule == "url":
            current_text, mapping, _ = _replace_with_placeholder(
                current_text, URL_RE, "URL"
            )
            full_mapping["url"] = mapping

    return current_text, full_mapping


def desanitize(text: str, mapping: dict[str, dict[int, str]]) -> str:
    """Restore original PII values from *mapping* into *text*.

    Parameters
    ----------
    text : str
        Text containing placeholders like ``[EMAIL_0]``, ``[PHONE_1]`` etc.
    mapping : dict[str, dict[int, str]]
        Mapping produced by :func:`sanitize`.

    Returns
    -------
    str
        Original text with PII restored.
    """
    result = text
    for rule_name, entries in mapping.items():
        placeholder_base = PLACEHOLDER_NAMES.get(rule_name, rule_name.upper())
        # Sort descending by index so we don't corrupt earlier replacements
        for idx in sorted(entries.keys(), reverse=True):
            placeholder = f"[{placeholder_base}_{idx}]"
            result = result.replace(placeholder, entries[idx])
    return result
