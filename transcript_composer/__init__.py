"""Agent 1 — Pattern Transcript Composer."""

from transcript_composer.composition_service import CompositionService
from transcript_composer.handler import handler, parse_event
from transcript_composer.knowledge import (
    ExampleRetriever,
    PatternSelectionContext,
    PatternSelector,
)
from transcript_composer.service import Agent1RunResult, Agent1Service, build_agent1_service_for_tests

from transcript_composer.script_generator import (
    OpenAIScriptGenerator,
    TemplateScriptGenerator,
    get_default_script_generator,
)

__all__ = [
    "Agent1RunResult",
    "Agent1Service",
    "CompositionService",
    "ExampleRetriever",
    "OpenAIScriptGenerator",
    "PatternSelectionContext",
    "PatternSelector",
    "TemplateScriptGenerator",
    "build_agent1_service_for_tests",
    "get_default_script_generator",
    "handler",
    "parse_event",
]
