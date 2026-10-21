"""Tests for Agent 2 Script Doctor (guide-driven rewrite)."""

from __future__ import annotations

import pytest

from models.metadata import ScriptSection, SectionedScriptContent
from tts_enhancer.prompts import build_system_prompt, load_agent2_guide_text
from tts_enhancer.script_doctor import (
    DeterministicScriptDoctor,
    OpenAIScriptDoctor,
    get_default_script_doctor,
    script_doctor_name,
)
from transcript_composer.llm_config import resolve_openai_api_key


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
        user_content = kwargs["messages"][1]["content"]
        if "composition_slot: closing" in user_content:
            return _FakeResponse("When you are ready, gently return.\n\nCarry this ease with you.")
        if "composition_slot: opening" in user_content:
            return _FakeResponse("Welcome to this quiet moment.\n\nYou are here to rest.")
        return _FakeResponse("Notice your breath.\n\nLet each exhale soften the body.")


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.chat = _FakeChat()


@pytest.fixture(autouse=True)
def _clear_api_key_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    resolve_openai_api_key.cache_clear()
    monkeypatch.delenv("CREATIVE_AGENT_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CREATIVE_AGENT_MODEL_PROVIDER_SECRET_ARN", raising=False)
    monkeypatch.setenv("CREATIVE_AGENT_OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("CREATIVE_AGENT_MODEL_PROVIDER_SECRET_ARN", "")
    monkeypatch.setenv("CREATIVE_AGENT_SCRIPT_DOCTOR", "deterministic")


def test_system_prompt_includes_agent2_guide() -> None:
    prompt = build_system_prompt()
    guide = load_agent2_guide_text()
    assert "ElevenLabs Script Doctor" in prompt
    assert "short to medium sentences" in guide.lower() or "short to medium sentences" in prompt.lower()
    assert "[^" not in prompt
    assert "Second‑person, present tense" in prompt or "Second-person, present tense" in prompt


def test_openai_script_doctor_calls_model_per_section() -> None:
    client = FakeOpenAIClient()
    doctor = OpenAIScriptDoctor(client=client, api_key="test-key")
    sectioned = SectionedScriptContent(
        sections=[
            ScriptSection(slot="opening", title="Opening", text="Um, welcome here."),
            ScriptSection(slot="closing", title="Closing", text="Return when ready."),
        ]
    )

    full_script, output_sectioned, _ = doctor.rewrite(
        raw_text="ignored",
        sectioned_script=sectioned,
        voice_model="eleven_multilingual_v2",
    )

    assert len(client.chat.completions.calls) == 2
    system_prompt = client.chat.completions.calls[0]["messages"][0]["content"]
    assert "Agent 2" in system_prompt
    assert "Chunking and feeding text to ElevenLabs" in system_prompt
    assert output_sectioned is not None
    assert len(output_sectioned.sections) == 2
    assert "Welcome to this quiet moment" in full_script
    assert "gently return" in full_script


def test_get_default_script_doctor_uses_deterministic_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREATIVE_AGENT_SCRIPT_DOCTOR", "auto")
    resolve_openai_api_key.cache_clear()
    doctor = get_default_script_doctor()
    assert script_doctor_name(doctor) == "deterministic"


def test_get_default_script_doctor_uses_openai_when_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREATIVE_AGENT_SCRIPT_DOCTOR", "auto")
    monkeypatch.setenv("CREATIVE_AGENT_OPENAI_API_KEY", "test-key")
    doctor = get_default_script_doctor()
    assert script_doctor_name(doctor) == "openai"


def test_deterministic_script_doctor_removes_fillers() -> None:
    doctor = DeterministicScriptDoctor()
    text, _, _ = doctor.rewrite(
        raw_text="Um, take 2 slow breaths.",
        sectioned_script=None,
        voice_model="eleven_multilingual_v2",
    )
    assert "Um" not in text
    assert "two" in text
