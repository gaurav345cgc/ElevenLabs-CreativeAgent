"""TTS job intake validation errors."""

from __future__ import annotations


class AudioJobIntakeError(Exception):
    """Base error for TTS job intake."""


class IntakeValidationError(AudioJobIntakeError):
    """Request or upstream transcript state is not valid for TTS."""
