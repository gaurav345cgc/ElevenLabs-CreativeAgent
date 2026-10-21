"""Run Agent 2 enhancement transactionally from an SQS job message."""

from __future__ import annotations

from uuid import uuid4

from db.exceptions import DuplicateVersionError, StateTransitionError, TranscriptNotFoundError
from db.repositories import TranscriptRepository
from db.session import build_session_factory, session_scope
from models.agents import Agent2Output
from models.enums import TranscriptStatus
from models.messages import EnhancementJobMessage
from models.metadata import DurationEstimate, EnhancedScriptContent, SectionedScriptContent
from observability.logging import log_enhancer_event
from queues.idempotency import find_existing_enhanced_version
from tts_enhancer.engine import EnhancementEngine, get_default_enhancement_engine
from tts_enhancer.exceptions import EnhancementQualityError, TransientEnhancementError
from tts_enhancer.persistence import persist_agent2_output


class EnhancementService:
    """Load raw transcript, claim, enhance, and persist ElevenLabs-ready output."""

    def __init__(
        self,
        *,
        repository: TranscriptRepository | None = None,
        engine: EnhancementEngine | None = None,
        database_url: str | None = None,
    ) -> None:
        if repository is not None:
            self._repository = repository
        else:
            self._repository = TranscriptRepository(build_session_factory(database_url))
        self._engine = engine or get_default_enhancement_engine()

    def run(self, message: EnhancementJobMessage) -> Agent2Output:
        correlation_id = message.correlation_id
        log_enhancer_event(
            "enhancement_started",
            correlation_id=correlation_id,
            transcript_id=message.transcript_id,
            raw_version_id=message.raw_version_id,
            requested_output_mode=message.requested_output_mode.value,
        )

        try:
            with session_scope(self._repository._session_factory) as session:
                existing = find_existing_enhanced_version(self._repository, session, message)
                if existing is not None:
                    log_enhancer_event(
                        "enhancement_already_complete",
                        correlation_id=correlation_id,
                        transcript_id=message.transcript_id,
                        enhanced_version_id=existing.id,
                    )
                    return _output_from_existing_version(message, existing)

                try:
                    self._repository.claim_for_enhancement(
                        session,
                        message.transcript_id,
                        correlation_id=correlation_id,
                    )
                except StateTransitionError as exc:
                    existing = find_existing_enhanced_version(self._repository, session, message)
                    if existing is not None:
                        return _output_from_existing_version(message, existing)
                    transcript = self._repository.get_transcript(session, message.transcript_id)
                    if transcript.status == TranscriptStatus.ENHANCING:
                        raise TransientEnhancementError(
                            f"transcript {message.transcript_id} is already being enhanced"
                        ) from exc
                    raise

                raw_version = self._load_raw_version(session, message)
                sectioned = _load_sectioned_script(raw_version.content_json)

                engine_result = self._engine.enhance(
                    raw_text=raw_version.content_text,
                    sectioned_script=sectioned,
                    enhancement_mode=message.requested_output_mode,
                    voice_model=message.voice_model,
                )

                output = Agent2Output(
                    transcript_id=message.transcript_id,
                    version_id=uuid4(),
                    source_version_id=message.raw_version_id,
                    enhanced_full_script=engine_result.enhanced_full_script,
                    sectioned_script=engine_result.sectioned_script,
                    enhanced_content=engine_result.enhanced_content,
                    voice_direction_notes=engine_result.voice_direction_notes,
                    pronunciation_notes=engine_result.pronunciation_notes,
                    duration_estimate=DurationEstimate(
                        seconds=engine_result.duration_estimate_seconds,
                        method="word_count_heuristic",
                    ),
                )
                persist_agent2_output(
                    self._repository,
                    session,
                    message=message,
                    output=output,
                    correlation_id=correlation_id,
                    source_metadata_json=raw_version.metadata_json,
                )
        except DuplicateVersionError:
            with session_scope(self._repository._session_factory) as session:
                existing = find_existing_enhanced_version(self._repository, session, message)
                if existing is None:
                    raise
                return _output_from_existing_version(message, existing)
        except EnhancementQualityError as exc:
            self._mark_review_required(message, str(exc), correlation_id=correlation_id)
            raise
        except TranscriptNotFoundError:
            raise

        log_enhancer_event(
            "enhancement_completed",
            correlation_id=correlation_id,
            transcript_id=output.transcript_id,
            version_id=output.version_id,
        )
        return output

    def _load_raw_version(self, session, message: EnhancementJobMessage):
        _, versions = self._repository.load_transcript_with_versions(
            session,
            message.transcript_id,
        )
        raw_version = next((v for v in versions if v.id == message.raw_version_id), None)
        if raw_version is None:
            raise TranscriptNotFoundError(
                f"raw version {message.raw_version_id} not found for transcript {message.transcript_id}"
            )
        return raw_version

    def _mark_review_required(
        self,
        message: EnhancementJobMessage,
        error_message: str,
        *,
        correlation_id: str | None,
    ) -> None:
        with session_scope(self._repository._session_factory) as session:
            self._repository.mark_enhancement_failed(
                session,
                message.transcript_id,
                error_message,
                review_required=True,
                correlation_id=correlation_id,
            )
        log_enhancer_event(
            "enhancement_review_required",
            level=30,
            correlation_id=correlation_id,
            transcript_id=message.transcript_id,
            error=error_message,
        )


def _load_sectioned_script(content_json: dict | None) -> SectionedScriptContent | None:
    if not content_json:
        return None
    if "sections" in content_json:
        return SectionedScriptContent.model_validate(content_json)
    if "sectioned_script" in content_json:
        return SectionedScriptContent.model_validate(content_json["sectioned_script"])
    return None


def _output_from_existing_version(message: EnhancementJobMessage, version) -> Agent2Output:
    metadata = version.metadata_json or {}
    content_json = version.content_json or {}
    return Agent2Output(
        transcript_id=message.transcript_id,
        version_id=version.id,
        source_version_id=message.raw_version_id,
        enhanced_full_script=version.content_text,
        enhanced_content=EnhancedScriptContent.model_validate(
            {
                "schema_version": content_json.get("schema_version", "1.0"),
                "beats": content_json.get("beats", []),
                "chunks": content_json.get("chunks", []),
                "extra": content_json.get("extra", {}),
            }
        ),
        voice_direction_notes=metadata.get("voice_direction_notes", []),
        pronunciation_notes=metadata.get("pronunciation_notes", []),
    )


def build_enhancement_service_for_tests(
    *,
    database_url: str | None = None,
    engine: EnhancementEngine | None = None,
) -> EnhancementService:
    return EnhancementService(database_url=database_url, engine=engine)
