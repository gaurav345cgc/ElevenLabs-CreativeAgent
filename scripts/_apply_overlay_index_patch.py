"""One-shot: apply First-10 overlay rows + new variants into meditation_patterns_index.md."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "transcript_composer" / "data" / "meditation_patterns_index.md"


def _splice(text: str, anchor: str, new_rows: list[str]) -> str:
    """Replace ``ROW\\n\\n---...`` with ``ROW\\nNEWROWS\\n\\n---...`` (or append rows)."""
    if new_rows[0] in text:
        return text
    if anchor not in text:
        raise SystemExit(f"splice anchor missing:\n{anchor[:180]!r}")
    if "\n\n" in anchor:
        row, rest = anchor.split("\n\n", 1)
        replacement = row + "\n" + "\n".join(new_rows) + "\n\n" + rest
    else:
        replacement = anchor + "\n" + "\n".join(new_rows)
    return text.replace(anchor, replacement, 1)


def _insert_block_before(text: str, before_marker: str, block: str) -> str:
    first = block.strip().splitlines()[0]
    if first in text:
        return text
    if before_marker not in text:
        raise SystemExit(f"before marker missing:\n{before_marker!r}")
    return text.replace(before_marker, block.rstrip() + "\n\n" + before_marker, 1)


def main() -> None:
    text = INDEX.read_text(encoding="utf-8")

    if "### Overlay Wounds" not in text:
        marker = "| Boomer | Disconnection from Body | BO-04 |\n\n### Stages"
        overlay_tax = """| Boomer | Disconnection from Body | BO-04 |

### Overlay Wounds (First-10 life-domain overlays)
| Generation | Wound | Wound ID | Primary Pillar | Typical Stage |
|---|---|---|---|---|
| Gen X / Millennial | Organisational Betrayal | WK-04 | P02 Emotional Regulation | 2–4 |
| Gen X / Millennial | Purpose at Work | WK-05 | P07 Spiritual Inquiry (P05 Cognitive Clarity secondary) | 3–5 |
| Gen X / Boomer | Age / Tech Obsolescence | WK-06 | P05 Cognitive Clarity | 2–3 |
| Boomer / Gen X | Chronic Pain | PH-01 | P03 Somatic Healing | 2–3 |
| Boomer / Gen X / Millennial | Fatigue / Burnout | PH-03 | P04 Deep Rest & Sleep | 2 |
| Gen Z / Millennial | Friendship Loss | FR-01 | P06 Relational Wellbeing | 2–3 |

> Overlay wounds are life-domain overlays on top of the 16 core wounds. They are selected by their own Wound ID and must not be proxied through a core wound.

### Stages"""
        if marker not in text:
            raise SystemExit("taxonomy marker missing")
        text = text.replace(marker, overlay_tax, 1)

    splices: list[tuple[str, list[str]]] = [
        (
            "| All | Cross-generational | — | 1 | Awakening | Seeker | P04 Deep Rest & Sleep | P3 Resilience · P6 Presence | overstimulated |\n\n---\n\n#### `guided_meditation_intro`",
            [
                "| Gen X / Millennial | Purpose at Work | WK-05 | 3–5 | Reflection → Re-Alignment | Practitioner | P07 Spiritual Inquiry · P05 Cognitive Clarity | P10 Meaning-Making · P2 Purpose · P1 Authenticity | steady job, no hate, no why; flat after the milestone |"
            ],
        ),
        (
            "| Boomer | Disconnection from Body | BO-04 | 1–2 | Awakening / Stabilisation | Seeker | P03 Somatic Healing | P6 Presence · P3 Resilience · P4 Self-Compassion | stiff, tense, numb |\n\n---\n\n#### `meditation_welcome_intro`",
            [
                '| Gen X / Millennial | Organisational Betrayal | WK-04 | 2–4 | Stabilisation → Pattern Recognition | Seeker / Practitioner | P02 Emotional Regulation | P7 Emotional Intelligence · P4 Self-Compassion · P11 Integrity | anger and grief at a named workplace, "I gave them everything" |',
                "| Gen X / Boomer | Age / Tech Obsolescence | WK-06 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P05 Cognitive Clarity | P1 Authenticity · P4 Self-Compassion · P10 Meaning-Making | tools keep changing, dreading the next system rollout, still useful |",
                "| Boomer / Gen X | Chronic Pain | PH-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P03 Somatic Healing | P4 Self-Compassion · P6 Presence · P3 Resilience | body as the enemy, pain that is not leaving, people stopped asking |",
                '| Boomer / Gen X / Millennial | Fatigue / Burnout | PH-03 | 2 | Stabilisation | Seeker | P04 Deep Rest & Sleep | P4 Self-Compassion · P6 Presence · P3 Resilience | tired as the default, "I\'m fine" cover, sleep no longer restores |',
                '| Gen Z / Millennial | Friendship Loss | FR-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P06 Relational Wellbeing | P5 Belonging · P7 Emotional Intelligence · P4 Self-Compassion | a friendship that faded, hollow ache at a reminder, "when did it end" |',
            ],
        ),
        (
            "| Boomer | Disconnection from Body | BO-04 | 1–2 | Awakening / Stabilisation | Seeker | P03 Somatic Healing | P6 Presence · P3 Resilience · P4 Self-Compassion | stiff, tense, numb |\n\n---\n\n#### `softening_settling_awareness`",
            [
                "| Gen X / Boomer | Age / Tech Obsolescence | WK-06 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P05 Cognitive Clarity | P1 Authenticity · P4 Self-Compassion · P10 Meaning-Making | shoulders braced for the next demo, tired of performing competence |",
                "| Boomer / Gen X | Chronic Pain | PH-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P03 Somatic Healing | P4 Self-Compassion · P6 Presence · P3 Resilience | a position the pain does not have to organise, vigilance easing |",
                "| Boomer / Gen X / Millennial | Fatigue / Burnout | PH-03 | 2 | Stabilisation | Seeker | P04 Deep Rest & Sleep | P4 Self-Compassion · P6 Presence · P3 Resilience | nowhere to be, permission to stop fully, heavy limbs |",
            ],
        ),
        (
            "| Gen Z | Anticipatory Dread | GZ-03 | 1 | Awakening | Seeker | P03 Somatic Healing | P3 Resilience · P6 Presence · P8 Growth Mindset | panicky, pre-sleep anxiety |\n\n---\n\n#### `body_sensation_contact`",
            [
                "| Gen X / Millennial | Organisational Betrayal | WK-04 | 2–4 | Stabilisation → Pattern Recognition | Seeker / Practitioner | P02 Emotional Regulation | P7 Emotional Intelligence · P11 Integrity · P3 Resilience | jaw and chest still armoured after the meeting, heat held as protection |",
                "| Gen X / Millennial | Purpose at Work | WK-05 | 3–5 | Reflection → Re-Alignment | Practitioner | P07 Spiritual Inquiry | P10 Meaning-Making · P2 Purpose · P1 Authenticity | flat weekday body, unhurried, no answer needed yet |",
                "| Boomer / Gen X / Millennial | Fatigue / Burnout | PH-03 | 2 | Stabilisation | Seeker | P04 Deep Rest & Sleep | P4 Self-Compassion · P6 Presence · P3 Resilience | early exhale, tired all the way down, body led not pushed |",
            ],
        ),
        (
            "| Gen Z | Validation Dependency | GZ-04 | 2 | Stabilisation | Seeker | P05 Cognitive Clarity | P4 Self-Compassion · P1 Authenticity · P2 Purpose | exhausted by self-presentation |\n\n---\n\n### Family: `somatic_scan`",
            [
                "| Gen Z / Millennial | Friendship Loss | FR-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P06 Relational Wellbeing | P5 Belonging · P7 Emotional Intelligence · P4 Self-Compassion | held by the chair, supported, the ache of one absent friend |"
            ],
        ),
        (
            "| Gen Z | Anticipatory Dread | GZ-03 | 1 | Awakening | Seeker | P03 Somatic Healing | P3 Resilience · P6 Presence · P8 Growth Mindset | panicky, pre-sleep anxiety |\n\n---\n\n#### `somatic_scan_awareness`",
            [
                "| Gen X / Boomer | Age / Tech Obsolescence | WK-06 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P05 Cognitive Clarity | P1 Authenticity · P4 Self-Compassion · P10 Meaning-Making | chest tight in the rollout meeting, jaw, hands that know the work |",
                "| Boomer / Gen X / Millennial | Fatigue / Burnout | PH-03 | 2 | Stabilisation | Seeker | P04 Deep Rest & Sleep | P4 Self-Compassion · P6 Presence · P3 Resilience | heavy eyelids, leaden limbs, tired top to bottom |",
            ],
        ),
        (
            "| Boomer | Grief Unprocessed | BO-02 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P02 Emotional Regulation | P7 Emotional Intelligence · P4 Self-Compassion · P6 Presence | grief held in body |\n\n---\n\n#### `somatic_scan_exploration`",
            [
                "| Gen X / Millennial | Organisational Betrayal | WK-04 | 2–4 | Stabilisation → Pattern Recognition | Seeker / Practitioner | P02 Emotional Regulation | P7 Emotional Intelligence · P11 Integrity · P3 Resilience | heat in chest and jaw, colder grief underneath, nothing to fix |",
                "| Boomer / Gen X | Chronic Pain | PH-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P03 Somatic Healing | P4 Self-Compassion · P6 Presence · P3 Resilience | named places that hurt, noticed not fought, vigilance fatigue |",
            ],
        ),
        (
            "| All | Cross-generational | — | 1–2 | Awakening / Stabilisation | Seeker | P03 Somatic Healing | P3 Resilience · P6 Presence · P4 Self-Compassion | ambient, restorative |\n\n---\n\n#### `self_love_somatic_scan`",
            [
                "| Gen X / Millennial | Purpose at Work | WK-05 | 3–5 | Reflection → Re-Alignment | Practitioner | P07 Spiritual Inquiry | P10 Meaning-Making · P2 Purpose · P1 Authenticity | curious about the flatness, exploring what is here without needing a why |"
            ],
        ),
        (
            "| Boomer | Grief Unprocessed | BO-02 | 1 | Awakening | Seeker | P01 Mindful Awareness | P7 Emotional Intelligence · P4 Self-Compassion · P6 Presence | grief held in body |\n\n---\n\n### Family: `breath_attention`",
            [
                "| Gen Z / Millennial | Friendship Loss | FR-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P06 Relational Wellbeing | P5 Belonging · P7 Emotional Intelligence · P4 Self-Compassion | heart-space ache at a reminder of one friend, hand on the chest |"
            ],
        ),
        (
            "| All | Cross-generational | — | 1–2 | Awakening / Stabilisation | Seeker | P04 Deep Rest & Sleep | P3 Resilience · P6 Presence | overstimulated, calming ritual |\n\n---\n\n#### `breath_spaciousness`",
            [
                "| Gen X / Millennial | Organisational Betrayal | WK-04 | 2–4 | Stabilisation → Pattern Recognition | Seeker / Practitioner | P02 Emotional Regulation | P7 Emotional Intelligence · P11 Integrity · P3 Resilience | anger riding the breath, let it be here without feeding it |",
                "| Gen X / Boomer | Age / Tech Obsolescence | WK-06 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P05 Cognitive Clarity | P1 Authenticity · P4 Self-Compassion · P10 Meaning-Making | steady breath under the rollout-meeting tightness |",
                "| Boomer / Gen X | Chronic Pain | PH-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P03 Somatic Healing | P4 Self-Compassion · P6 Presence · P3 Resilience | breath beside the pain, not against it |",
                "| Boomer / Gen X / Millennial | Fatigue / Burnout | PH-03 | 2 | Stabilisation | Seeker | P04 Deep Rest & Sleep | P4 Self-Compassion · P6 Presence · P3 Resilience | an early exhale, nothing to earn |",
            ],
        ),
        (
            "| All | Cross-generational | — | 1 | Awakening | Seeker | P04 Deep Rest & Sleep | P3 Resilience · P6 Presence | ambient, restorative |\n\n---\n\n### Family: `mind_reframing_kindness`",
            [
                "| Gen X / Millennial | Purpose at Work | WK-05 | 3–5 | Reflection → Re-Alignment | Practitioner | P07 Spiritual Inquiry | P10 Meaning-Making · P2 Purpose · P1 Authenticity | room around the question, breath wider than the workday |",
                "| Gen Z / Millennial | Friendship Loss | FR-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P06 Relational Wellbeing | P5 Belonging · P7 Emotional Intelligence · P4 Self-Compassion | breath carrying one absent friend, closeness still within reach |",
            ],
        ),
        (
            "| Millennial | Arrival Fallacy | ML-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P01 Mindful Awareness · P05 Cognitive Clarity | P2 Purpose · P1 Authenticity · P10 Meaning-Making | numb success, questioning metrics |\n\n---\n\n### Family: `mind_reframing_oneness`",
            [
                "| Gen X / Millennial | Organisational Betrayal | WK-04 | 2–4 | Stabilisation → Pattern Recognition | Seeker / Practitioner | P02 Emotional Regulation | P7 Emotional Intelligence · P11 Integrity · P3 Resilience | legitimate anger and grief side by side, not self-blame |",
                "| Boomer / Gen X | Chronic Pain | PH-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P03 Somatic Healing | P4 Self-Compassion · P6 Presence · P3 Resilience | pain and comfort both present, neither erased, no cure promised |",
                '| Gen Z / Millennial | Friendship Loss | FR-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P06 Relational Wellbeing | P5 Belonging · P7 Emotional Intelligence · P4 Self-Compassion | "is it my fault?" loosening; ache and gratitude both true |',
            ],
        ),
        (
            "| All | Cross-generational | — | 1–2 | Awakening / Stabilisation | Seeker | Gentle, ambient-appropriate |",
            [
                '| Gen X / Millennial | Organisational Betrayal | WK-04 | 2–4 | Stabilisation → Pattern Recognition | Seeker / Practitioner | Level and steady; honours the anger as real; no "trust again", no loyalty speech |',
                "| Gen X / Millennial | Purpose at Work | WK-05 | 3–5 | Reflection → Re-Alignment | Practitioner | Quiet and open-ended; leaves the question open; no verdict, no job advice |",
                "| Gen X / Boomer | Age / Tech Obsolescence | WK-06 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | Plain, respectful, unhurried; what you carry is still yours; no upskilling, no pep |",
                "| Boomer / Gen X | Chronic Pain | PH-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | Gentle and companionable; no cure promise, no mind-over-pain |",
                "| Boomer / Gen X / Millennial | Fatigue / Burnout | PH-03 | 2 | Stabilisation | Seeker | Slow and permissive; rest is already yours; nothing to do next; no productivity clause |",
                "| Gen Z / Millennial | Friendship Loss | FR-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | Warm and witnessing; the ache honoured; no outreach homework |",
            ],
        ),
    ]

    for anchor, rows in splices:
        text = _splice(text, anchor, rows)

    distinction = """#### `mind_reframing_distinction`
- **Placement:** middle
- **Canonical pattern:** name the fused pair → separate them gently → rest in the difference → let it land in the body
- **Instruction rule:** Offer one clean distinction between two things the listener has fused (a thing that changes, and a person who is changing). Say it as a noticing, not a verdict, and let it land in the body. Do not argue the listener out of the feeling. No advice.
- **Use case:** Use when Cognitive Clarity owns the session and soothing alone would leave the knot untouched.

**Applicable to:**
| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Gen X / Boomer | Age / Tech Obsolescence | WK-06 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P05 Cognitive Clarity | P1 Authenticity · P4 Self-Compassion · P10 Meaning-Making | system updating, person not outdated; worth is not a version number |

---
"""
    open_q = """#### `mind_reframing_open_question`
- **Placement:** middle
- **Canonical pattern:** name the question → give it room → stay with not-knowing → notice what arrives quietly
- **Instruction rule:** Name the question the listener already carries, then let it stay open. Offer room around it, not an answer. No purpose pep talk and no prescription about the job. Let any sense of meaning arrive quietly, if at all.
- **Use case:** Use for Spiritual Inquiry sessions where the existential why sits inside an ordinary working life.

**Applicable to:**
| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Gen X / Millennial | Purpose at Work | WK-05 | 3–5 | Reflection → Re-Alignment | Practitioner | P07 Spiritual Inquiry | P10 Meaning-Making · P2 Purpose · P1 Authenticity | "is this what it adds up to?", the part still asking why, a search not a failure |

---
"""
    rest_perm = """#### `affirmation_rest_permission`
- **Placement:** middle
- **Canonical pattern:** notice tiredness → permit stopping → offer rest as already theirs → release the need to be anywhere
- **Instruction rule:** Offer permission statements from the felt sense of tiredness: nowhere to be, nothing to prove, rest already theirs. Never attach a so-that clause and never frame rest as earned. Keep the release soft and slow.
- **Use case:** Use for exhaustion and burnout when Deep Rest is the pillar. Follows settling or breath work.

**Applicable to:**
| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Boomer / Gen X / Millennial | Fatigue / Burnout | PH-03 | 2 | Stabilisation | Seeker | P04 Deep Rest & Sleep | P4 Self-Compassion · P6 Presence · P3 Resilience | tired all the way down, rest is not something to earn, nothing left to prove |

---
"""

    # distinction sits under mind_reframing_kindness (before oneness family)
    text = _insert_block_before(text, "### Family: `mind_reframing_oneness`", distinction)
    # open_question sits under mind_reframing_oneness (before affirmation family)
    text = _insert_block_before(text, "### Family: `affirmation_release`", open_q)
    # rest_permission sits under affirmation_release (before closing family)
    text = _insert_block_before(text, "### Family: `closing_transition`", rest_perm)

    INDEX.write_text(text, encoding="utf-8")
    print(f"patched {INDEX}")
    for code in ("WK-04", "WK-05", "WK-06", "PH-01", "PH-03", "FR-01"):
        print(f"  {code} rows: {text.count(f'| {code} |')}")
    for name in (
        "mind_reframing_distinction",
        "mind_reframing_open_question",
        "affirmation_rest_permission",
    ):
        print(f"  variant {name}: {name in text}")


if __name__ == "__main__":
    main()
