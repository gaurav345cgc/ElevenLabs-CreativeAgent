#!/usr/bin/env python3
"""Validate an Agent 1 transcript against the pattern index and examples corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from models.requests import CreateTranscriptRequest
from models.validation import build_example_pattern_plan
from pipeline_orchestrator.config import OrchestratorSettings
from pipeline_orchestrator.client import CreativeAgentClient
from transcript_composer.composition_service import CompositionService
from transcript_composer.llm_config import ensure_dotenv_loaded
from transcript_composer.script_generator import (
    TemplateScriptGenerator,
    get_default_script_generator,
)
from transcript_composer.validation import TranscriptValidationError, TranscriptValidator


def _settings() -> OrchestratorSettings:
    return OrchestratorSettings.from_env()


def _headers(settings: OrchestratorSettings) -> dict[str, str]:
    return {
        "X-API-Key": settings.api_key,
        "X-Tenant-Id": str(settings.tenant_id),
    }


def _load_raw_version_from_db(
    transcript_id: UUID,
    version_id: UUID,
):
    from db.repositories import TranscriptRepository
    from db.session import build_session_factory, session_scope
    from models.metadata import SectionedScriptContent

    factory = build_session_factory()
    repo = TranscriptRepository(factory)
    with session_scope(factory) as session:
        version = repo.get_transcript_version(session, transcript_id, version_id)
        if not version.content_json:
            return None, None
        return version, SectionedScriptContent.model_validate(version.content_json)


def validate_existing_transcript(
    transcript_id: str,
    *,
    settings: OrchestratorSettings,
    validation_mode: str | None = None,
) -> int:
    client = CreativeAgentClient(settings)
    tid = UUID(transcript_id)
    transcript = client.get_transcript(tid)
    versions = client.list_versions(tid)
    raw = next(
        (v for v in versions.get("versions", []) if v.get("version_kind") == "RAW_PATTERN"),
        None,
    )
    if raw is None:
        print(f"No RAW_PATTERN version found for transcript {transcript_id}")
        return 1

    metadata = raw.get("metadata_json") or raw.get("metadata") or {}
    stored_report = metadata.get("validation_report")
    if stored_report:
        print("Stored validation report (from compose time)")
        print("-" * 50)
        print(json.dumps(stored_report, indent=2))
        print()
        if stored_report.get("passed"):
            print("Result: PASSED (at compose time)")
            return 0
        print("Result: FAILED (at compose time)")
        return 1

    version_id = UUID(str(raw.get("version_id")))
    try:
        db_version, sectioned = _load_raw_version_from_db(tid, version_id)
    except Exception as exc:
        print(f"Could not load RAW_PATTERN from database: {exc}")
        return 1
    if sectioned is None or db_version is None:
        print("Could not load sectioned script (DB content_json missing)")
        return 1

    request = CreateTranscriptRequest(
        tenant_id=settings.tenant_id,
        content_type=transcript.get("content_type", "guided_meditation"),
        generation_code=transcript.get("generation_code", "millennial"),
        wound_id=transcript.get("wound_id", "ml_02"),
        stage_no=int(transcript.get("stage_no", 2)),
        pillar_code=transcript.get("pillar_code"),
        target_duration_minutes=5,
    )
    from models.agents import Agent1Output
    from models.metadata import (
        DurationEstimate,
        RawPatternMetadata,
        SectionedScriptContent,
        TaxonomyContext,
    )

    metadata_model = RawPatternMetadata.model_validate(metadata) if metadata else None
    output = Agent1Output(
        transcript_id=tid,
        version_id=version_id,
        title=metadata.get("title", transcript.get("title", "Untitled")),
        transcript_text=db_version.content_text or "\n\n".join(s.text for s in sectioned.sections),
        sectioned_script=sectioned,
        pattern_plan=metadata_model.pattern_plan if metadata_model else build_example_pattern_plan(),
        taxonomy=metadata_model.taxonomy
        if metadata_model
        else TaxonomyContext(
            generation_code=request.generation_code,
            wound_id=request.wound_id,
            stage_no=request.stage_no,
            pillar_code=request.pillar_code,
        ),
        duration_estimate=metadata_model.duration_estimate
        if metadata_model
        else DurationEstimate(seconds=0),
        metadata=metadata_model
        or RawPatternMetadata(
            taxonomy=TaxonomyContext(
                generation_code=request.generation_code,
                wound_id=request.wound_id,
                stage_no=request.stage_no,
                pillar_code=request.pillar_code,
            ),
            pattern_plan=build_example_pattern_plan(),
            duration_estimate=DurationEstimate(seconds=0),
            title="Untitled",
        ),
    )

    report = TranscriptValidator(validation_mode=validation_mode).validate(request, output)
    print(report.format_summary())
    if report.issues:
        print()
        for issue in report.issues:
            slot = f" [{issue.slot}]" if issue.slot else ""
            print(f"  {issue.severity.value.upper()}{slot} ({issue.source}): {issue.message}")
    return 0 if report.passed else 1


def validate_compose_dry_run(*, duration_minutes: int, validation_mode: str | None) -> int:
    request = CreateTranscriptRequest(
        tenant_id=_settings().tenant_id,
        content_type="guided_meditation",
        generation_code="millennial",
        wound_id="ml_02",
        stage_no=2,
        pillar_code="p04",
        target_duration_minutes=duration_minutes,
    )
    validator = TranscriptValidator(validation_mode=validation_mode)
    generator = (
        TemplateScriptGenerator()
        if validation_mode == "rules"
        else get_default_script_generator()
    )
    try:
        output = CompositionService(
            generator=generator,
            validator=validator,
            validate_output=True,
        ).compose(request)
    except TranscriptValidationError as exc:
        print(exc.report.format_summary())
        if exc.report.issues:
            print()
            for issue in exc.report.issues:
                slot = f" [{issue.slot}]" if issue.slot else ""
                print(f"  {issue.severity.value.upper()}{slot} ({issue.source}): {issue.message}")
        return 1
    report = output.metadata.validation_report
    if report:
        print(json.dumps(report, indent=2))
        if output.metadata.validation_engine:
            print(f"\nengine: {output.metadata.validation_engine}")
    else:
        print("Validation ran but no report was stored.")
    return 0 if report and report.get("passed") else 1


def main() -> int:
    ensure_dotenv_loaded()
    parser = argparse.ArgumentParser(
        description="Check Agent 1 transcript against meditation_patterns_index and _examples",
    )
    parser.add_argument(
        "--transcript-id",
        help="Validate an existing transcript (reads RAW_PATTERN from API)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compose a test transcript locally (template generator) and validate",
    )
    parser.add_argument("--duration-minutes", type=int, default=5)
    parser.add_argument(
        "--rules",
        action="store_true",
        help="Use code-only rules validator (skip OpenAI even if key is set)",
    )
    parser.add_argument(
        "--openai",
        action="store_true",
        help="Force OpenAI validator (requires API key)",
    )
    args = parser.parse_args()

    validation_mode = None
    if args.rules:
        validation_mode = "rules"
    elif args.openai:
        validation_mode = "openai"

    if args.dry_run:
        return validate_compose_dry_run(
            duration_minutes=args.duration_minutes,
            validation_mode=validation_mode,
        )
    if args.transcript_id:
        return validate_existing_transcript(
            args.transcript_id,
            settings=_settings(),
            validation_mode=validation_mode,
        )

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
