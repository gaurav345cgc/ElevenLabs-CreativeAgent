"""Section-by-section script generation for Agent 1."""

from __future__ import annotations

from typing import Any, Protocol

from models.metadata import ScriptSection, SectionedScriptContent
from models.requests import CreateTranscriptRequest
from models.metadata import SelectedPatternPlan
from transcript_composer.duration import (
    SessionDurationBudget,
    build_session_duration_budget,
    clamp_slot_word_ceiling,
    count_words,
    format_composer_timing_brief,
)
from transcript_composer.knowledge.models import RankedExample
from transcript_composer.knowledge.pattern_selector import PatternSelector
from transcript_composer.relatability import format_relatability_block
from transcript_composer.theme import format_session_theme_block
from transcript_composer.llm_config import (
    ModelProviderConfigError,
    ensure_dotenv_loaded,
    require_openai_api_key,
    resolve_openai_api_key,
    resolve_openai_model,
    resolve_script_generator_mode,
)

SLOT_LABELS: dict[str, str] = {
    "opening": "Opening",
    "settling": "Settling",
    "body": "Body",
    "breath": "Breath",
    "mind_heart": "Mind and heart",
    "closing": "Closing",
}

INDEX_CORPUS = "meditation_patterns_index.md"
EXAMPLES_CORPUS = "meditation_patterns_examples.md"

ASSEMBLY_FLOW = """\
1. opening — opening_intro family
2. settling — settling_grounding family
3. body — somatic_scan family
4. breath — breath_attention family
5. mind_heart — mind_reframing_kindness / mind_reframing_oneness / affirmation_release
6. closing — closing_transition family"""

SYSTEM_PROMPT = f"""You are Agent 1 — Pattern Transcript Composer.

Write as if you are speaking to one tired, busy person listening on headphones —
not composing an essay, lecture, or workshop script. They want to feel guided,
not flooded with words. Prefer short lines they can absorb and then rest in silence.

Authoritative sources (follow strictly):
- `{INDEX_CORPUS}` — structural blueprint, canonical patterns, instruction rules
- `{EXAMPLES_CORPUS}` — phrasing, pace, and emotional register reference

Hard rules:
1. Implement ONLY the assigned `pattern_family` for this section — do not substitute another pattern.
2. Follow the canonical pattern beats in order — they define the narrative structure.
3. Obey the instruction rule as therapeutic intent — never paste it verbatim.
4. Match register from the examples for the same pattern (invite; do not command; ear-first language).
5. Write NEW original narration — use examples for tone only, never copy excerpts verbatim.
6. Stay within the six-stage assembly flow; do not skip ahead or merge stages.
7. Output spoken narration only — no labels, markdown, pattern names, wound codes, or meta-commentary.
8. Script arc: start with a BRIEF welcome/intro, then move into the main practice. Do not dump
   dense teaching or a long body of cues in the opening — save that for settling / body / breath /
   mind_heart. Listeners should feel greeted and oriented first, then guided into the practice.
9. LEAN language: say each cue once. Prefer fewer, clearer sentences over soft restatements.
   Treat the word target as a ceiling — stay at or under it; do not pad to fill it.
10. NO DUPLICATION: never repeat the same invitation, sensation, or idea in different words
    in this section (or vs the prior section). Advance the practice; do not circle.
11. Consumer mindset: they may only have a few minutes; every sentence must earn its place.
    Soften with silence later — do not soften by saying the same thing three ways.
12. Session length = spoken words (at or under the speech word budget) + later silence holds.
    Never fill wall-clock with speech alone — intentional pauses are inserted after you write.
    Obey the Session timing block in each user message (word ceilings and remaining budget).
13. THEME FIDELITY: honor the Session theme block. If the title/intent is about work, pain,
    friendship, or another life domain, that domain must appear in the spoken narration
    (especially opening + mind_heart + closing). A beautiful generic meditation that ignores
    the stated theme is wrong — even if pattern beats are perfect.
14. RELATABILITY PACK: when a Relatability brief block is present, treat it as authority for
    wound scene, must-use phrases, must-not-say, pillar feel, generation register, and the
    mind_heart core reframe. Do not write a generic calm script that could fit another wound."""


class ScriptGenerator(Protocol):
    def generate_sections(
        self,
        request: CreateTranscriptRequest,
        plan: SelectedPatternPlan,
        example_refs: dict[str, list[RankedExample]],
        selector: PatternSelector,
    ) -> SectionedScriptContent: ...


class TemplateScriptGenerator:
    """Deterministic offline generator for tests and fallback mode."""

    def generate_sections(
        self,
        request: CreateTranscriptRequest,
        plan: SelectedPatternPlan,
        example_refs: dict[str, list[RankedExample]],
        selector: PatternSelector,
    ) -> SectionedScriptContent:
        sections: list[ScriptSection] = []
        for slot_selection in plan.slots:
            pattern = selector.get_pattern_metadata(slot_selection.pattern_family)
            ranked = example_refs.get(slot_selection.slot) or []
            top_example = ranked[0].example if ranked else None

            instruction = pattern.instruction_rule if pattern else ""
            use_case = pattern.use_case if pattern else ""
            tone_notes = pattern.tone_notes if pattern else ""
            if top_example and top_example.tone_notes:
                tone_notes = top_example.tone_notes

            sentences = _build_template_section_sentences(
                slot=slot_selection.slot,
                instruction=instruction,
                use_case=use_case,
                tone_notes=tone_notes,
                target_minutes=request.target_duration_minutes,
            )
            sections.append(
                ScriptSection(
                    slot=slot_selection.slot,
                    title=SLOT_LABELS.get(slot_selection.slot, slot_selection.slot),
                    text=" ".join(sentences),
                )
            )

        return SectionedScriptContent(sections=sections)


class OpenAIScriptGenerator:
    """Generate narration with one OpenAI call per composition section."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._model = model or resolve_openai_model()
        self._client = client or self._build_client(api_key or require_openai_api_key())

    def generate_sections(
        self,
        request: CreateTranscriptRequest,
        plan: SelectedPatternPlan,
        example_refs: dict[str, list[RankedExample]],
        selector: PatternSelector,
    ) -> SectionedScriptContent:
        sections: list[ScriptSection] = []
        prior_excerpt = ""
        budget = build_session_duration_budget(request.target_duration_minutes)
        words_used = 0

        for slot_selection in plan.slots:
            pattern = selector.get_pattern_metadata(slot_selection.pattern_family)
            ranked = example_refs.get(slot_selection.slot) or []
            same_family = [
                item
                for item in ranked
                if item.example.pattern_family == slot_selection.pattern_family
            ]
            examples_for_prompt = (same_family or ranked)[:3]
            slot_ceiling = _target_words_for_slot(
                request.target_duration_minutes,
                slot_selection.slot,
            )
            remaining = budget.speech_budget_words - words_used
            target_words = clamp_slot_word_ceiling(slot_ceiling, remaining)

            text = self._generate_section_text(
                request=request,
                slot=slot_selection.slot,
                pattern_family=slot_selection.pattern_family,
                pattern=pattern,
                ranked_examples=examples_for_prompt,
                plan=plan,
                selector=selector,
                prior_excerpt=prior_excerpt,
                target_words=target_words,
                words_used_so_far=words_used,
                budget=budget,
            )
            sections.append(
                ScriptSection(
                    slot=slot_selection.slot,
                    title=SLOT_LABELS.get(slot_selection.slot, slot_selection.slot),
                    text=text,
                )
            )
            words_used += count_words(text)
            prior_excerpt = text[-400:]

        return SectionedScriptContent(sections=sections)

    def _generate_section_text(
        self,
        *,
        request: CreateTranscriptRequest,
        slot: str,
        pattern_family: str,
        pattern: Any,
        ranked_examples: list[RankedExample],
        plan: SelectedPatternPlan,
        selector: PatternSelector,
        prior_excerpt: str,
        target_words: int,
        words_used_so_far: int = 0,
        budget: SessionDurationBudget | None = None,
    ) -> str:
        user_prompt = _build_section_prompt(
            request=request,
            slot=slot,
            pattern_family=pattern_family,
            pattern=pattern,
            ranked_examples=ranked_examples,
            plan=plan,
            selector=selector,
            prior_excerpt=prior_excerpt,
            target_words=target_words,
            words_used_so_far=words_used_so_far,
            budget=budget,
        )
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
        )
        content = response.choices[0].message.content
        if not content or not content.strip():
            raise RuntimeError(f"OpenAI returned empty narration for slot {slot!r}")
        return content.strip()

    @staticmethod
    def _build_client(api_key: str) -> Any:
        from openai import OpenAI

        return OpenAI(api_key=api_key)


def get_default_script_generator() -> ScriptGenerator:
    """Select generator from CREATIVE_AGENT_SCRIPT_GENERATOR (auto|openai|template)."""
    ensure_dotenv_loaded()
    mode = resolve_script_generator_mode()
    if mode == "template":
        return TemplateScriptGenerator()
    if mode == "openai":
        return OpenAIScriptGenerator()
    if resolve_openai_api_key():
        return OpenAIScriptGenerator()
    return TemplateScriptGenerator()


def script_generator_name(generator: ScriptGenerator) -> str:
    if isinstance(generator, OpenAIScriptGenerator):
        return "openai"
    if isinstance(generator, TemplateScriptGenerator):
        return "template"
    return type(generator).__name__


def _target_words_for_slot(target_duration_minutes: int, slot: str) -> int:
    """Opening stays brief; remaining sections share the *speech* budget.

    Total words are sized to ``speech_share`` of wall-clock so pause holds can
    fill the rest and advertised length (speech + holds) hits the target.
    """
    budget = build_session_duration_budget(target_duration_minutes)
    total_words = budget.speech_budget_words
    if slot == "opening":
        # Brief welcome only — ~6–10% of speech words.
        return max(35, min(70, total_words // 12))
    opening_budget = max(35, min(70, total_words // 12))
    remaining = max(total_words - opening_budget, total_words // 2)
    # Ceiling per body section; leaner floor so OpenAI is not pushed to pad.
    return max(55, remaining // 5)


def _target_words_per_section(target_duration_minutes: int) -> int:
    """Backward-compatible average budget (tests / callers). Prefer ``_target_words_for_slot``."""
    return _target_words_for_slot(target_duration_minutes, "settling")


def _build_section_prompt(
    *,
    request: CreateTranscriptRequest,
    slot: str,
    pattern_family: str,
    pattern: Any,
    ranked_examples: list[RankedExample],
    plan: SelectedPatternPlan,
    selector: PatternSelector,
    prior_excerpt: str,
    target_words: int,
    words_used_so_far: int = 0,
    budget: SessionDurationBudget | None = None,
) -> str:
    instruction = pattern.instruction_rule if pattern else ""
    use_case = pattern.use_case if pattern else ""
    tone_notes = pattern.tone_notes if pattern else ""
    canonical_pattern = pattern.canonical_pattern if pattern else ""
    family = pattern.family if pattern else ""
    placement = pattern.placement if pattern else slot

    continuity = (
        f"Prior section ending (continue the arc; do NOT restate or paraphrase "
        f"any cue already said):\n{prior_excerpt}\n"
        if prior_excerpt
        else "This is the first section."
    )
    title_hint = request.title_hint or "(none)"
    principles = ", ".join(request.principles) if request.principles else "(none)"
    theme_block = format_session_theme_block(request)
    relatability_block = format_relatability_block(request)
    session_budget = budget or build_session_duration_budget(
        request.target_duration_minutes
    )
    timing_brief = format_composer_timing_brief(
        session_budget,
        slot=slot,
        slot_word_ceiling=target_words,
        words_used_so_far=words_used_so_far,
    )

    opening_rules = ""
    if slot == "opening":
        opening_rules = """
## Opening section rules (brief intro only)
- Keep this SHORT: a warm welcome, name the purpose of this moment using the Session theme
  (if the title is about work / pain / friendship, say that in plain language), invite arrival.
- If a Relatability brief is present, land in THAT wound's specific scene (see gold opening tone).
- Typically 3–5 short spoken lines (~35–70 words). Do not begin body scans, long breath drills, or deep teaching here.
- End by gently inviting them into the practice that follows (settling / body) — then stop.
- Do not overwhelm with words; leave space for the next sections to carry the main guidance.
"""
    elif slot == "settling":
        opening_rules = """
## After the intro
- The opening already welcomed the listener. Now begin the main practice: posture, comfort, settling in.
- Do not re-welcome at length; transition from arrival into embodied settling.
"""
    elif slot == "mind_heart":
        opening_rules = """
## Mind and heart
- Return explicitly to the Session theme (work / wound / life domain from the title).
- If a Relatability brief is present, deliver the mind_heart_core reframe (paraphrase OK).
- Keep it invitational and ear-first — no lecture, no diagnosing.
"""
    elif slot == "closing":
        opening_rules = """
## Closing
- Close the arc of THIS theme (not a generic goodbye that could fit any meditation).
- If a Relatability brief is present, echo the closing_promise tone.
"""

    relatability_section = f"\n{relatability_block}\n" if relatability_block else ""

    return f"""Compose the **{SLOT_LABELS.get(slot, slot)}** section (`{slot}`) for this guided meditation.

Listener mindset: one tired, busy person — clear, sparse, kind. No filler.

## Script assembly ({INDEX_CORPUS})
{ASSEMBLY_FLOW}

## Selected plan for this script (do not change)
{_format_plan_table(plan)}

## Your assigned pattern for THIS section (strict)
- composition_slot: {slot}
- pattern_family: `{pattern_family}` (required — do not use a different pattern)
- pattern_group: `{family}`
- placement: `{placement}`
- canonical_pattern beats (follow in order): {canonical_pattern or "(see instruction rule)"}
- instruction_rule: {instruction}
- use_case: {use_case}
- mood/tone notes from index: {tone_notes or "(none)"}
{opening_rules}
{timing_brief}

{theme_block}
{relatability_section}
## Brief / taxonomy (codes are internal — speak the theme, not the codes)
- content_type: {request.content_type}
- generation: {request.generation_code}
- wound: {request.wound_id}
- stage: {request.stage_no}
- pillar: {request.pillar_code or "(none)"}
- principles: {principles}
- title_hint: {title_hint}

## Anti-duplication
- One idea per sentence; one sentence per idea.
- Do not rephrase the same invitation ("soften… allow… notice…" loops).
- Do not echo the prior section's lines in new wording.

## Tone references ({EXAMPLES_CORPUS}) for `{pattern_family}`
{_format_example_references(ranked_examples)}

## Continuity
{continuity}

Write lean original spoken narration that strictly implements `{pattern_family}` and its canonical beats for this brief.
Honor the Session theme and Relatability brief when present. Stay at or under this section's hard word ceiling. Return narration text only."""

def _format_plan_table(plan: SelectedPatternPlan) -> str:
    lines = []
    for index, slot_selection in enumerate(plan.slots, start=1):
        lines.append(
            f"{index}. {slot_selection.slot} → `{slot_selection.pattern_family}`"
        )
    return "\n".join(lines)


def _format_example_references(ranked_examples: list[RankedExample]) -> str:
    if not ranked_examples:
        return "(No examples in corpus for this pattern — follow index canonical pattern and instruction rule strictly.)"

    blocks: list[str] = []
    guidance = ""
    for index, ranked in enumerate(ranked_examples, start=1):
        example = ranked.example
        if example.pattern_guidance and not guidance:
            guidance = example.pattern_guidance
        blocks.append(
            f"""Example {index} [{example.example_id}] (match: {ranked.match_tier}, score: {ranked.score})
- context: {example.generation_code} / {example.wound_id} / stage {example.stage_no} / {example.pillar_code or "n/a"}
- mood: {example.tone_notes or "(none)"}
- what_to_notice: {example.use_case}
- reference_excerpt (tone only — do not copy): {example.reference_excerpt}"""
        )

    header = ""
    if guidance:
        header = f"What makes this pattern work: {guidance}\n\n"

    return header + "\n\n".join(blocks)


def _build_template_section_sentences(
    *,
    slot: str,
    instruction: str,
    use_case: str,
    tone_notes: str,
    target_minutes: int,
) -> list[str]:
    """Offline scaffold — spoken narration only (never paste index instruction/use-case text)."""
    min_words = 25
    sentences = [_slot_opener(slot)]
    for filler in _slot_fillers(slot):
        if _word_count(" ".join(sentences)) >= min_words:
            break
        sentences.append(filler)
    if tone_notes and _word_count(" ".join(sentences)) < min_words + 8:
        sentences.append(
            f"You might notice a quality of {tone_notes.lower().rstrip('.')} in how this unfolds."
        )
    while _word_count(" ".join(sentences)) < min_words:
        sentences.append(
            "Stay with what is here now, without needing to change or fix anything."
        )
    return sentences


def _word_count(text: str) -> int:
    return len(text.split())


def _slot_fillers(slot: str) -> list[str]:
    fillers: dict[str, list[str]] = {
        "opening": [
            "Welcome. You are invited to pause here for a few quiet minutes.",
            "Nothing is required of you except to arrive gently into this practice.",
        ],
        "settling": [
            "Feel the support beneath you and let your body know it can soften.",
            "There is no performance here — only a quiet arrival into presence.",
        ],
        "body": [
            "Move attention slowly, noticing sensation without rushing toward a goal.",
            "If an area feels tight or numb, meet it with patience rather than force.",
        ],
        "breath": [
            "Follow the natural rhythm of inhale and exhale, without changing it.",
            "When the mind drifts, return gently to the feeling of breath in the body.",
        ],
        "mind_heart": [
            "Thoughts and feelings may come and go — you can let them pass like weather.",
            "Meet whatever arises with kindness, as you would for someone you care about.",
        ],
        "closing": [
            "Take a moment to notice how you feel now, however subtle the shift may be.",
            "Carry this steadiness with you as you move back into your day.",
        ],
    }
    return fillers.get(slot, fillers["opening"])


def _slot_opener(slot: str) -> str:
    openers = {
        "opening": "Welcome. Let this be a brief arrival before we begin.",
        "settling": "Find a position you can rest in without effort.",
        "body": "Bring your attention gently into the body.",
        "breath": "Let your breath become a quiet anchor.",
        "mind_heart": "Allow thoughts and feelings to move without being pushed away.",
        "closing": "When you are ready, begin to return your awareness to the room around you.",
    }
    return openers.get(slot, "Continue with gentle awareness.")
