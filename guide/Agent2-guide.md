
## Clean and structure the transcript before TTS

Raw transcription (from meetings, podcasts, or even generated scripts) should **not** be sent directly to ElevenLabs; do a “writer’s pass” first. You already designed this as a two‑agent pipeline: Agent 1 (Pattern Transcript Composer) creates the base meditation script from your pattern library, and Agent 2 (ElevenLabs Script Doctor) rewrites it into TTS‑ready narration with clean structure and chunking.[^5][^6][^7][^8]

For the Script Doctor pass, apply these rules:

- Remove fillers and disfluencies (“um”, “you know”, half‑sentences, self‑corrections).
- Fix grammar and spelling, especially names, mantras, and non‑English words.
- Use **short to medium sentences** (often 5–15 words) with clear punctuation; avoid huge compound sentences.[^7][^8]
- Insert paragraph breaks / blank lines where silence should land. **Hard rule for meditation:** each beat is at most **1–3 sentences** (prefer one). Never leave 4+ sentences in one continuous block — the TTS plane inserts a pause between beats.
- One instruction per sentence: “Notice your breath.” then a new beat — not three actions in one paragraph.

This gives ElevenLabs clear prosody signals and reduces the chance of odd timing or emphasis.[^8][^7]

***

## Chunking and feeding text to ElevenLabs

Even though some models allow large character limits (e.g., 10,000 for Multilingual v2, more for Flash), ElevenLabs recommends splitting long text into **segments** rather than sending a 20‑minute script in one go. For long meditations, chunk by **logical sections** (e.g., intro, body scan, breathing, visualization, closing) or by 3–5 sentences at a time, and keep individual chunks relatively short to maintain control and allow easy re‑generation if needed.[^2][^1]

Use **request stitching / previous_text / next_text** so the model understands what came before and what’s coming after, reducing abrupt changes in rhythm or tone between chunks. The official guide shows conditioning each chunk on the concatenated text of previous paragraphs and/or upcoming ones via `previous_text` and `next_text`, then concatenating the audio segments with something like Pydub on your side. This is exactly the pattern your pipeline can adopt: send a chunk, include previous_text/next_text, store the audio, then stitch segments for a seamless 10–20 minute meditation.[^1][^2]

***

## Script formatting for ElevenLabs

Use **punctuation as your main prosody control**:

- Periods for full stops and longer pauses.
- Commas for micro‑pauses within a thought.
- Line breaks between “beats” of the meditation (e.g., changing focus from breath to body).

ElevenLabs explicitly notes that emotional delivery comes from **textual cues and formatting**, and that descriptive text like “she said excitedly” will be spoken unless removed later. So for meditation, don’t write literal stage directions like “(pause 4 seconds)” or “she whispers calmly” in the text unless you plan to trim them out in post; instead, rely on punctuation, line breaks, and, for Eleven v3, audio tags like `[whispers]`, `[laughs]`, `[angry]` that are interpreted as performance markers.[^3][^1]

A safe default formatting style:

- Keep each “sentence group” on its own line.
- Avoid more than 2 clauses per sentence.
- Use ellipses sparingly for softer trailing off (“…”) rather than constant use (which can sound unnatural).

***

## Meditation‑specific scripting techniques

Here are concrete scripting techniques for mindfulness audio that tend to work well with TTS voices:

1. **Second‑person, present tense**
    - “You are lying down comfortably.”
    - “You notice the breath moving in and out.”
This feels more immediate and guides the listener without heavy cognition.
2. **Body‑based, sensory cues**
    - Describe physical sensations (“weight of your body”, “softness under your back”) and simple visuals (“a warm light at your chest”) rather than abstract philosophy.
    - This type of language maps well to neutral, calm delivery in Multilingual v2/v3.
3. **Gentle repetition and refrains**
    - Repeat key lines or mantras throughout the script (e.g., “It’s okay to relax here.”) at spaced intervals.
    - Synthetic voices handle repeated phrases well and repetition reinforces the meditative state.
4. **Slow progression, low instruction density**
    - One instruction per sentence: “Notice your breath.” → “Let your shoulders soften.” → “Feel your jaw relax.”
    - Avoid stacking 3–4 actions in one line; TTS will sound rushed and the listener will feel overloaded.
5. **Soft suggestion, not command**
    - Prefer “You might notice…” or “Allow your attention to settle…” over “You must focus…”
    - This reduces harshness in tone and avoids the voice sounding strict or clinical.

These are perfect responsibilities for your “Script Doctor” agent: rewriting pattern‑generated text into this gentle, instruction‑light, sensory style before feeding to ElevenLabs.[^6][^5]

***

## Using ElevenLabs settings for realism

Within ElevenLabs, tune model settings to match meditation use:

- **Stability**: higher for predictability, slightly lower if you want tiny natural variation; for meditation, bias toward stability/robustness.[^4][^1]
- **Similarity** (or equivalent voice‑consistency setting): keep moderate to high so the voice doesn’t drift across a 20‑minute track.[^1]
- Use a **seed** if you want reproducible output across re‑generations; this helps keep tone consistent when regenerating problematic chunks.[^1]

For expressive v3 use (if you experiment there), follow Eleven’s guidance:

- Use **longer prompts** (>250 characters) for better consistency.
- Choose voices from the “best voices for v3” category.
- Match tags to the voice’s character (don’t put extreme `[angry]` tags on a super‑calm voice).[^3]

For meditation, you’ll probably use v3 tags lightly (e.g., occasional `[whispers]` or softer emotional shading), but keep the core script simple and calm.

***

## Practical script template you can standardize

Below is a simple structure you can bake into Agent 1 (pattern composer) and Agent 2 (Script Doctor) so every transcript is “ElevenLabs‑ready” by design:

### 1. Opening (brief welcome only)

- 3–6 short lines: welcome + intention + invite to begin.
- Keep this short — do **not** start the body scan, long breath work, or deep teaching here.
- Example:
> “Welcome to this moment of quiet.
> You are here to rest, to notice, to simply be.
> When you’re ready, we’ll begin.”

Then leave a clear beat before settling / main practice.


### 2. Body positioning (start of main practice)

- 3–4 lines: posture, comfort.
- Example:
> “Let your body find a comfortable position.
> If your eyes are open, allow them to soften, or gently close.
> Feel the support beneath you.”


### 3. Breathing focus

- 4–6 lines: breath awareness.
- Example:
> “Bring attention to your breath.
> Notice each inhale… and each exhale.
> There is nothing to change.
> Just noticing, gently.”


### 4. Main practice (scan or visualization)

- 8–15 lines: stepwise, one area or image per sentence.
- Example (body scan excerpt):
> “Let your awareness move to your feet.
> Notice any sensation there.
> Then your ankles… your calves… your knees.”


### 5. Closing

- 3–5 lines: integration + return.
- Example:
> “Now, deepen your breath.
> Feel the space around you.
> When you’re ready, gently open your eyes.
> Carry this sense of ease into the rest of your day.”