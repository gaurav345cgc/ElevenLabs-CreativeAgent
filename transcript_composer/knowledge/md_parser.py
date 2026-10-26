"""Parse meditation pattern markdown corpus into structured documents."""

from __future__ import annotations

import re

from models.validation import COMPOSITION_SLOTS
from transcript_composer.knowledge.models import (
    ExamplesDocument,
    MeditationExampleEntry,
    PatternFamilyEntry,
    PatternIndexDocument,
)
from transcript_composer.knowledge.taxonomy import (
    DEFAULT_PATTERN_BY_SLOT,
    FAMILY_COMPOSITION_SLOTS,
    expand_wound_ids,
    extract_wound_id_from_text,
    normalize_generation,
    normalize_wound_id,
    parse_generation_codes,
    parse_pillar_codes,
    parse_stage_numbers,
)

FIELD_PATTERN = re.compile(r"^- \*\*(?P<key>[^*]+):\*\* (?P<value>.+)$")
FAMILY_HEADER_PATTERN = re.compile(r"^### Family: `(?P<family>[^`]+)`")
PATTERN_HEADER_PATTERN = re.compile(r"^#### `(?P<pattern>[^`]+)`")
EXAMPLE_SECTION_PATTERN = re.compile(r"^## `(?P<pattern>[^`]+)`")
EXAMPLE_META_PATTERN = re.compile(r"^\*\*Example (?P<num>\d+)\*\* \| (?P<meta>.+)$")
SECTION_META_PATTERN = re.compile(
    r"^\*\*Family:\*\* (?P<family>[^|]+) \| \*\*Placement:\*\* (?P<placement>.+)$"
)


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _merge_unique(existing: list[str], values: list[str]) -> list[str]:
    seen = set(existing)
    for value in values:
        if value and value not in seen:
            existing.append(value)
            seen.add(value)
    return existing


def _merge_unique_ints(existing: list[int], values: list[int]) -> list[int]:
    seen = set(existing)
    for value in values:
        if value not in seen:
            existing.append(value)
            seen.add(value)
    return existing


def parse_pattern_index_markdown(text: str) -> PatternIndexDocument:
    current_family = ""
    patterns: list[PatternFamilyEntry] = []
    current_pattern: str | None = None
    block_lines: list[str] = []

    def flush_pattern() -> None:
        nonlocal current_pattern, block_lines
        if not current_pattern or not current_family:
            block_lines = []
            return

        block = "\n".join(block_lines)
        composition_slot = FAMILY_COMPOSITION_SLOTS.get(current_family)
        if composition_slot is None:
            block_lines = []
            current_pattern = None
            return

        fields: dict[str, str] = {}
        for line in block_lines:
            field_match = FIELD_PATTERN.match(line.strip())
            if field_match:
                fields[field_match.group("key").strip().lower()] = field_match.group("value").strip()

        wound_ids: list[str] = []
        generation_codes: list[str] = []
        stage_numbers: list[int] = []
        pillar_codes: list[str] = []
        tone_notes: list[str] = []

        in_applicable = False
        for line in block_lines:
            stripped = line.strip()
            if stripped.startswith("**Applicable to:**"):
                in_applicable = True
                continue
            if not in_applicable or not stripped.startswith("|"):
                continue
            if "---" in stripped:
                continue

            cells = _split_table_row(stripped)
            if len(cells) < 4 or cells[0].lower() == "generation":
                continue

            wound_cell = cells[2] if len(cells) > 2 else ""
            stage_cell = cells[3] if len(cells) > 3 else ""
            pillar_cell = cells[6] if len(cells) > 6 else cells[5] if len(cells) > 5 else ""
            mood_cell = cells[-1] if cells else ""

            _merge_unique(generation_codes, parse_generation_codes(cells[0]))

            expanded = expand_wound_ids(wound_cell)
            if expanded:
                _merge_unique(wound_ids, expanded)
            else:
                wound_id = normalize_wound_id(wound_cell) or extract_wound_id_from_text(cells[1])
                if wound_id:
                    _merge_unique(wound_ids, [wound_id])

            _merge_unique_ints(stage_numbers, parse_stage_numbers(stage_cell))
            _merge_unique(pillar_codes, parse_pillar_codes(pillar_cell))
            if mood_cell and mood_cell not in {"Closing tone", "Mood states"}:
                tone_notes.append(mood_cell)

        patterns.append(
            PatternFamilyEntry(
                pattern_family=current_pattern,
                family=current_family,
                composition_slot=composition_slot,
                placement=fields.get("placement", composition_slot),
                canonical_pattern=fields.get("canonical pattern", ""),
                wound_ids=wound_ids,
                generation_codes=generation_codes,
                stage_numbers=sorted(stage_numbers),
                pillar_codes=pillar_codes,
                instruction_rule=fields.get("instruction rule", ""),
                use_case=fields.get("use case", ""),
                tone_notes="; ".join(dict.fromkeys(tone_notes)),
            )
        )
        block_lines = []
        current_pattern = None

    for raw_line in text.replace("\r\n", "\n").splitlines():
        line = raw_line.rstrip()

        family_match = FAMILY_HEADER_PATTERN.match(line.strip())
        if family_match:
            flush_pattern()
            current_family = family_match.group("family")
            continue

        pattern_match = PATTERN_HEADER_PATTERN.match(line.strip())
        if pattern_match:
            flush_pattern()
            current_pattern = pattern_match.group("pattern")
            block_lines = [line]
            continue

        if current_pattern is not None:
            if line.strip() == "---":
                flush_pattern()
                continue
            block_lines.append(line)

    flush_pattern()

    return PatternIndexDocument(
        schema_version="1.0",
        composition_slots=list(COMPOSITION_SLOTS),
        default_pattern_by_slot=DEFAULT_PATTERN_BY_SLOT,
        patterns=patterns,
    )


def _parse_example_context(meta: str) -> dict[str, str | int | None]:
    mood_match = re.search(r"\*(?P<mood>[^*]+)\*$", meta.strip())
    mood = mood_match.group("mood").strip() if mood_match else ""
    context_text = meta[: mood_match.start()].strip() if mood_match else meta.strip()
    parts = [part.strip() for part in re.split(r"\s*[·•]\s*", context_text)]

    generation = normalize_generation(parts[0]) if parts else None
    wound_id = extract_wound_id_from_text(parts[1]) if len(parts) > 1 else None
    stage_numbers = parse_stage_numbers(parts[2]) if len(parts) > 2 else []
    stage_no = stage_numbers[0] if stage_numbers else 1
    pillar_codes = parse_pillar_codes(parts[3]) if len(parts) > 3 else []

    return {
        "generation_code": generation or "all_generations",
        "wound_id": wound_id or "all_generations",
        "stage_no": stage_no,
        "pillar_code": pillar_codes[0] if pillar_codes else None,
        "tone_notes": mood,
    }


def _split_example_contexts(meta: str) -> list[str]:
    contexts: list[str] = []
    for chunk in meta.split(" + "):
        chunk = chunk.strip()
        if not chunk:
            continue
        if re.search(r"\([A-Z]{2}-\d{2}\)", chunk):
            contexts.append(chunk)
            continue

        if contexts:
            contexts[-1] = f"{contexts[-1]} + {chunk}"
        else:
            contexts.append(chunk)
    return contexts or [meta]


def parse_examples_markdown(text: str) -> ExamplesDocument:
    examples: list[MeditationExampleEntry] = []
    current_pattern = ""
    current_family = ""
    current_placement = ""
    current_guidance = ""

    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()

        section_match = EXAMPLE_SECTION_PATTERN.match(line)
        if section_match:
            current_pattern = section_match.group("pattern")
            current_family = ""
            current_placement = ""
            current_guidance = ""
            index += 1
            if index < len(lines):
                meta_match = SECTION_META_PATTERN.match(lines[index].strip())
                if meta_match:
                    current_family = meta_match.group("family").strip()
                    current_placement = meta_match.group("placement").strip()
                    index += 1
            while index < len(lines) and lines[index].strip() and not lines[index].strip().startswith(
                "**Example "
            ):
                guidance_line = lines[index].strip()
                if guidance_line.startswith("**What makes this pattern work:**"):
                    current_guidance = guidance_line.replace(
                        "**What makes this pattern work:**", ""
                    ).strip()
                    index += 1
                    break
                index += 1
            continue

        example_match = EXAMPLE_META_PATTERN.match(line)
        if example_match and current_pattern:
            example_num = example_match.group("num")
            meta = example_match.group("meta")
            excerpt = ""
            use_case = ""

            index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1
            if index < len(lines) and lines[index].strip().startswith(">"):
                excerpt = lines[index].strip().lstrip(">").strip()
                index += 1

            while index < len(lines) and not lines[index].strip():
                index += 1
            if index < len(lines) and lines[index].strip().startswith("*What to notice:"):
                use_case = lines[index].strip().strip("*").replace("What to notice:", "").strip()
                index += 1

            for context_index, context_meta in enumerate(_split_example_contexts(meta), start=1):
                parsed = _parse_example_context(context_meta)
                suffix = f"_{context_index}" if context_index > 1 else ""
                examples.append(
                    MeditationExampleEntry(
                        example_id=f"{current_pattern}_ex{example_num}{suffix}",
                        generation_code=str(parsed["generation_code"]),
                        wound_id=str(parsed["wound_id"]),
                        stage_no=int(parsed["stage_no"]),
                        pillar_code=parsed["pillar_code"],  # type: ignore[arg-type]
                        pattern_family=current_pattern,
                        pattern_group=current_family,
                        placement=current_placement,
                        pattern_guidance=current_guidance,
                        use_case=use_case or f"{current_family} example",
                        tone_notes=str(parsed["tone_notes"]),
                        reference_excerpt=excerpt,
                    )
                )
            continue

        index += 1

    return ExamplesDocument(schema_version="1.0", examples=examples)
