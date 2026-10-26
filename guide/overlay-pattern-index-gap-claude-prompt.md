# Claude prompt — Fill Agent 1 pattern-index gap (overlay wounds)

Copy everything inside the fence below into Claude. **No attachments needed** — pipeline context, gap analysis, taxonomy, full pillar definitions, First-10 overlay specs, and index markdown format are embedded.

**Goal of Claude’s output:** Produce paste-ready extensions to `transcript_composer/data/meditation_patterns_index.md` (and a companion JSON mapping) so Agent 1’s `PatternSelector` can score **overlay wounds** (`wk_*`, `ph_*`, `fr_*`) as first-class taxonomy — ending the temporary “proxy to gx/bo/gz” workaround.

---

```text
You are a GenMyō senior content architect + pattern-index engineer.

Your job: FILL A STRUCTURAL KNOWLEDGE GAP in our Creative Agent monorepo so Agent 1 (Pattern Transcript Composer) can select meditation patterns using the REAL First-10 overlay wounds — not proxy core wounds.

Do NOT ask for attachments. Everything you need is below.
Do NOT invent pillars P08–P11.
Do NOT invent principle P9.
Do NOT rewrite Agent 2 or TTS.
Do NOT produce full meditation scripts — produce PATTERN INDEX knowledge only (plus a small selector-mapping JSON).

════════════════════════════════════════════════════════════════
0) ULTRA-DETAILED PRODUCT + SYSTEM CONTEXT
════════════════════════════════════════════════════════════════

## 0.1 Brand / product
- Brand: GenMyō — “honour the person.”
- In-house production of guided meditation narration for specific wounds, generations, pillars, and life situations.
- We license content where the library is strong; we PRODUCE where the library is thin/empty — especially work overlays (WK), physical overlays (PH), and friendship overlays (FR).

## 0.2 Creative Agent pipeline (how code actually runs)
```
Brief (tenant, generation, wound_id, stage, pillar, duration, title_hint)
  → Agent 1 Pattern Transcript Composer
       1) PatternSelector.build_pattern_plan  (scores pattern index by wound/stage/gen/pillar)
       2) ExampleRetriever                    (tone refs from examples corpus)
       3) ScriptGenerator                     (6 OpenAI section calls)
       4) TranscriptValidator                 (structure + theme + relatability keywords)
       5) Persist RAW_PATTERN → PENDING_ENHANCEMENT
       6) SQS (IDs only) → Agent 2 Script Doctor → ELEVENLABS_ENHANCED → ENHANCED
  → Script Hub human approve (optional today) → APPROVED_FINAL
  → TTS plane: pause plan → chunk → ElevenLabs → stitch → mix bed → master + manifest
```

Agent 1 six spoken sections (fixed order):
  opening → settling → body → breath → mind_heart → closing

Agent 1 voice rules (non-negotiable for any instruction_rule / use_case you write):
  - Spoken narration only (one tired listener in headphones)
  - Invite register: allow / notice / soften / invite — NOT command (breathe / feel / do / must)
  - Never speak product codes, wound_ids, or pillar codes aloud
  - No lecture, no medical claims, no toxic positivity, no hustle advice
  - Pattern fidelity: follow canonical beats; do not invent a different pattern family

## 0.3 How PatternSelector uses the index (why this gap hurts)
File: transcript_composer/knowledge/pattern_selector.py

For each composition slot, candidates are patterns whose family maps to that slot.
Score:
  - wound_id match:     +8
  - stage_no match:     +6
  - generation match:   +4
  - pillar_code match:  +3  (or +1 if request has no pillar)

Highest score wins. If score is 0, fall back to default pattern for the slot.

Parser: transcript_composer/knowledge/md_parser.py reads
  transcript_composer/data/meditation_patterns_index.md
and extracts per pattern:
  pattern_family, composition_slot, placement, canonical_pattern, instruction_rule,
  use_case, tone_notes, wound_ids[], stage_numbers[], generation_codes[], pillar_codes[]

Wound IDs in tables are normalized to slugs like gz_01, ml_03, gx_04, bo_04.
Generation codes normalize to gen_z, millennial, gen_x, boomer, all_generations.
Pillars normalize to p01…p07, p12.

## 0.4 THE GAP (exact engineering problem you are fixing)

### What exists
1) Core pattern index — 16 core wounds only:
   gz_01–gz_04, ml_01–ml_04, gx_01–gx_04, bo_01–bo_04
2) First-10 relatability pack JSON — already written:
   transcript_composer/data/first10_relatability_pack.json
   Contains briefs, wound_story, pillar_feel, must_use phrases, validator keyword groups,
   AND overlay_wounds metadata with high_scoring_pattern_families.
3) Relatability prompts are injected into Agent 1 section generation when a First-10 code matches.
4) Keyword validators exist for pack entries (when validation mode includes them).

### What is MISSING (this is your deliverable)
Overlay wounds are NOT first-class rows in meditation_patterns_index.md:
  wk_04, wk_05, wk_06, ph_01, ph_03, fr_01

Today Agent 1 does this (relatability.py compose_wound_id_for_entry):
  “If wound_id_fallback_proxy is set, ALWAYS use the proxy for pattern selection.”
  Examples:
    WK-06 preferred wk_06 → selector uses gx_02 (Emotional Self-Reliance)
    WK-04 preferred wk_04 → selector uses gx_04 (Cynicism as Shield)
    WK-05 preferred wk_05 → selector uses gx_03 (Purpose Displacement)
    PH-01 preferred ph_01 → selector uses bo_04 (Disconnection from Body)
    PH-03 preferred ph_03 → selector uses bo_04
    FR   preferred fr_01 → selector uses gz_02 (Belonging Without Roots)

### Failure mode this causes
- Pattern plan is therapeutically “nearby” but wrong (wrong wound tags win the +8).
- Scripts can miss work / pain / friendship scene structure even when title_hint is correct.
- Known historical failure: titles like “WK-04 Organisational Betrayal” / “WK-05 Purpose at Work”
  produced scripts with ZERO work language when only the proxy wound_id drove selection.
- Relatability pack tries to paper over this in PROMPTS, but structural selection still scores the proxy.
- overlay_wounds[].high_scoring_pattern_families is NEVER read by PatternSelector.

### Success condition after your work is wired
When request.wound_id = wk_06 (or title resolves to WK-06), PatternSelector should find
index rows tagged wound_id wk_06 and score them +8 — WITHOUT needing gx_02 proxy.
Same for wk_04, wk_05, ph_01, ph_03, fr_01.

════════════════════════════════════════════════════════════════
1) TAXONOMY REFERENCE (authoritative)
════════════════════════════════════════════════════════════════

### Generations (API / internal)
| Display | generation_code |
|---|---|
| Gen Z | gen_z |
| Millennial | millennial |
| Gen X | gen_x |
| Boomer | boomer |
| Cross-generational | all_generations |

### Core wounds (ALREADY in index — do not duplicate as new wounds; may appear as contrast)
| Gen | Wound | Product | wound_id |
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

### Overlay wounds you MUST add to the index taxonomy + Applicable-to tables
| Product | Display name | wound_id (preferred) | Old proxy (do NOT rely on after your work) | Primary gens | Primary pillar | Typical stage |
|---|---|---|---|---|---|---|
| WK-04 | Organisational Betrayal | wk_04 | gx_04 | gen_x, millennial | p02 | 2–4 |
| WK-05 | Purpose at Work | wk_05 | gx_03 | gen_x, millennial | p07 (also p05 ok as secondary) | 3–5 |
| WK-06 | Age / Tech Obsolescence | wk_06 | gx_02 | gen_x, boomer | p05 | 2–3 |
| PH-01 | Chronic Pain | ph_01 | bo_04 | boomer, gen_x | p03 | 2–3 |
| PH-03 | Fatigue / Burnout | ph_03 | bo_04 | boomer, gen_x, millennial | p04 | 2 |
| FR | Friendship Loss | fr_01 | gz_02 | gen_z, millennial | p06 | 2–3 |

Differentiate carefully (must not collapse):
- WK-04 ≠ WK-05 ≠ WK-06 (betrayal vs hollow purpose vs tech obsolescence)
- PH-01 ≠ PH-03 (chronic pain befriending ≠ permission-to-rest fatigue)
- FR ≠ GZ-02 (specific friendship fade ≠ general belonging without roots)
- Do NOT invent RL dating overlays for this deliverable.

### Stages
| No | Name | Arc |
|---|---|---|
| 1 | Awakening | Seeker |
| 2 | Stabilisation | Seeker |
| 3 | Reflection | Practitioner |
| 4 | Pattern Recognition | Practitioner |
| 5 | Re-Alignment | Practitioner |
| 6 | Inner Growth | Contributor |

### Principles (ONLY these — P9 does not exist)
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

Always write principles as “P4 Self-Compassion”, never bare codes alone in tables.

### Pattern families already in the index (reuse these — prefer tagging overlays onto existing families)
Composition assembly:
| Step | composition_slot | Pattern family |
|---|---|---|
| 1 Open | opening | opening_intro |
| 2 Settle | settling | settling_grounding |
| 3 Body | body | somatic_scan (and related body families in index) |
| 4 Breath | breath | breath_attention |
| 5 Mind/heart | mind_heart | mind_reframing_kindness, mind_reframing_oneness, affirmation_release |
| 6 Close | closing | closing_transition |

Known high-value families already referenced by overlay_wounds in the relatability pack:
  opening_intro, settling_grounding, somatic_scan, breath_attention,
  mind_reframing_kindness, mind_reframing_oneness, affirmation_release, closing_transition

You MAY propose a SMALL number of NEW pattern variants (#### `new_slug`) ONLY when an overlay cannot honestly fit an existing variant’s instruction_rule — max 2 new variants per overlay wound, and they MUST sit under an existing ### Family.

════════════════════════════════════════════════════════════════
2) FULL PILLAR DEFINITIONS (authoritative — use these exactly)
════════════════════════════════════════════════════════════════

ONLY these pillars exist. Do not invent P08, P09, P10, P11 as pillars.
(Note: P10/P11 above are PRINCIPLES, not pillars. Pillar list is P01–P07 and P12 only.)

--------------------------------
P01 / p01 — Mindful Awareness
Category: Body Awareness
Essence: Notice what is actually here without fixing, clearing, or forcing focus.
Invite-register phrases (prefer in instruction_rule / mood when this pillar is primary):
  - “just notice, without changing anything”
  - “see what's actually here”
  - “no need to fix what you find”
  - “curious, not critical”
  - “a quiet noticing”
Violating phrases (never encode these into instruction rules):
  - “you must pay attention”
  - “focus harder”
  - “clear your mind completely”
Missing-cue diagnostic: Absent noticing language directed at something specific.
When this pillar owns a session: the arc should make perception itself the medicine — not advice, not catharsis-first, not productivity.

--------------------------------
P02 / p02 — Emotional Regulation
Category: Stress & Recovery
Essence: Name and permit an emotion so it can move through, without suppression or “calm down” control.
Invite-register phrases:
  - “let the feeling move through”
  - “this will settle, in its own time”
  - “you're allowed to feel this fully”
  - “safe to feel, safe to let go”
Violating phrases:
  - “calm down”
  - “don't overreact”
  - “get over it”
Missing-cue diagnostic: Emotion never named/permitted before any settling occurs.
When this pillar owns a session: feelings are legitimate; regulation is capacity, not erasure. Especially for WK-04 anger/grief with a real institutional target — do not turn into self-blame.

--------------------------------
P03 / p03 — Somatic Healing
Category: Body Awareness
Essence: Let the body be heard. Specific body-part / sensation language. No cure theater, no “push through.”
Invite-register phrases:
  - “let the body be heard”
  - “no fixing needed here”
  - “the body has been carrying this”
  - “your body isn't the enemy”
Violating phrases:
  - “correct your posture”
  - “push through the discomfort”
  - “this stretch will fix it”
Missing-cue diagnostic: Only abstract “your body” with no concrete sensation/parts.
When this pillar owns a session (PH-01): befriending a body that hurts — not fighting pain, not promising resolution.

--------------------------------
P04 / p04 — Deep Rest & Sleep
Category: Sleep & Energy
Essence: Rest as permission and end-in-itself — never “rest so you can perform.”
Invite-register phrases:
  - “rest is not something to earn”
  - “permission to stop, fully”
  - “nowhere to be right now”
  - “this rest is already yours”
Violating phrases:
  - “rest so you can be more productive”
  - “you've earned this break”
  - “sleep better to perform better”
Missing-cue diagnostic: Rest framed with a “so that you can…” productivity clause.
When this pillar owns a session (PH-03): chronic tiredness / burnout permission — not sleep-hygiene lecture.

--------------------------------
P05 / p05 — Cognitive Clarity
Category: Values & Purpose
Essence: Untangle noise from signal; draw a real distinction/reframe — not empty reassurance that “clarity will come.”
Invite-register phrases:
  - “let's untangle what's actually true”
  - “separate the noise from the signal”
  - “clarity, not judgment”
  - “the fog lifting, slightly”
Violating phrases:
  - “figure it out already”
  - “stop overthinking”
  - “just be more rational”
Missing-cue diagnostic: No actual reframe/distinction — only soothing fog.
When this pillar owns a session (WK-06): clarity about worth vs version numbers / tools changing — not upskilling advice.

--------------------------------
P06 / p06 — Relational Wellbeing
Category: Relationships & Connection
Essence: Being seen / unseen in relation to others. Fails if purely internal with no relational frame.
Invite-register phrases:
  - “you are not invisible here”
  - “seen, even in this quiet moment”
  - “closeness you're still capable of”
  - “not alone in this feeling”
Violating phrases:
  - “just make more friends”
  - “reach out and fix it”
  - “relationships take work” (as a scolding prescription)
Missing-cue diagnostic: No address of being seen/unseen by another person.
When this pillar owns a session (FR, and GX-01-like sacrifice): witness, not networking tips. For FR: grief-adjacent friendship fade — not “text them now.”

--------------------------------
P07 / p07 — Spiritual Inquiry
Category: Values & Purpose
Essence: Treat the existential “why” as legitimate and leave it open — not a purpose pep talk.
Invite-register phrases:
  - “sitting with the question, not rushing the answer”
  - “meaning that shows up quietly”
  - “the part of you still asking why”
  - “a search, not a failure”
Violating phrases:
  - “here's the meaning of life”
  - “you need to find your purpose now”
  - “stop questioning and just accept it”
Missing-cue diagnostic: Question rushed to resolution or pathologized.
When this pillar owns a session (WK-05): hollow competence / “is this it?” at work — not “quit your job” advice.

--------------------------------
P12 / p12 — Generativity
Category: Values & Purpose
Essence: Connect the listener’s experience to something beyond themselves (passing on, contributing) without legacy panic.
Invite-register phrases:
  - “what you've learned is worth passing on”
  - “your experience still has a place”
  - “contributing without needing credit”
  - “a legacy made of small things”
Violating phrases:
  - “you need to leave a big legacy”
  - “make sure you're remembered”
  - “your time is running out to matter”
Missing-cue diagnostic: Purely self-focused with no beyond-self thread.
When this pillar appears: often secondary for Boomer/legacy-adjacent work; First-10 primary pillars above usually dominate.

════════════════════════════════════════════════════════════════
3) FIRST-10 OVERLAY BRIEFS (compress into index rows — do not ignore)
════════════════════════════════════════════════════════════════

Use these as the semantic source when writing Applicable-to mood states, instruction_rule nuances, and use_case lines. Keep index rows SHORT (index style), but accurate.

### WK-06 — Age / Tech Obsolescence (wk_06) · gen_x/boomer · p05 · stage ~3
Life domain: technology/skills currency at paid work.
Wound feel: chest tightness in meetings where new systems roll out; fear of looking obsolete; judgment still strong but unpraised.
Pillar feel: Cognitive Clarity — untangle “system updated” from “person outdated”; clarity not confidence theater.
Must NOT become: upskilling advice, denial of change, medical aging claims.
Contrast wounds: wk_05, gx_01, bo_03 — scripts that only sound like those FAIL.
Mind/heart turn: difference between a system updating and a person becoming outdated.

### WK-04 — Organisational Betrayal (wk_04) · gen_x/millennial · p02 · stage 2–4
Life domain: workplace trust broken (layoff, broken promise, restructuring hypocrisy).
Wound feel: hot anger + colder grief about naivety; “I gave them everything.”
Pillar feel: Emotional Regulation for legitimate anger/grief with a real institutional target — move through, don’t harden into permanent cynicism; NOT self-blame.
Must NOT become: revenge fantasy, “just trust again,” hustle loyalty speech.
Contrast: gx_01 (invisible sacrifice without betrayal), wk_06, wk_05.

### WK-05 — Purpose at Work (wk_05) · gen_x/millennial · p07 · stage 3–5
Life domain: stable job that doesn’t feel meaningful; “I don’t hate this — I don’t know why I’m doing it.”
Wound feel: flatness after milestones that should feel good.
Pillar feel: Spiritual Inquiry — sit with why; not religious; not “find a new job” prescription.
Must NOT become: arrival-fallacy twin of ml_01 without work scene; productivity purpose-hacking.
Contrast: wk_06, wk_04, ml_01.

### PH-01 — Chronic Pain (ph_01) · boomer/gen_x · p03 · stage 2–3
Life domain: ongoing physical pain / chronic condition.
Wound feel: body as enemy; vigilance fatigue; isolation of invisible pain.
Pillar feel: Somatic Healing without cure narrative — befriend, don’t fight or pretend away.
Must NOT become: medical advice, miracle healing, “mind over pain” denial.
Contrast: ph_03, bo_04 (general numbness ≠ chronic pain story).

### PH-03 — Fatigue / Burnout (ph_03) · boomer/gen_x/millennial · p04 · stage 2
Life domain: long stretch of overextension; tired as default.
Wound feel: sleep doesn’t restore; “I’m fine” cover; short fuse.
Pillar feel: Deep Rest as permission — early exhale; not sleep-hygiene tutorial; not “rest to perform.”
Must NOT become: caffeine jokes as main content, productivity recovery plan.
Contrast: ph_01, bo_04, ml_02.

### FR / fr_01 — Friendship Loss · gen_z/millennial · p06 · stage 2–3
Life domain: friendship fade (move, life-stage split, quiet attrition).
Wound feel: hollow ache at triggers; “when did it end?”; blame loop.
Pillar feel: Relational Wellbeing, grief-adjacent — mourn the fade; reconnect to capacity for connection; do NOT “fix the friendship” with outreach homework.
Must NOT become: generic loneliness with no friendship specificity; dating/RL content.
Contrast: gz_02, ml_04.

════════════════════════════════════════════════════════════════
4) INDEX MARKDOWN FORMAT YOU MUST MATCH EXACTLY
════════════════════════════════════════════════════════════════

The live file is: transcript_composer/data/meditation_patterns_index.md

Existing pattern block shape (copy this grammar precisely):

### Family: `opening_intro`

#### `guided_meditation_intro`
- **Placement:** opening
- **Canonical pattern:** introduce journey → frame purpose → emphasize relaxation → invite presence
- **Instruction rule:** Tell the listener what this session is for. Frame it around their specific wound — name the feeling without diagnosing it. Make it feel like permission.
- **Use case:** Use when the content has a clear therapeutic purpose tied to a wound. This sets the container before the body work begins.

**Applicable to:**
| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Gen X | Invisible Sacrifice | GX-01 | 2 | Stabilisation | Seeker | P04 Deep Rest & Sleep | P4 Self-Compassion · P3 Resilience · P2 Purpose | depleted |

YOUR JOB for overlays:
A) Add a new subsection under ## Content Taxonomy Reference → ### Wounds per Generation
   (or a new ### Overlay wounds table) listing WK/PH/FR with wound_id slugs wk_04 etc.
B) For EACH overlay wound, add **Applicable to** rows onto the best-fitting EXISTING pattern variants
   across all 6 assembly families (opening, settling, body/somatic, breath, mind_heart, closing).
   Minimum coverage per overlay wound:
   - ≥1 opening_intro variant row
   - ≥1 settling_grounding variant row
   - ≥1 body (somatic_scan or equivalent) variant row
   - ≥1 breath_attention variant row
   - ≥1 mind_heart family variant row (kindness OR oneness OR affirmation — choose intentionally)
   - ≥1 closing_transition variant row
C) Optionally add NEW #### variants only when necessary (see limits above).
D) Wound ID column must show BOTH human code and be parseable:
   Prefer table cells like: `WK-06` in Wound ID column IF the parser’s expand_wound_ids supports it,
   OR write slug-friendly form. SAFEST for our parser: put product style `WK-06` AND ensure
   wound name column says the display name. ALSO include the internal slug in a dedicated note
   list for engineers. Our normalize_wound_id typically maps GZ-01 → gz_01; for overlays you must
   output a machine mapping table (Section E) with wound_id slug wk_06 etc. so engineers can
   extend taxonomy.normalize_wound_id / expand_wound_ids if needed.

IMPORTANT: Every Applicable-to row you add must be honest:
  - Generation matches allowed gens for that overlay
  - Stage within allowed stages
  - Pillar MUST be the intentional primary pillar for that product (see table) unless you justify a secondary pillar row explicitly
  - Mood states must be overlay-specific (work scene / pain / friendship) — NOT generic “calm”
  - Principles 2–4 from the allowed principle list

════════════════════════════════════════════════════════════════
5) DELIVERABLES (ALL required — use these exact section headers)
════════════════════════════════════════════════════════════════

## SECTION A — Taxonomy patch (markdown)
1) Updated “Wounds per Generation” / new “Overlay wounds” table for the index header.
2) Explicit list of new wound_id slugs: wk_04, wk_05, wk_06, ph_01, ph_03, fr_01.
3) Note which old proxies become OPTIONAL fallbacks only (not required for selection).

## SECTION B — Applicable-to row patches (markdown)
For each overlay wound, output ready-to-paste markdown tables rows grouped by:
  Family → existing #### pattern variant → new Applicable-to rows.

Cover all 6 slots per overlay (minimum rows as specified in §4).

## SECTION C — New pattern variants (markdown) [only if needed]
If you create new #### blocks:
  - Full Placement / Canonical pattern / Instruction rule / Use case
  - Applicable-to table including the overlay rows
  - Explain in one line why an existing variant was insufficient

## SECTION D — Selector boost map (JSON)
Produce JSON the engineers can later wire into PatternSelector / relatability overlay_wounds:

```json
{
  "schema_version": "1.0",
  "purpose": "overlay_pattern_index_gap_fill",
  "wounds": {
    "wk_06": {
      "product_code": "WK-06",
      "display_name": "Age / Tech Obsolescence",
      "generation_codes": ["gen_x", "boomer"],
      "stage_numbers": [2, 3],
      "primary_pillar": "p05",
      "secondary_pillars": [],
      "proxy_wound_id_deprecated": "gx_02",
      "high_scoring_pattern_families": ["opening_intro", "somatic_scan", "mind_reframing_kindness", "closing_transition"],
      "preferred_variants": ["guided_meditation_intro", "..."],
      "contrast_wound_ids": ["wk_05", "gx_01", "bo_03"],
      "mood_keywords": ["tools keep changing", "left behind", "still useful"]
    }
  }
}
```

Include ALL six overlay wound_ids.

## SECTION E — Parser / taxonomy engineering notes
Tell engineers exactly what code may need updates:
- taxonomy.normalize_wound_id / expand_wound_ids must accept WK-06 → wk_06, PH-01 → ph_01, FR → fr_01
- models.validation wound-stage rules must include new wound_ids + allowed stages
- relatability.compose_wound_id_for_entry should stop forcing proxy once preferred wound exists in index
- PatternSelector needs no logic change IF wound_ids appear on pattern rows (preferred)

## SECTION F — QA checklist (yes/no tests)
Write 12 tests like:
- “If wound_id=wk_04, does opening_intro have ≥1 Applicable-to row with WK-04/wk_04?” 
- “Would a wk_05 plan that only uses gx_03-tagged rows without wk_05 tags still be needed? → NO after patch”
- “PH-01 rows must not read like generic BO-04 numbness without pain-specific mood”
- “FR rows must not collapse into GZ-02 belonging-without-roots”
- Pillar fidelity tests per product (p02/p07/p05/p03/p04/p06)

## SECTION G — Diff summary for humans
Bullet list: what was missing → what you added → which proxies can be retired.

════════════════════════════════════════════════════════════════
6) QUALITY BAR / ANTI-PATTERNS
════════════════════════════════════════════════════════════════

FAIL if you:
- Only update the relatability pack (already done) and skip index Applicable-to rows
- Tag every overlay onto every pattern (noise) — be selective and intentional
- Use pillar p04 as a lazy default for work overlays
- Make WK-04 and WK-05 share the same mood / mind_heart implication
- Make PH-01 and PH-03 interchangeable
- Write commanding instruction rules
- Invent pillars P08–P11
- Dump full scripts or must_use phrase essays into the index (keep index terse)
- Leave any overlay without closing + opening coverage

PASS if:
- All 6 overlays are first-class in taxonomy + have 6-slot Applicable-to coverage
- Primary pillars match the product table
- Contrast between overlays is obvious from mood states alone
- JSON boost map is complete and consistent with markdown
- Engineer notes explain how to stop proxying

════════════════════════════════════════════════════════════════
7) OUTPUT ORDER
════════════════════════════════════════════════════════════════
Return sections A → G in order.
Prefer paste-ready markdown for A–C.
Prefer valid JSON for D.
Be exhaustive but non-redundant.
Start now.
```

---

## How to use after Claude returns

1. Paste **Section A–C** carefully into [`transcript_composer/data/meditation_patterns_index.md`](../transcript_composer/data/meditation_patterns_index.md).
2. Extend `taxonomy.normalize_wound_id` / wound–stage rules per **Section E**.
3. Save **Section D** JSON (e.g. `transcript_composer/data/overlay_pattern_boost.json`) and optionally wire into `PatternSelector`.
4. Change `compose_wound_id_for_entry` to prefer `wound_id_preferred` when present in the index (stop always-proxy).
5. Run composition for WK-04/05/06, PH-01/03, FR and confirm selected `pattern_plan` families match **Section D**.

Related: [`relatability-knowledge-claude-prompt.md`](relatability-knowledge-claude-prompt.md) (briefs — already largely done), [`first10_relatability_pack.md`](first10_relatability_pack.md).
