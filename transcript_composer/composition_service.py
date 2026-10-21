"""Orchestrate pattern selection, example retrieval, and script generation."""

from __future__ import annotations

from uuid import uuid4

from models.agents import Agent1Output
from models.metadata import RawPatternMetadata, TaxonomyContext
from models.requests import CreateTranscriptRequest
from transcript_composer.duration import build_session_duration_budget, estimate_duration_seconds
from transcript_composer.knowledge import ExampleRetriever, PatternSelectionContext, PatternSelector
from transcript_composer.knowledge.models import RankedExample
from transcript_composer.script_generator import (
    ScriptGenerator,
    TemplateScriptGenerator,
    get_default_script_generator,
    script_generator_name,
)
from transcript_composer.title import build_title
from transcript_composer.validation import TranscriptValidator


class CompositionService:
    """Build Agent1Output from a validated content brief."""

    def __init__(
        self,
        *,
        selector: PatternSelector | None = None,
        retriever: ExampleRetriever | None = None,
        generator: ScriptGenerator | None = None,
        validator: TranscriptValidator | None = None,
        validate_output: bool = True,
    ) -> None:
        self._selector = selector or PatternSelector()
        self._retriever = retriever or ExampleRetriever(selector=self._selector)
        self._generator = generator or get_default_script_generator()
        self._validator = validator or TranscriptValidator(
            selector=self._selector,
            validation_mode="rules"
            if isinstance(self._generator, TemplateScriptGenerator)
            else None,
        )
        self._validate_output = validate_output

    def compose(self, request: CreateTranscriptRequest) -> Agent1Output:
        context = PatternSelectionContext(
            generation_code=request.generation_code,
            wound_id=request.wound_id,
            stage_no=request.stage_no,
            pillar_code=request.pillar_code,
            content_type=request.content_type,
        )
        plan = self._selector.build_pattern_plan(context)
        example_refs = self._retriever.examples_for_plan(context, plan, per_slot=3)
        sectioned = self._generator.generate_sections(request, plan, example_refs, self._selector)
        transcript_text = "\n\n".join(section.text for section in sectioned.sections)
        title = build_title(request)
        duration_estimate = estimate_duration_seconds(transcript_text)
        duration_budget = build_session_duration_budget(request.target_duration_minutes)
        taxonomy = TaxonomyContext(
            generation_code=request.generation_code,
            wound_id=request.wound_id,
            stage_no=request.stage_no,
            pillar_code=request.pillar_code,
            principles=request.principles,
        )
        metadata = RawPatternMetadata(
            taxonomy=taxonomy,
            pattern_plan=plan,
            duration_estimate=duration_estimate,
            title=title,
            example_reference_ids=_collect_example_ids(example_refs),
            script_generator=script_generator_name(self._generator),
            **duration_budget.as_metadata(),
        )
        output = Agent1Output(
            transcript_id=uuid4(),
            version_id=uuid4(),
            title=title,
            transcript_text=transcript_text,
            sectioned_script=sectioned,
            pattern_plan=plan,
            taxonomy=taxonomy,
            duration_estimate=duration_estimate,
            metadata=metadata,
        )
        if self._validate_output:
            validation = self._validator.validate_or_raise(request, output)
            output.metadata.validation_report = validation.model_dump(mode="json")
            output.metadata.validation_engine = self._validator.validation_mode
        return output


def _collect_example_ids(example_refs: dict[str, list[RankedExample]]) -> list[str]:
    ids: list[str] = []
    for ranked_list in example_refs.values():
        if ranked_list:
            example_id = ranked_list[0].example.example_id
            if example_id not in ids:
                ids.append(example_id)
    return ids
