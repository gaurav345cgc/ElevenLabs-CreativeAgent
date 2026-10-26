"""Agent 1 end-to-end orchestration: compose, persist, queue."""

from __future__ import annotations

from dataclasses import dataclass

from models.agents import Agent1Output
from models.messages import EnhancementJobMessage
from models.requests import CreateTranscriptRequest
from db.repositories import TranscriptRepository
from db.session import build_session_factory, session_scope
from observability.logging import log_composer_event
from queues.publisher import EnhancementQueuePublisher, InMemoryEnhancementPublisher, SqsEnhancementPublisher
from transcript_composer.composition_service import CompositionService
from transcript_composer.validation import TranscriptValidationError
from transcript_composer.persistence import persist_agent1_output


@dataclass(frozen=True, slots=True)
class Agent1RunResult:
    output: Agent1Output
    queue_message_id: str


class Agent1Service:
    """Pattern Transcript Composer — full Lambda 1 workflow."""

    def __init__(
        self,
        *,
        composition_service: CompositionService | None = None,
        repository: TranscriptRepository | None = None,
        publisher: EnhancementQueuePublisher | None = None,
        database_url: str | None = None,
    ) -> None:
        self._composition = composition_service or CompositionService()
        if repository is not None:
            self._repository = repository
        else:
            self._repository = TranscriptRepository(build_session_factory(database_url))
        self._publisher = publisher or SqsEnhancementPublisher()

    def run(self, request: CreateTranscriptRequest) -> Agent1RunResult:
        correlation_id = request.correlation_id
        log_composer_event(
            "composition_started",
            correlation_id=correlation_id,
            tenant_id=request.tenant_id,
            wound_id=request.wound_id,
            stage_no=request.stage_no,
        )

        try:
            output = None
            last_validation_error: TranscriptValidationError | None = None
            for attempt in range(1, 3):
                try:
                    output = self._composition.compose(request)
                    break
                except TranscriptValidationError as exc:
                    last_validation_error = exc
                    retryable = any(
                        issue.code
                        in {
                            "session_theme_missing",
                            "relatability_keywords_missing",
                            "relatability_opening_weak",
                            "relatability_pillar_missing",
                            "relatability_forbidden",
                            "relatability_better_match",
                            "pain_pillar_wound_weak",
                            "pain_pillar_pillar_mismatch",
                            "pain_pillar_better_match",
                            "pain_pillar_generic",
                            "pain_pillar_mind_heart_miss",
                        }
                        for issue in exc.report.issues
                    )
                    log_composer_event(
                        "composition_validation_failed",
                        level=40,
                        correlation_id=correlation_id,
                        tenant_id=request.tenant_id,
                        attempt=attempt,
                        validation_errors=exc.report.error_count,
                        validation_warnings=exc.report.warning_count,
                        issues=[issue.model_dump(mode="json") for issue in exc.report.issues],
                    )
                    if not retryable or attempt >= 2:
                        raise
            if output is None:
                assert last_validation_error is not None
                raise last_validation_error
        except TranscriptValidationError:
            raise

        log_composer_event(
            "composition_validated",
            correlation_id=correlation_id,
            transcript_id=output.transcript_id,
            tenant_id=request.tenant_id,
            validation_passed=True,
            validation_errors=0,
            validation_warnings=output.metadata.validation_report.get("warning_count", 0)
            if output.metadata.validation_report
            else 0,
        )
        log_composer_event(
            "composition_completed",
            correlation_id=correlation_id,
            transcript_id=output.transcript_id,
            version_id=output.version_id,
            tenant_id=request.tenant_id,
            pattern_families=[slot.pattern_family for slot in output.pattern_plan.slots],
        )

        with session_scope(self._repository._session_factory) as session:
            persist_agent1_output(
                self._repository,
                session,
                request=request,
                output=output,
                correlation_id=correlation_id,
            )

        message = EnhancementJobMessage.from_ids(
            transcript_id=output.transcript_id,
            tenant_id=request.tenant_id,
            raw_version_id=output.version_id,
            requested_output_mode=request.requested_output_mode,
            voice_model=request.voice_model,
            correlation_id=correlation_id,
        )
        queue_message_id = self._publisher.publish(message)
        log_composer_event(
            "enhancement_job_published",
            correlation_id=correlation_id,
            transcript_id=output.transcript_id,
            tenant_id=request.tenant_id,
            raw_version_id=output.version_id,
            queue_message_id=queue_message_id,
        )
        return Agent1RunResult(output=output, queue_message_id=queue_message_id)


def build_agent1_service_for_tests(
    *,
    publisher: InMemoryEnhancementPublisher | None = None,
    database_url: str | None = None,
) -> tuple[Agent1Service, InMemoryEnhancementPublisher]:
    memory_publisher = publisher or InMemoryEnhancementPublisher()
    service = Agent1Service(
        publisher=memory_publisher,
        database_url=database_url,
    )
    return service, memory_publisher
