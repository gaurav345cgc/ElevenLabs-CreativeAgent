# Claude prompt — GenMyō First-10 relatability knowledge pack

Copy everything inside the fence below into Claude. **No attachments needed** — production plan, wound tables, pillars, and system constraints are embedded.

---

```text
You are a GenMyō content strategist + therapeutic meditation brief writer.

Produce a COMPLETE relatability knowledge pack for our Creative Agent (Pattern Transcript Composer + validators). This pack must make transcripts feel like they were written FOR the exact wound, generation, pillar, and life situation — not generic calm meditations with a new title.

Do NOT ask me for attachments. Everything you need is below.

════════════════════════════════════════════════════════════════
0) PRODUCT + PIPELINE (fixed)
════════════════════════════════════════════════════════════════
- Brand: GenMyō — “honour the person.”
- We license where coverage exists; we PRODUCE OWN content where library is thin/empty.
- Creative Agent pipeline:
  Agent 1 (Pattern Transcript Composer) → RAW_PATTERN
  → SQS → Agent 2 (ElevenLabs Script Doctor) → ELEVENLABS_ENHANCED
  → human or auto approve → APPROVED_FINAL
  → TTS plane (chunk → speech → stitch holds → mix bed → master.mp3)
- Agent 1 voice rules (non-negotiable):
  - Spoken narration only (headphones, one tired person)
  - Invite register: allow / notice / soften / invite — NOT command (breathe/feel/do/must)
  - Never speak codes aloud (GZ-04, gx_01, WK-06, P04, P1, etc.)
  - Lean language; no lecture; no medical claims; no toxic positivity
  - Six sections in order: opening → settling → body → breath → mind_heart → closing
- Current engineering gap we are fixing:
  - Title/situation theme (work/pain/friendship) is PARTLY enforced
  - Pillar fidelity is WEAK (often defaulted to p04)
  - Overlay codes WK/PH/FR are NOT in pattern index yet (proxied to gx/bo/gz)
  - We need briefs + validator seeds so Agent 1 + QA can enforce TOTAL relatability

════════════════════════════════════════════════════════════════
1) TAXONOMY REFERENCE (from pattern index — authoritative)
════════════════════════════════════════════════════════════════

### Generations (API / internal slugs)
| Display | Internal generation_code |
|---|---|
| Gen Z | gen_z |
| Millennial | millennial |
| Gen X | gen_x |
| Boomer | boomer |
| Cross-generational | all_generations |

### Core wounds (already in system — use these slugs)
| Gen | Wound | Product code | Internal wound_id |
|---|---|---|---|
| Gen Z | Identity Diffusion | GZ-01 | gz_01 |
| Gen Z | Belonging Without Roots | GZ-02 | gz_02 |
| Gen Z | Anticipatory Dread | GZ-03 | gz_03 |
| Gen Z | Validation Dependency | GZ-04 | gz_04 |
| Millennial | Arrival Fallacy | ML-01 | ml_01 |
| Millennial | Chronic Overextension | ML-02 | ml_02 |
| Millennial | Authentic Self Suppression | ML-03 | ml_03 |
| Millennial | Relational Erosion | ML-04 | ml_04 |
| Gen X | Invisible Sacrifice | GX-01 | gx_01 |
| Gen X | Emotional Self-Reliance | GX-02 | gx_02 |
| Gen X | Purpose Displacement | GX-03 | gx_03 |
| Gen X | Cynicism as Shield | GX-04 | gx_04 |
| Boomer | Legacy Uncertainty | BO-01 | bo_01 |
| Boomer | Grief Unprocessed | BO-02 | bo_02 |
| Boomer | Identity After Role | BO-03 | bo_03 |
| Boomer | Disconnection from Body | BO-04 | bo_04 |

### Overlay / situational codes (NOT in pattern index yet — you must specify new slugs)
| Product code | Meaning | Notes |
|---|---|---|
| WK-04 | Organisational Betrayal | Work overlay — Gen X heavy |
| WK-05 | Purpose at Work | Work overlay — abstract, hard to license |
| WK-06 | Age / Tech Obsolescence | Work overlay — EMPTY in licensed library |
| PH-01 | Chronic Pain | Physical overlay — Boomer / body |
| PH-03 | Fatigue / Burnout | Physical overlay — body |
| FR | Friendship overlays | Loneliness / friendship loss — Gen Z sparse |
| RL | Relationship overlays | Dating/breakup — out of First-10 scope (mention only if needed for contrast) |

### Stages
| No | Name | Arc |
|---|---|---|
| 1 | Awakening | Seeker |
| 2 | Stabilisation | Seeker |
| 3 | Reflection | Practitioner |
| 4 | Pattern Recognition | Practitioner |
| 5 | Re-Alignment | Practitioner |
| 6 | Inner Growth | Contributor |

Default for First-10 shorts/micros: stage_no = 2 unless you justify otherwise.

### Pillars (ONLY these — do not invent P08–P11)
| Code | Name | Category |
|---|---|---|
| P01 / p01 | Mindful Awareness | Body Awareness |
| P02 / p02 | Emotional Regulation | Stress & Recovery |
| P03 / p03 | Somatic Healing | Body Awareness |
| P04 / p04 | Deep Rest & Sleep | Sleep & Energy |
| P05 / p05 | Cognitive Clarity | Values & Purpose |
| P06 / p06 | Relational Wellbeing | Relationships & Connection |
| P07 / p07 | Spiritual Inquiry | Values & Purpose |
| P12 / p12 | Generativity | Values & Purpose |

### Principles (ONLY these — no P9)
| Code | Name |
|---|---|
| P1 | Authenticity |
| P2 | Purpose |
| P3 | Resilience |
| P4 | Self-Compassion |
| P5 | Belonging |
| P6 | Presence |
| P7 | Emotional Intelligence |
| P8 | Growth Mindset |
| P10 | Meaning-Making |
| P11 | Integrity |
| P12 | Generativity |

Always write principles as “P4 Self-Compassion” (code + name).

### Script assembly families (Agent 1)
1. opening → opening_intro
2. settling → settling_grounding
3. body → somatic_scan
4. breath → breath_attention
5. mind_heart → mind_reframing_kindness / mind_reframing_oneness / affirmation_release
6. closing → closing_transition

════════════════════════════════════════════════════════════════
2) OWN-CONTENT PRODUCTION PLAN (why we produce)
════════════════════════════════════════════════════════════════
Strategy drivers:
- Licensed library has almost NO true short content (few under 10 min). Micros 3–6 min are the biggest gap + cheapest.
- Genuinely thin wounds: GX-01 (2×20min only), BO-04 (1×30min only), Gen Z short-form weak.
- Produce where license cannot fill: work overlays, physical overlays, friendship overlays.

By generation (broader roadmap — First-10 is the CURRENT execution slice):

GEN Z (skew short — acquisition edge)
- GZ-01: 1×4, 1×10
- GZ-04: 1×3, 1×8  ← First-10 includes 3 min
- GZ-02: 1×5
- FR friendship: 2×8–10  ← First-10 includes 8 min
- RL early relationships: 2×6–10 (later)
- SEA local: later

MILLENNIAL (skew mid; core already stronger)
- ML-03: 1×5, 1×12  ← First-10 includes 5 min
- ML-02: 1×4 (later)
- WK work overlays: 3×8–15 (shared with Gen X work set)
- ML-04: 1×6 (later)

GEN X (skew work-heavy)
- GX-01: 1×5, 1×10, 1×15  ← First-10 includes 5 min
- GX-02: 1×5 (later)
- WK-04 Organisational Betrayal: 1×10  ← First-10
- WK-05 Purpose at Work: 1×12  ← First-10
- WK-06 Age/Tech Obsolescence: 1×10  ← First-10 (EMPTY)

BOOMER (skew longer + body)
- BO-04: 1×6, 1×12, 1×20  ← First-10 includes 6 min
- PH-01 Chronic Pain: 1×15  ← First-10
- PH-03 Fatigue/Burnout: 1×12  ← First-10
- BO-03: 1×10 (later)

Length bands:
- Micro 3–6: entry / acute regulation
- Short 8–12: daily practice
- Mid 15–20: deeper seated
- Long 25–30: out of First-10 scope

════════════════════════════════════════════════════════════════
3) FIRST-10 THIN-WOUND WAVE (LOCKED SCOPE — your only delivery set)
════════════════════════════════════════════════════════════════
Ranking rule: empty → near-empty → weakest cores → hard-to-license overlays.
Nothing else enters this wave until these ten are done.

| Rank | Batch | Code | Wound | Gen/overlay | Existing licensed | Length | Words (spoken) | Job |
|---|---|---|---|---|---|---|---|---|
| 1 | A | WK-06 | Age / Tech Obsolescence | Gen X · work | 0 (empty) | 10 min | 1,100–1,300 | Fill empty wound |
| 2 | A | BO-04 | Disconnection from Body | Boomer · body | 1 (30 min) | 6 min | 660–780 | First micro entry |
| 3 | A | GX-01 | Invisible Sacrifice | Gen X · core | 2 (both 20 min) | 5 min | 550–650 | First short for thinnest core |
| 4 | B | GZ-04 | Validation Dependency | Gen Z · core | 3 (10–25 min) | 3 min | 330–390 | Post-scroll micro reset |
| 5 | B | ML-03 | Authentic Self Suppression | Millennial · core | 3 (15–20 min) | 5 min | 550–650 | Thinnest ML short |
| 6 | C | PH-01 | Chronic Pain | Boomer · physical | Thin | 15 min | 1,650–1,950 | Body gap, hard to license |
| 7 | C | WK-04 | Organisational Betrayal | Gen X · work | Thin | 10 min | 1,100–1,300 | Work betrayal |
| 8 | C | WK-05 | Purpose at Work | Gen X · work | Thin | 12 min | 1,320–1,560 | Abstract work theme |
| 9 | C | PH-03 | Fatigue / Burnout | Boomer · physical | Thin | 12 min | 1,320–1,560 | Body fatigue |
| 10 | D | FR | Friendship overlays | Gen Z · friendship | Sparse | 8 min | 880–1,040 | Loneliness / friendship loss |

Gate after Batch A+B (first 5): stop if voice/mix/length wrong before spending C+D credits.

QA length bands (±10%):
- WK-06: 9–11 min | BO-04: 5.4–6.6 | GX-01: 4.5–5.5 | GZ-04: 2.7–3.3 | ML-03: 4.5–5.5
- PH-01: 13.5–16.5 | WK-04: 9–11 | WK-05: 10.8–13.2 | PH-03: 10.8–13.2 | FR: 7.2–8.8

Note on speech vs wall-clock: Agent 1 writes SPOKEN words only; silence holds are added later. Word ranges above are speech budgets — do not treat them as “fill every second with talk.”

════════════════════════════════════════════════════════════════
4) CURRENT SYSTEM REALITY (so your pack is engineer-ready)
════════════════════════════════════════════════════════════════
Internal API fields for compose:
- content_type: guided_meditation
- generation_code: gen_z | millennial | gen_x | boomer
- wound_id: lowercase slug (gz_04, gx_01, …)
- stage_no: int
- target_duration_minutes: int
- pillar_code: p01… (optional but we want it required in pack)
- principles: string list (often empty today — YOU must fill)
- title_hint: human title string

Known failure mode we already hit:
- Title “WK-04 Organisational Betrayal” / “WK-05 Purpose at Work” produced scripts with ZERO work language when only wound_id=gx_04/gx_03 was passed.
- Fixing that requires brief packs + situational frames + validators — which is what you are writing.

For overlays not in index, propose:
- preferred NEW wound_id (wk_04, wk_05, wk_06, ph_01, ph_03, fr_01 — or better slug)
- AND a temporary core proxy (which existing gx/bo/gz/ml to use until index is extended)

════════════════════════════════════════════════════════════════
5) YOUR DELIVERABLES (ALL required)
════════════════════════════════════════════════════════════════

## SECTION A — Taxonomy decisions (all 10 codes)
For each First-10 code output:
- product_code
- display_name
- generation_code
- wound_id_preferred (new overlay slug OR existing core)
- wound_id_fallback_proxy (existing core only; required for overlays)
- pillar_code (MUST be intentional — do NOT default all to p04)
- stage_no
- target_duration_minutes
- spoken_word_range
- principles (2–4, as “P4 Self-Compassion”)
- title_hint_canonical (exact title string for Agent 1)
- content_type: guided_meditation
- batch: A|B|C|D
- rationale (why this pillar + wound + gen pairing)

Quality bar: WK-04 and WK-05 must NOT share the same wound_id_preferred OR the same mind_heart turn.

## SECTION B — Relatability brief pack (ONE per code × 10)
For EACH code include ALL of:

1) listener_portrait (4–6 lines)
2) wound_story (body/mind feel + 2–3 inner monologue lines + somatic tells + life context)
3) pillar_feel (how pillar colors the whole session)
4) situational_frame
   - required life domain
   - must_use_phrases: 8–15 short spoken phrases (natural language)
5) must_not_say (codes, diagnosing, lecture, hustle advice, medical claims, other wounds)
6) opening_job (3–5 bullets)
7) arc_by_section for opening / settling / body / breath / mind_heart / closing (2–4 bullets each)
8) mind_heart_core (unique emotional turn for THIS wound — 1 short paragraph)
9) closing_promise (1–2 lines)
10) relatability_tests (5 yes/no checks; include at least one “would this also pass as CODE-X? → FAIL”)
11) gold_opening_example (60–90 words, invite-register)
12) anti_generic_traps (3 LLM failure modes + how to avoid)

A stranger reading only WK-04’s brief must distinguish it from WK-05 and GX-01 without seeing codes.

## SECTION C — Overlay wound specs (for pattern index)
For each NEW overlay wound_id:
- wound_id, display_label
- generation_codes_allowed[]
- stage_numbers_allowed[]
- recommended_pillars[]
- high_scoring_pattern_families[] (from assembly list)
- example_mood_lines[3]
- closest_core_wound + why (fallback only)
- contrast_wounds[] (what it must NOT collapse into)

## SECTION D — Pillar language kits (p01–p06 at minimum; include p07/p12 if useful)
For each pillar:
- 10 invite-register phrases that sound like that pillar
- 5 phrases that violate it
- how it should interact with work / physical-pain / friendship frames
- “if script only sounds like generic calm, which pillar cues are missing?”

## SECTION E — Generation register kits
For gen_z, millennial, gen_x, boomer:
- do’s / don’ts
- 5 relatability markers unique to that gen
- what “trying too hard” sounds like
- what “too Boomer/GenZ mismatched” sounds like for cross-checks

## SECTION F — Validator seeds (machine-usable)
For each of the 10 codes:
```json
{
  "product_code": "WK-04",
  "required_keyword_groups": [["work","job","workplace"], ["betray","trust","unfair"]],
  "forbidden_patterns": ["WK-04", "gx_04", "P04", "you must", "diagnose"],
  "min_opening_theme_hits": 1,
  "fail_if_better_matches": ["WK-05", "GX-01"],
  "pillar_required_keyword_groups": [["..."]],
  "generation_required_keyword_groups": [["..."]]
}
```
Rules:
- Keywords = natural spoken words
- required_keyword_groups = OR within group, AND across groups
- Include pillar + generation groups (can be softer / smaller)
- fail_if_better_matches prevents wound collapse

## SECTION G — Agent 2 preserve rules
- must_preserve[]
- may_rewrite_for_tts[]
- 5 washed-out fail examples (before → after bad enhance)
- checklist Agent 2 must pass before ENHANCED is accepted

## SECTION H — Engineer drop-in JSON
At the end, output ONE fenced JSON block named exactly:

first10_relatability_pack.json

Schema:
{
  "schema_version": "1.0",
  "wave": "first-10-thin-wound",
  "codes": [ { ...Section A fields..., "brief": { ...Section B condensed... }, "validator": { ...Section F... } } ],
  "overlay_wounds": [ ...Section C... ],
  "pillars": { "p01": {...}, ... },
  "generations": { "gen_z": {...}, ... },
  "agent2_preserve": { ...Section G... }
}

JSON must be valid. No comments inside JSON.

════════════════════════════════════════════════════════════════
6) OUTPUT RULES
════════════════════════════════════════════════════════════════
- Markdown for human sections A–G, then the JSON block.
- Be specific, concrete, ear-first. No filler strategy essays.
- Do not write full meditation scripts (except gold openings).
- Prefer GenMyō invite language in all examples.
- If two pillars could fit, pick one and justify; never leave null.
- Cover ALL 10 First-10 codes with equal depth — no stub entries.
- Differentiate work overlays carefully:
  - WK-06 = obsolescence / being left behind by tech-age at work
  - WK-04 = betrayal by organisation/system/leadership
  - WK-05 = hollow purpose / meaning drought inside the job
- Differentiate physical overlays:
  - PH-01 = living with pain (not “fix the pain” medical)
  - PH-03 = fatigue/burnout exhaustion in the body
  - BO-04 = disconnection from body / living from the neck up
- FR = loneliness / friendship loss for Gen Z — not dating (RL), not ML-04 couple erosion.

Begin now with Section A table, then B for Rank 1→10, then C–H.
```

---

After Claude returns it, send me especially `first10_relatability_pack.json` plus any Section A/B you’re unsure about — I’ll wire it into Agent 1 + validators.
