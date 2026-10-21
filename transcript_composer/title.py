"""Title generation for composed transcripts."""

from __future__ import annotations

from models.requests import CreateTranscriptRequest

WOUND_DISPLAY: dict[str, str] = {
    "gz_01": "identity diffusion",
    "gz_02": "belonging without roots",
    "gz_03": "anticipatory dread",
    "gz_04": "validation dependency",
    "ml_01": "arrival fallacy",
    "ml_02": "chronic overextension",
    "ml_03": "authentic self suppression",
    "ml_04": "relational erosion",
    "gx_01": "invisible sacrifice",
    "gx_02": "emotional self-reliance",
    "gx_03": "purpose displacement",
    "gx_04": "cynicism as shield",
    "bo_01": "legacy uncertainty",
    "bo_02": "grief unprocessed",
    "bo_03": "identity after role",
    "bo_04": "disconnection from body",
}

GENERATION_DISPLAY: dict[str, str] = {
    "gen_z": "Gen Z",
    "millennial": "Millennial",
    "gen_x": "Gen X",
    "boomer": "Boomer",
    "all_generations": "Cross-generational",
}


def build_title(request: CreateTranscriptRequest) -> str:
    """Prefer title_hint; otherwise derive a concise title from taxonomy."""
    if request.title_hint and request.title_hint.strip():
        return request.title_hint.strip()[:512]

    return build_title_from_taxonomy(
        request.generation_code,
        request.wound_id,
        request.stage_no,
    )


def build_title_from_taxonomy(
    generation_code: str | None,
    wound_id: str | None,
    stage_no: int | None,
) -> str:
    """Derive a dashboard-friendly title when none was stored on the version."""
    wound_label = WOUND_DISPLAY.get(
        (wound_id or "").lower(),
        (wound_id or "meditation").replace("_", " "),
    )
    generation_label = GENERATION_DISPLAY.get(
        (generation_code or "").lower(),
        (generation_code or "guided").replace("_", " "),
    )
    stage = stage_no if stage_no is not None else 1
    return f"{generation_label} meditation — {wound_label} (stage {stage})"[:512]
