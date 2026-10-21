"""Tests for OpenAI script generation."""

from __future__ import annotations

from uuid import uuid4

import pytest

from models.requests import CreateTranscriptRequest
from models.validation import COMPOSITION_SLOTS
from transcript_composer.composition_service import CompositionService
from transcript_composer.knowledge import PatternSelectionContext, PatternSelector
from transcript_composer.knowledge.example_retriever import ExampleRetriever
from transcript_composer.llm_config import resolve_openai_api_key
from transcript_composer.script_generator import (
    OpenAIScriptGenerator,
    TemplateScriptGenerator,
    get_default_script_generator,
)


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        slot = "opening"
        user_content = kwargs["messages"][1]["content"]
        if "Settling" in user_content:
            slot = "settling"
        elif "**Body**" in user_content:
            slot = "body"
        elif "**Breath**" in user_content:
            slot = "breath"
        elif "Mind and heart" in user_content:
            slot = "mind_heart"
        elif "**Closing**" in user_content:
            slot = "closing"
        # Long enough for section min words and overall duration checks in compose().
        base = (
            f"Spoken narration for the {slot} section. "
            "You arrive gently here. Soften your attention. "
            "There is nothing to force. Stay with what is present. "
            "Let the next moment unfold without hurry. "
        )
        text = (base * 8).strip()
        return _FakeResponse(text)

class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.chat = _FakeChat()


def _sample_request() -> CreateTranscriptRequest:
    return CreateTranscriptRequest(
        tenant_id=uuid4(),
        content_type="guided_meditation",
        generation_code="millennial",
        wound_id="ml_02",
        stage_no=2,
        target_duration_minutes=10,
        pillar_code="p04",
    )


@pytest.fixture(autouse=True)
def _clear_api_key_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    resolve_openai_api_key.cache_clear()
    monkeypatch.delenv("CREATIVE_AGENT_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CREATIVE_AGENT_MODEL_PROVIDER_SECRET_ARN", raising=False)
    monkeypatch.setenv("CREATIVE_AGENT_SCRIPT_GENERATOR", "template")


def test_openai_generator_calls_model_per_section() -> None:
    client = FakeOpenAIClient()
    generator = OpenAIScriptGenerator(client=client, api_key="test-key")
    request = _sample_request()
    selector = PatternSelector()
    context = PatternSelectionContext(
        generation_code=request.generation_code,
        wound_id=request.wound_id,
        stage_no=request.stage_no,
        pillar_code=request.pillar_code,
    )
    plan = selector.build_pattern_plan(context)
    refs = ExampleRetriever(selector=selector).examples_for_plan(context, plan)

    sectioned = generator.generate_sections(request, plan, refs, selector)

    assert len(sectioned.sections) == len(COMPOSITION_SLOTS)
    assert len(client.chat.completions.calls) == len(COMPOSITION_SLOTS)
    assert all("instruction" not in section.text.lower() for section in sectioned.sections)
    assert all(section.text.startswith("Spoken narration") for section in sectioned.sections)


def test_get_default_script_generator_uses_template_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATIVE_AGENT_SCRIPT_GENERATOR", "template")
    generator = get_default_script_generator()
    assert isinstance(generator, TemplateScriptGenerator)


def test_get_default_script_generator_uses_openai_when_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREATIVE_AGENT_SCRIPT_GENERATOR", "auto")
    monkeypatch.setenv("CREATIVE_AGENT_OPENAI_API_KEY", "test-key")
    generator = get_default_script_generator()
    assert isinstance(generator, OpenAIScriptGenerator)


def test_composition_service_with_openai_generator() -> None:
    client = FakeOpenAIClient()
    generator = OpenAIScriptGenerator(client=client, api_key="test-key")
    request = _sample_request()
    request = request.model_copy(update={"target_duration_minutes": 2})
    output = CompositionService(generator=generator).compose(request)

    assert len(output.sectioned_script.sections) == 6
    assert "Tell the listener what this session is for" not in output.transcript_text
    assert len(client.chat.completions.calls) == 6
    first_prompt = client.chat.completions.calls[0]["messages"][1]["content"]
    assert "meditation_patterns_index.md" in first_prompt
    assert "canonical_pattern beats" in first_prompt
    assert "guided_meditation_intro" in first_prompt
    assert "Opening section rules" in first_prompt
    assert "brief" in first_prompt.lower()
    second_prompt = client.chat.completions.calls[1]["messages"][1]["content"]
    assert "After the intro" in second_prompt
