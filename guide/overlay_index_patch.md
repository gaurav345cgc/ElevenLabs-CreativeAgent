# Overlay Wound Gap-Fill — `meditation_patterns_index.md` patch

Sections A → G. Paste-ready markdown in A–C, JSON in D (also shipped as `overlay_selector_boost_map.json`).

---

## SECTION A — Taxonomy patch

### A.1 Replace/extend `### Wounds per Generation` in the index header

Append this block directly after the existing 16-row table:

```markdown
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
```

### A.2 New wound_id slugs

| Index label | Slug | Pack `product_code` |
|---|---|---|
| WK-04 | `wk_04` | WK-04 |
| WK-05 | `wk_05` | WK-05 |
| WK-06 | `wk_06` | WK-06 |
| PH-01 | `ph_01` | PH-01 |
| PH-03 | `ph_03` | PH-03 |
| FR-01 | `fr_01` | FR |

The pack uses `FR` as the product code. The index uses `FR-01` so it matches the `XX-NN` grammar the parser already handles. Section E asks the normaliser to accept both.

### A.3 Old proxies become optional fallbacks only

| Overlay | Deprecated proxy | Status after patch |
|---|---|---|
| WK-04 | `gx_04` Cynicism as Shield | Fallback only if `wk_04` has zero index rows |
| WK-05 | `gx_03` Purpose Displacement | Fallback only if `wk_05` has zero index rows |
| WK-06 | `gx_02` Emotional Self-Reliance | Fallback only if `wk_06` has zero index rows |
| PH-01 | `bo_04` Disconnection from Body | Fallback only if `ph_01` has zero index rows |
| PH-03 | `bo_04` Disconnection from Body | Fallback only if `ph_03` has zero index rows |
| FR-01 | `gz_02` Belonging Without Roots | Fallback only if `fr_01` has zero index rows |

---

## SECTION B — Applicable-to row patches

Append rows to the **Applicable to:** table of each named existing variant. Nothing else in those variants changes. Every row uses the product's own primary pillar, in-range generations and stages, overlay-specific mood states, and allowed principles only. The sole exception is the WK-05 `opening_intro_spaciousness` row, which carries a P05 Cognitive Clarity secondary pillar on purpose.

Coverage per overlay (existing variants plus Section C):

| Overlay | opening | settling | body | breath | mind_heart | closing |
|---|---|---|---|---|---|---|
| WK-04 | `guided_meditation_intro` | `softening_settling_awareness` | `somatic_scan_awareness` | `breath_attention` | `mind_reframing_kindness` | `closing_transition` |
| WK-05 | `opening_intro_spaciousness` | `softening_settling_awareness` | `somatic_scan_exploration` | `breath_spaciousness` | NEW `mind_reframing_open_question` | `closing_transition` |
| WK-06 | `guided_meditation_intro` | `grounding_settling_posture` | `somatic_scan` | `breath_attention` | NEW `mind_reframing_distinction` | `closing_transition` |
| PH-01 | `guided_meditation_intro` | `grounding_settling_posture` | `somatic_scan_awareness` | `breath_attention` | `mind_reframing_kindness` | `closing_transition` |
| PH-03 | `guided_meditation_intro` | `grounding_settling_posture` + `softening_settling_awareness` | `somatic_scan` | `breath_attention` | NEW `affirmation_rest_permission` | `closing_transition` |
| FR-01 | `guided_meditation_intro` | `grounding_settling_sitbones` | `self_love_somatic_scan` | `breath_spaciousness` | `mind_reframing_kindness` | `closing_transition` |

Variant fit notes:
- **WK-04 on `somatic_scan_awareness`:** the variant says Stage 3+, but its other use is emotional suppression. Anger held in the chest and jaw fits, so the row runs 2–4.
- **FR-01 on `breath_spaciousness`:** this variant is also tagged to GZ-02. The FR-01 mood names one absent friend, so it stays distinct. QA test 7 guards against collapse.
- **WK-06 vs WK-05:** WK-06 never uses oneness or open-question variants. WK-05 never uses the posture variant or the distinction variant.

### Family: `opening_intro`

#### `guided_meditation_intro` — append these rows to **Applicable to:**

| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Gen X / Millennial | Organisational Betrayal | WK-04 | 2–4 | Stabilisation → Pattern Recognition | Seeker / Practitioner | P02 Emotional Regulation | P7 Emotional Intelligence · P4 Self-Compassion · P11 Integrity | anger and grief at a named workplace, "I gave them everything" |
| Gen X / Boomer | Age / Tech Obsolescence | WK-06 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P05 Cognitive Clarity | P1 Authenticity · P4 Self-Compassion · P10 Meaning-Making | tools keep changing, dreading the next system rollout, still useful |
| Boomer / Gen X | Chronic Pain | PH-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P03 Somatic Healing | P4 Self-Compassion · P6 Presence · P3 Resilience | body as the enemy, pain that is not leaving, people stopped asking |
| Boomer / Gen X / Millennial | Fatigue / Burnout | PH-03 | 2 | Stabilisation | Seeker | P04 Deep Rest & Sleep | P4 Self-Compassion · P6 Presence · P3 Resilience | tired as the default, "I'm fine" cover, sleep no longer restores |
| Gen Z / Millennial | Friendship Loss | FR-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P06 Relational Wellbeing | P5 Belonging · P7 Emotional Intelligence · P4 Self-Compassion | a friendship that faded, hollow ache at a reminder, "when did it end" |

#### `opening_intro_spaciousness` — append these rows to **Applicable to:**

| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Gen X / Millennial | Purpose at Work | WK-05 | 3–5 | Reflection → Re-Alignment | Practitioner | P07 Spiritual Inquiry · P05 Cognitive Clarity | P10 Meaning-Making · P2 Purpose · P1 Authenticity | steady job, no hate, no why; flat after the milestone |

### Family: `settling_grounding`

#### `grounding_settling_posture` — append these rows to **Applicable to:**

| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Gen X / Boomer | Age / Tech Obsolescence | WK-06 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P05 Cognitive Clarity | P1 Authenticity · P4 Self-Compassion · P10 Meaning-Making | shoulders braced for the next demo, tired of performing competence |
| Boomer / Gen X | Chronic Pain | PH-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P03 Somatic Healing | P4 Self-Compassion · P6 Presence · P3 Resilience | a position the pain does not have to organise, vigilance easing |
| Boomer / Gen X / Millennial | Fatigue / Burnout | PH-03 | 2 | Stabilisation | Seeker | P04 Deep Rest & Sleep | P4 Self-Compassion · P6 Presence · P3 Resilience | nowhere to be, permission to stop fully, heavy limbs |

#### `softening_settling_awareness` — append these rows to **Applicable to:**

| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Gen X / Millennial | Organisational Betrayal | WK-04 | 2–4 | Stabilisation → Pattern Recognition | Seeker / Practitioner | P02 Emotional Regulation | P7 Emotional Intelligence · P11 Integrity · P3 Resilience | jaw and chest still armoured after the meeting, heat held as protection |
| Gen X / Millennial | Purpose at Work | WK-05 | 3–5 | Reflection → Re-Alignment | Practitioner | P07 Spiritual Inquiry | P10 Meaning-Making · P2 Purpose · P1 Authenticity | flat weekday body, unhurried, no answer needed yet |
| Boomer / Gen X / Millennial | Fatigue / Burnout | PH-03 | 2 | Stabilisation | Seeker | P04 Deep Rest & Sleep | P4 Self-Compassion · P6 Presence · P3 Resilience | early exhale, tired all the way down, body led not pushed |

#### `grounding_settling_sitbones` — append these rows to **Applicable to:**

| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Gen Z / Millennial | Friendship Loss | FR-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P06 Relational Wellbeing | P5 Belonging · P7 Emotional Intelligence · P4 Self-Compassion | held by the chair, supported, the ache of one absent friend |

### Family: `somatic_scan`

#### `somatic_scan` — append these rows to **Applicable to:**

| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Gen X / Boomer | Age / Tech Obsolescence | WK-06 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P05 Cognitive Clarity | P1 Authenticity · P4 Self-Compassion · P10 Meaning-Making | chest tight in the rollout meeting, jaw, hands that know the work |
| Boomer / Gen X / Millennial | Fatigue / Burnout | PH-03 | 2 | Stabilisation | Seeker | P04 Deep Rest & Sleep | P4 Self-Compassion · P6 Presence · P3 Resilience | heavy eyelids, leaden limbs, tired top to bottom |

#### `somatic_scan_awareness` — append these rows to **Applicable to:**

| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Gen X / Millennial | Organisational Betrayal | WK-04 | 2–4 | Stabilisation → Pattern Recognition | Seeker / Practitioner | P02 Emotional Regulation | P7 Emotional Intelligence · P11 Integrity · P3 Resilience | heat in chest and jaw, colder grief underneath, nothing to fix |
| Boomer / Gen X | Chronic Pain | PH-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P03 Somatic Healing | P4 Self-Compassion · P6 Presence · P3 Resilience | named places that hurt, noticed not fought, vigilance fatigue |

#### `somatic_scan_exploration` — append these rows to **Applicable to:**

| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Gen X / Millennial | Purpose at Work | WK-05 | 3–5 | Reflection → Re-Alignment | Practitioner | P07 Spiritual Inquiry | P10 Meaning-Making · P2 Purpose · P1 Authenticity | curious about the flatness, exploring what is here without needing a why |

#### `self_love_somatic_scan` — append these rows to **Applicable to:**

| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Gen Z / Millennial | Friendship Loss | FR-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P06 Relational Wellbeing | P5 Belonging · P7 Emotional Intelligence · P4 Self-Compassion | heart-space ache at a reminder of one friend, hand on the chest |

### Family: `breath_attention`

#### `breath_attention` — append these rows to **Applicable to:**

| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Gen X / Millennial | Organisational Betrayal | WK-04 | 2–4 | Stabilisation → Pattern Recognition | Seeker / Practitioner | P02 Emotional Regulation | P7 Emotional Intelligence · P11 Integrity · P3 Resilience | anger riding the breath, let it be here without feeding it |
| Gen X / Boomer | Age / Tech Obsolescence | WK-06 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P05 Cognitive Clarity | P1 Authenticity · P4 Self-Compassion · P10 Meaning-Making | steady breath under the rollout-meeting tightness |
| Boomer / Gen X | Chronic Pain | PH-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P03 Somatic Healing | P4 Self-Compassion · P6 Presence · P3 Resilience | breath beside the pain, not against it |
| Boomer / Gen X / Millennial | Fatigue / Burnout | PH-03 | 2 | Stabilisation | Seeker | P04 Deep Rest & Sleep | P4 Self-Compassion · P6 Presence · P3 Resilience | an early exhale, nothing to earn |

#### `breath_spaciousness` — append these rows to **Applicable to:**

| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Gen X / Millennial | Purpose at Work | WK-05 | 3–5 | Reflection → Re-Alignment | Practitioner | P07 Spiritual Inquiry | P10 Meaning-Making · P2 Purpose · P1 Authenticity | room around the question, breath wider than the workday |
| Gen Z / Millennial | Friendship Loss | FR-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P06 Relational Wellbeing | P5 Belonging · P7 Emotional Intelligence · P4 Self-Compassion | breath carrying one absent friend, closeness still within reach |

### Family: `mind_reframing_kindness`

#### `mind_reframing_kindness` — append these rows to **Applicable to:**

| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Gen X / Millennial | Organisational Betrayal | WK-04 | 2–4 | Stabilisation → Pattern Recognition | Seeker / Practitioner | P02 Emotional Regulation | P7 Emotional Intelligence · P11 Integrity · P3 Resilience | legitimate anger and grief side by side, not self-blame |
| Boomer / Gen X | Chronic Pain | PH-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P03 Somatic Healing | P4 Self-Compassion · P6 Presence · P3 Resilience | pain and comfort both present, neither erased, no cure promised |
| Gen Z / Millennial | Friendship Loss | FR-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P06 Relational Wellbeing | P5 Belonging · P7 Emotional Intelligence · P4 Self-Compassion | "is it my fault?" loosening; ache and gratitude both true |

### Family: `closing_transition`

#### `closing_transition` — append these rows to **Applicable to:** (this table has its own 7-column grammar)

| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Closing tone |
|---|---|---|---|---|---|---|
| Gen X / Millennial | Organisational Betrayal | WK-04 | 2–4 | Stabilisation → Pattern Recognition | Seeker / Practitioner | Level and steady; honours the anger as real; no "trust again", no loyalty speech |
| Gen X / Millennial | Purpose at Work | WK-05 | 3–5 | Reflection → Re-Alignment | Practitioner | Quiet and open-ended; leaves the question open; no verdict, no job advice |
| Gen X / Boomer | Age / Tech Obsolescence | WK-06 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | Plain, respectful, unhurried; what you carry is still yours; no upskilling, no pep |
| Boomer / Gen X | Chronic Pain | PH-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | Gentle and companionable; no cure promise, no mind-over-pain |
| Boomer / Gen X / Millennial | Fatigue / Burnout | PH-03 | 2 | Stabilisation | Seeker | Slow and permissive; rest is already yours; nothing to do next; no productivity clause |
| Gen Z / Millennial | Friendship Loss | FR-01 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | Warm and witnessing; the ache honoured; no outreach homework |

---

## SECTION C — New pattern variants

Three new variants. Each sits under an existing family and carries one overlay wound, within the limit of 2 per wound. They also cover the mind_heart slot for WK-05, WK-06 and PH-03.

### Family: `mind_reframing_kindness`  (existing family — new variant)

#### `mind_reframing_distinction`
- **Placement:** middle
- **Canonical pattern:** name the fused pair → separate them gently → rest in the difference → let it land in the body
- **Instruction rule:** Offer one clean distinction between two things the listener has fused (a thing that changes, and a person who is changing). Say it as a noticing, not a verdict, and let it land in the body. Do not argue the listener out of the feeling. No advice.
- **Use case:** Use when Cognitive Clarity owns the session and soothing alone would leave the knot untouched.

**Applicable to:**
| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Gen X / Boomer | Age / Tech Obsolescence | WK-06 | 2–3 | Stabilisation / Reflection | Seeker / Practitioner | P05 Cognitive Clarity | P1 Authenticity · P4 Self-Compassion · P10 Meaning-Making | system updating, person not outdated; worth is not a version number |

*Why an existing variant was insufficient:* `mind_reframing_kindness` says "do not resolve"; WK-06 needs one real distinction (system updating vs person outdated) or P05 fails its missing-cue check.

---

### Family: `mind_reframing_oneness`  (existing family — new variant)

#### `mind_reframing_open_question`
- **Placement:** middle
- **Canonical pattern:** name the question → give it room → stay with not-knowing → notice what arrives quietly
- **Instruction rule:** Name the question the listener already carries, then let it stay open. Offer room around it, not an answer. No purpose pep talk and no prescription about the job. Let any sense of meaning arrive quietly, if at all.
- **Use case:** Use for Spiritual Inquiry sessions where the existential why sits inside an ordinary working life.

**Applicable to:**
| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Gen X / Millennial | Purpose at Work | WK-05 | 3–5 | Reflection → Re-Alignment | Practitioner | P07 Spiritual Inquiry | P10 Meaning-Making · P2 Purpose · P1 Authenticity | "is this what it adds up to?", the part still asking why, a search not a failure |

*Why an existing variant was insufficient:* `mind_reframing_oneness` resolves toward connection and unity; no existing variant holds a question open.

---

### Family: `affirmation_release`  (existing family — new variant)

#### `affirmation_rest_permission`
- **Placement:** middle
- **Canonical pattern:** notice tiredness → permit stopping → offer rest as already theirs → release the need to be anywhere
- **Instruction rule:** Offer permission statements from the felt sense of tiredness: nowhere to be, nothing to prove, rest already theirs. Never attach a so-that clause and never frame rest as earned. Keep the release soft and slow.
- **Use case:** Use for exhaustion and burnout when Deep Rest is the pillar. Follows settling or breath work.

**Applicable to:**
| Generation | Wound | Wound ID | Stage | Stage Name | Arc | Pillar | Principles | Mood states |
|---|---|---|---|---|---|---|---|---|
| Boomer / Gen X / Millennial | Fatigue / Burnout | PH-03 | 2 | Stabilisation | Seeker | P04 Deep Rest & Sleep | P4 Self-Compassion · P6 Presence · P3 Resilience | tired all the way down, rest is not something to earn, nothing left to prove |

*Why an existing variant was insufficient:* `affirmation_release` builds on self-worth and "release what no longer serves", which drifts toward earned rest.

---


## SECTION D — Selector boost map (JSON)

```json
{
  "schema_version": "1.0",
  "purpose": "overlay_pattern_index_gap_fill",
  "wounds": {
    "wk_04": {
      "product_code": "WK-04",
      "index_wound_id_label": "WK-04",
      "display_name": "Organisational Betrayal",
      "generation_codes": [
        "gen_x",
        "millennial"
      ],
      "stage_numbers": [
        2,
        3,
        4
      ],
      "primary_pillar": "p02",
      "secondary_pillars": [],
      "proxy_wound_id_deprecated": "gx_04",
      "high_scoring_pattern_families": [
        "opening_intro",
        "settling_grounding",
        "somatic_scan",
        "breath_attention",
        "mind_reframing_kindness",
        "closing_transition"
      ],
      "preferred_variants": [
        "guided_meditation_intro",
        "softening_settling_awareness",
        "somatic_scan_awareness",
        "breath_attention",
        "mind_reframing_kindness",
        "closing_transition"
      ],
      "variants_by_slot": {
        "opening": [
          "guided_meditation_intro"
        ],
        "settling": [
          "softening_settling_awareness"
        ],
        "body": [
          "somatic_scan_awareness"
        ],
        "breath": [
          "breath_attention"
        ],
        "mind_heart": [
          "mind_reframing_kindness"
        ],
        "closing": [
          "closing_transition"
        ]
      },
      "new_variants": [],
      "contrast_wound_ids": [
        "gx_01",
        "wk_06",
        "wk_05"
      ],
      "mood_keywords": [
        "gave them everything",
        "let down",
        "should have seen it coming",
        "anger and grief"
      ]
    },
    "wk_05": {
      "product_code": "WK-05",
      "index_wound_id_label": "WK-05",
      "display_name": "Purpose at Work",
      "generation_codes": [
        "gen_x",
        "millennial"
      ],
      "stage_numbers": [
        3,
        4,
        5
      ],
      "primary_pillar": "p07",
      "secondary_pillars": [
        "p05"
      ],
      "proxy_wound_id_deprecated": "gx_03",
      "high_scoring_pattern_families": [
        "opening_intro",
        "settling_grounding",
        "somatic_scan",
        "breath_attention",
        "mind_reframing_oneness",
        "closing_transition"
      ],
      "preferred_variants": [
        "opening_intro_spaciousness",
        "softening_settling_awareness",
        "somatic_scan_exploration",
        "breath_spaciousness",
        "mind_reframing_open_question",
        "closing_transition"
      ],
      "variants_by_slot": {
        "opening": [
          "opening_intro_spaciousness"
        ],
        "settling": [
          "softening_settling_awareness"
        ],
        "body": [
          "somatic_scan_exploration"
        ],
        "breath": [
          "breath_spaciousness"
        ],
        "mind_heart": [
          "mind_reframing_open_question"
        ],
        "closing": [
          "closing_transition"
        ]
      },
      "new_variants": [
        "mind_reframing_open_question"
      ],
      "contrast_wound_ids": [
        "wk_06",
        "wk_04",
        "ml_01"
      ],
      "mood_keywords": [
        "don't hate this job",
        "missing the why",
        "is this what it adds up to",
        "steady but flat"
      ]
    },
    "wk_06": {
      "product_code": "WK-06",
      "index_wound_id_label": "WK-06",
      "display_name": "Age / Tech Obsolescence",
      "generation_codes": [
        "gen_x",
        "boomer"
      ],
      "stage_numbers": [
        2,
        3
      ],
      "primary_pillar": "p05",
      "secondary_pillars": [],
      "proxy_wound_id_deprecated": "gx_02",
      "high_scoring_pattern_families": [
        "opening_intro",
        "settling_grounding",
        "somatic_scan",
        "breath_attention",
        "mind_reframing_kindness",
        "closing_transition"
      ],
      "preferred_variants": [
        "guided_meditation_intro",
        "grounding_settling_posture",
        "somatic_scan",
        "breath_attention",
        "mind_reframing_distinction",
        "closing_transition"
      ],
      "variants_by_slot": {
        "opening": [
          "guided_meditation_intro"
        ],
        "settling": [
          "grounding_settling_posture"
        ],
        "body": [
          "somatic_scan"
        ],
        "breath": [
          "breath_attention"
        ],
        "mind_heart": [
          "mind_reframing_distinction"
        ],
        "closing": [
          "closing_transition"
        ]
      },
      "new_variants": [
        "mind_reframing_distinction"
      ],
      "contrast_wound_ids": [
        "wk_05",
        "gx_01",
        "bo_03"
      ],
      "mood_keywords": [
        "tools keep changing",
        "left behind",
        "still useful",
        "worth isn't a version number"
      ]
    },
    "ph_01": {
      "product_code": "PH-01",
      "index_wound_id_label": "PH-01",
      "display_name": "Chronic Pain",
      "generation_codes": [
        "boomer",
        "gen_x"
      ],
      "stage_numbers": [
        2,
        3
      ],
      "primary_pillar": "p03",
      "secondary_pillars": [],
      "proxy_wound_id_deprecated": "bo_04",
      "high_scoring_pattern_families": [
        "opening_intro",
        "settling_grounding",
        "somatic_scan",
        "breath_attention",
        "mind_reframing_kindness",
        "closing_transition"
      ],
      "preferred_variants": [
        "guided_meditation_intro",
        "grounding_settling_posture",
        "somatic_scan_awareness",
        "breath_attention",
        "mind_reframing_kindness",
        "closing_transition"
      ],
      "variants_by_slot": {
        "opening": [
          "guided_meditation_intro"
        ],
        "settling": [
          "grounding_settling_posture"
        ],
        "body": [
          "somatic_scan_awareness"
        ],
        "breath": [
          "breath_attention"
        ],
        "mind_heart": [
          "mind_reframing_kindness"
        ],
        "closing": [
          "closing_transition"
        ]
      },
      "new_variants": [],
      "contrast_wound_ids": [
        "ph_03",
        "bo_04"
      ],
      "mood_keywords": [
        "not going away",
        "body as the enemy",
        "people stop asking",
        "living alongside the pain"
      ]
    },
    "ph_03": {
      "product_code": "PH-03",
      "index_wound_id_label": "PH-03",
      "display_name": "Fatigue / Burnout",
      "generation_codes": [
        "boomer",
        "gen_x",
        "millennial"
      ],
      "stage_numbers": [
        2
      ],
      "primary_pillar": "p04",
      "secondary_pillars": [],
      "proxy_wound_id_deprecated": "bo_04",
      "high_scoring_pattern_families": [
        "opening_intro",
        "settling_grounding",
        "somatic_scan",
        "breath_attention",
        "affirmation_release",
        "closing_transition"
      ],
      "preferred_variants": [
        "guided_meditation_intro",
        "grounding_settling_posture",
        "softening_settling_awareness",
        "somatic_scan",
        "breath_attention",
        "affirmation_rest_permission",
        "closing_transition"
      ],
      "variants_by_slot": {
        "opening": [
          "guided_meditation_intro"
        ],
        "settling": [
          "grounding_settling_posture",
          "softening_settling_awareness"
        ],
        "body": [
          "somatic_scan"
        ],
        "breath": [
          "breath_attention"
        ],
        "mind_heart": [
          "affirmation_rest_permission"
        ],
        "closing": [
          "closing_transition"
        ]
      },
      "new_variants": [
        "affirmation_rest_permission"
      ],
      "contrast_wound_ids": [
        "ph_01",
        "bo_04",
        "ml_02"
      ],
      "mood_keywords": [
        "tired as the default",
        "I'm fine",
        "sleep doesn't restore",
        "nowhere to be"
      ]
    },
    "fr_01": {
      "product_code": "FR",
      "index_wound_id_label": "FR-01",
      "display_name": "Friendship Loss",
      "generation_codes": [
        "gen_z",
        "millennial"
      ],
      "stage_numbers": [
        2,
        3
      ],
      "primary_pillar": "p06",
      "secondary_pillars": [],
      "proxy_wound_id_deprecated": "gz_02",
      "high_scoring_pattern_families": [
        "opening_intro",
        "settling_grounding",
        "somatic_scan",
        "breath_attention",
        "mind_reframing_kindness",
        "closing_transition"
      ],
      "preferred_variants": [
        "guided_meditation_intro",
        "grounding_settling_sitbones",
        "self_love_somatic_scan",
        "breath_spaciousness",
        "mind_reframing_kindness",
        "closing_transition"
      ],
      "variants_by_slot": {
        "opening": [
          "guided_meditation_intro"
        ],
        "settling": [
          "grounding_settling_sitbones"
        ],
        "body": [
          "self_love_somatic_scan"
        ],
        "breath": [
          "breath_spaciousness"
        ],
        "mind_heart": [
          "mind_reframing_kindness"
        ],
        "closing": [
          "closing_transition"
        ]
      },
      "new_variants": [],
      "contrast_wound_ids": [
        "gz_02",
        "ml_04"
      ],
      "mood_keywords": [
        "used to talk every day",
        "when did it end",
        "drifted",
        "is it my fault"
      ]
    }
  }
}
```

`variants_by_slot` and `preferred_variants` mirror Sections B and C. `secondary_pillars` for `wk_05` is `["p05"]`, and only its opening row carries it.

---

## SECTION E — Parser / taxonomy engineering notes

1. **`taxonomy.normalize_wound_id` / `expand_wound_ids`**
   - Accept `WK-04`, `WK-05`, `WK-06`, `PH-01`, `PH-03`, `FR-01`, and bare `FR`, mapping to `wk_04 … fr_01`. Suggested pattern: `^(GZ|ML|GX|BO|WK|PH|FR)-?(\d{2})?$`, with bare `FR` defaulting to `fr_01`.
   - Existing range handling (`GZ-01–04`) must be untouched. Overlay rows are single IDs.
2. **Generation cell splitting.** Overlay rows write multi-generation cells as `Gen X / Millennial`, `Boomer / Gen X / Millennial` and so on. If the parser only handles one label per cell, split on ` / ` and map each part to `gen_x`, `millennial`, `boomer` or `gen_z`. Without this, rows still score +8 on wound ID but lose the +4 generation bonus.
3. **Stage cells.** Overlay rows use `2–4`, `3–5`, `2–3`, `2` with the existing en dash and `→` / `/` stage names. No new grammar.
4. **`models.validation` wound-stage rules.** Add:

| wound_id | generations | stages |
|---|---|---|
| `wk_04` | gen_x, millennial | 2, 3, 4 |
| `wk_05` | gen_x, millennial | 3, 4, 5 |
| `wk_06` | gen_x, boomer | 2, 3 |
| `ph_01` | boomer, gen_x | 2, 3 |
| `ph_03` | boomer, gen_x, millennial | 2 |
| `fr_01` | gen_z, millennial | 2, 3 |

5. **`relatability.compose_wound_id_for_entry`.** Replace "if `wound_id_fallback_proxy` is set, always use it" with: use `wound_id_preferred` when the loaded index contains at least one row for it, otherwise use the proxy and log a warning. Keep the proxy field in the pack as a safety net.
6. **`PatternSelector`.** No logic change. Once rows carry `WK-04` etc., the +8 wound match applies directly. Optional later: read `preferred_variants` from the boost map as a small tie-break (+1 or +2). Not needed for this fix.
7. **Family-to-slot mapping.** The three new variants sit under existing families (`mind_reframing_kindness`, `mind_reframing_oneness`, `affirmation_release`). Confirm that `md_parser` derives `composition_slot` from the family, not from a hard-coded variant list. If it uses a variant allow-list, add the three slugs.
8. **Index header.** The text "P08, P09, P10, P11 are not defined" and "P9 is not defined" stays. No pillar or principle was added.
9. **Pack discrepancy to decide.**
   - The pack lists WK-04 `recommended_pillars` as `[p02, p06]`, WK-05 as `[p05, p07]`, and WK-06 `principles` including P8 Growth Mindset. The index uses p02 (WK-04), p07 with p05 secondary (WK-05), and avoids P8 on WK-06 rows because it invites upskilling drift.
   - If requests ever pass p06 for WK-04, they will score 0 on pillar for these rows.
10. **Examples corpus.** `meditation_patterns_examples.md` has no overlay tone references. `ExampleRetriever` will keep pulling nearby core-wound examples until some are added. Out of scope here.

---

## SECTION F — QA checklist

1. If `wound_id=wk_04`, does every one of the 6 slots have at least one row tagged `WK-04`? **Yes**
2. If `wound_id=wk_05`, is a plan built only from `gx_03`-tagged rows still needed? **No**
3. Do WK-04 and WK-05 share any mood-state text or mind_heart variant? **No** (kindness vs NEW open_question)
4. Does every WK-06 mind_heart row draw a system-vs-person distinction rather than only soothing? **Yes** (`mind_reframing_distinction`)
5. Do PH-01 rows read as pain-specific (named places that hurt, pain/comfort, vigilance fatigue) rather than BO-04 numbness? **Yes**
6. Do PH-01 and PH-03 share any variant in the same slot with the same mood? **No** (PH-01 posture/awareness/kindness vs PH-03 posture+softening/scan/rest-permission)
7. Do FR-01 rows name a specific friendship (absent friend, "when did it end") rather than general belonging-without-roots? **Yes**
8. Does any row use a pillar other than the product's primary, apart from WK-05's single P05 secondary? **No**
9. Does any row use P08–P11 as a pillar, or P9 as a principle? **No**
10. Does any instruction_rule use command verbs (breathe / feel / do / must) or a "rest so that…" clause? **No**
11. Is P04 used for any work overlay? **No** (P04 appears only on PH-03)
12. Does the parser return `gen_x` and `millennial` for a `Gen X / Millennial` cell, and `fr_01` for both `FR` and `FR-01`? **Verify after E.1–E.2**

---

## SECTION G — Diff summary for humans

- **Was missing:** `wk_04`, `wk_05`, `wk_06`, `ph_01`, `ph_03`, `fr_01` had no rows in the index, so selection scored proxy wounds (`gx_04`, `gx_03`, `gx_02`, `bo_04`, `gz_02`) and the pack's `overlay_wounds` hints were never read.
- **Added:** an Overlay Wounds taxonomy table, 37 Applicable-to rows across the 6 families (including closing), and 3 new variants (`mind_reframing_distinction`, `mind_reframing_open_question`, `affirmation_rest_permission`).
- **Coverage:** every overlay has opening, settling, body, breath, mind_heart and closing rows. WK-05 has no mood or mind_heart overlap with WK-04. PH-03 uses the new rest-permission variant instead of self-worth affirmation.
- **Proxies that can be retired** once section E.1–E.5 land: `gx_04` (WK-04), `gx_03` (WK-05), `gx_02` (WK-06), `bo_04` (PH-01, PH-03), `gz_02` (FR-01). Keep them as a logged fallback until QA 12 passes.
