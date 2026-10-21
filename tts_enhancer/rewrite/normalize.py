"""Punctuation and spoken-form normalization."""

from __future__ import annotations

import re

NUMBER_PATTERN = re.compile(r"\b(\d{1,3}(?:,\d{3})*|\d+)(?:\.(\d+))?\b")
ACRONYM_PATTERN = re.compile(r"\b([A-Z]{2,6})\b")
MULTI_PUNCT = re.compile(r"([!?])\1+")
SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?])")


_ONES = {
    0: "zero",
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
    18: "eighteen",
    19: "nineteen",
}
_TENS = {
    2: "twenty",
    3: "thirty",
    4: "forty",
    5: "fifty",
    6: "sixty",
    7: "seventy",
    8: "eighty",
    9: "ninety",
}

_ACRONYM_OVERRIDES = {
    "AI": "A I",
    "API": "A P I",
    "TTS": "T T S",
    "UI": "U I",
}


def normalize_punctuation(text: str) -> str:
    text = SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = MULTI_PUNCT.sub(r"\1", text)
    text = re.sub(r"\s*—\s*", ", ", text)
    text = re.sub(r"\s*:\s*", ", ", text)
    text = re.sub(r",\s*,+", ", ", text)
    return text.strip()


def number_to_words(value: int) -> str:
    if value < 20:
        return _ONES[value]
    if value < 100:
        tens, ones = divmod(value, 10)
        if ones == 0:
            return _TENS[tens]
        return f"{_TENS[tens]} {_ONES[ones]}"
    if value < 1000:
        hundreds, remainder = divmod(value, 100)
        if remainder == 0:
            return f"{_ONES[hundreds]} hundred"
        return f"{_ONES[hundreds]} hundred {number_to_words(remainder)}"
    if value < 1_000_000:
        thousands, remainder = divmod(value, 1000)
        prefix = f"{number_to_words(thousands)} thousand"
        if remainder == 0:
            return prefix
        return f"{prefix} {number_to_words(remainder)}"
    return str(value)


def normalize_numbers(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []

    def replace(match: re.Match[str]) -> str:
        whole = match.group(1).replace(",", "")
        decimal = match.group(2)
        try:
            value = int(whole)
        except ValueError:
            return match.group(0)
        spoken = number_to_words(value)
        if decimal:
            spoken = f"{spoken} point {' '.join(_ONES[int(d)] if int(d) in _ONES else d for d in decimal)}"
            notes.append(f"{match.group(0)} -> {spoken}")
        elif value <= 999:
            notes.append(f"{match.group(0)} -> {spoken}")
        return spoken

    return NUMBER_PATTERN.sub(replace, text), notes


def normalize_acronyms(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []

    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        spoken = _ACRONYM_OVERRIDES.get(token, " ".join(token))
        if spoken != token:
            notes.append(f"{token} -> {spoken}")
        return spoken

    return ACRONYM_PATTERN.sub(replace, text), notes


def normalize_tokens(text: str) -> tuple[str, list[str]]:
    text, number_notes = normalize_numbers(text)
    text, acronym_notes = normalize_acronyms(text)
    return text, number_notes + acronym_notes
