"""Curated meditation-safe background beds from library/ → S3.

Excludes nature FX, bright/cinematic, melody-forward piano, and duplicate
Liborio Conti long-name / (1) copies. Default remains calm_ambient_01.
"""

from __future__ import annotations

# Local filename (under library/) → stable profile code (S3: background/{code}.mp3)
LIBRARY_BED_UPLOADS: dict[str, str] = {
    # Already seeded — re-upload keeps key in sync
    "calm_ambient_01.mp3": "calm_ambient_01",
    # Bilateral set
    "01-Bilateral-Tranquility-Variation-1.mp3": "bilateral_tranquility",
    "04-Bilateral-Stillness.mp3": "bilateral_stillness",
    "05-Bilateral-Eternal.mp3": "bilateral_eternal",
    "06-Transient.mp3": "transient",
    # 432 Hz short titles (canonical; skip long-name + (1) dupes)
    "09-BLESSING.mp3": "blessing",
    "14-BLOSSOM.mp3": "blossom",
    "19-EARTH.mp3": "earth",
    "24-FLOATING.mp3": "floating",
    "39-REPLENISH.mp3": "replenish",
    "44-SANCTUARY.mp3": "sanctuary",
    "49-THE-DEEP.mp3": "the_deep",
    "54-TIMING.mp3": "timing",
    "59-TUNING.mp3": "tuning",
    # Named soft pads
    "AmbientLight.mp3": "ambient_light",
    "Calmness.mp3": "calmness",
    "DeeperMeaning.mp3": "deeper_meaning",
    "Evolving-Pads-Free-Relaxing-Royalty-Free-Music-by-Liborio-Conti-01-Evolving-Pads.mp3": "evolving_pads",
    "ForgottonPlace.mp3": "forgotten_place",
    "Frozen-in-Time.mp3": "frozen_in_time",
    "Forever.mp3": "forever",
    "Just-Relax-No-Copyright-Music-01-Just-Relax.mp3": "just_relax",
    "Light-And-Balanced-No-Copyright-Music-01-Light-And-Balanced.mp3": "light_and_balanced",
    "Peaceful-Sleep-Music-Free-Royalty-Free-Music-by-Liborio-Conti-01-Peaceful-Sleep-Music.mp3": "peaceful_sleep",
    "Pure-Ambient-No-Copyright-Music-01-Pure-Ambient.mp3": "pure_ambient",
    "Reflections-No-Copyright-Music-01-Reflections.mp3": "reflections",
    "TranquilReflections.mp3": "tranquil_reflections",
    "Winter.mp3": "winter",
}

# Intentionally NOT uploaded (nature FX / melody / bright / rhythmic / dupes):
# Beach*, ByTheFire, Nature*, Forestal, SerenityInTheWoods, OnAPiano*,
# Emotional-Piano*, Bright*, Inspiring*, 07-Bright-Ambient, Cinelax, TheCalling,
# Noisescape, Voice-Of-Eden, Spring-Sunrise, Bilateral-Harp, TibetanBowls,
# MOTION, MOVEMENT, Ambient-Meets-Classical*, Relaxing-Music-432-Hz-* duplicates,
# SoftAndFragile, Wonder, Horizon (audition later if needed)
