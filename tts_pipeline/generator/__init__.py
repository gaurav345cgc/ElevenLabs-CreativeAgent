"""Call ElevenLabs Create speech and write audio outputs."""

from tts_pipeline.generator.chunk_generation import (
    CHUNK_COMPLETED_EVENT,
    CHUNK_FAILED_EVENT,
    CHUNK_SKIPPED_EVENT,
    ChunkGenerationError,
    ChunkGenerationRunResult,
    build_chunk_synthesis_request,
    generate_chunks_sequentially,
    generate_single_chunk,
    is_transient_generation_error,
    should_skip_chunk_generation,
    synthesize_chunk_with_retry,
)
from tts_pipeline.generator.chunk_synthesis import StoredChunkSynthesis, synthesize_and_store_chunk
from tts_pipeline.generator.config import (
    DEFAULT_APPLY_TEXT_NORMALIZATION,
    DEFAULT_ENABLE_LOGGING,
    DEFAULT_MODEL_ID,
    DEFAULT_OUTPUT_FORMAT,
    ElevenLabsConfigError,
    require_elevenlabs_api_key,
    resolve_elevenlabs_api_key,
)
from tts_pipeline.generator.elevenlabs_client import (
    ElevenLabsApiError,
    ElevenLabsClient,
    HttpxElevenLabsTransport,
    PronunciationDictionaryLocator,
    SpeechSynthesisRequest,
    SpeechSynthesisResult,
    VoiceSettings,
)

__all__ = [
    "DEFAULT_APPLY_TEXT_NORMALIZATION",
    "DEFAULT_ENABLE_LOGGING",
    "DEFAULT_MODEL_ID",
    "DEFAULT_OUTPUT_FORMAT",
    "ChunkGenerationError",
    "ChunkGenerationRunResult",
    "ElevenLabsApiError",
    "ElevenLabsClient",
    "ElevenLabsConfigError",
    "HttpxElevenLabsTransport",
    "PronunciationDictionaryLocator",
    "SpeechSynthesisRequest",
    "SpeechSynthesisResult",
    "StoredChunkSynthesis",
    "VoiceSettings",
    "build_chunk_synthesis_request",
    "generate_chunks_sequentially",
    "generate_single_chunk",
    "is_transient_generation_error",
    "require_elevenlabs_api_key",
    "resolve_elevenlabs_api_key",
    "should_skip_chunk_generation",
    "synthesize_and_store_chunk",
    "synthesize_chunk_with_retry",
]
