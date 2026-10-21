"""Split enhanced transcripts into speech-friendly generation chunks."""

from __future__ import annotations

from models.records import TranscriptVersionRecord
from transcript_composer.duration import count_words
from tts_pipeline.chunk_planner.config import (
    CONTINUITY_CHARS,
    MAX_CHUNK_CHARS,
    MAX_CHUNK_WORDS,
    MAX_SENTENCES_PER_CHUNK,
    MEDITATION_WORDS_PER_MINUTE,
    MIN_CHUNK_CHARS,
)
from tts_pipeline.chunk_planner.errors import ChunkPlanValidationError
from tts_pipeline.chunk_planner.models import ChunkBoundarySource, PlannedChunk
from tts_pipeline.chunk_planner.sentences import (
    ends_complete_sentence,
    ends_with_weak_connector,
    group_sentences_into_chunks,
    split_paragraphs,
    split_sentences,
)


def estimate_chunk_duration_ms(text: str) -> int:
    words = count_words(text)
    seconds = max(1, round(words / MEDITATION_WORDS_PER_MINUTE * 60))
    return seconds * 1000


def continuity_excerpt(text: str) -> str:
    excerpt = text.strip()
    if len(excerpt) <= CONTINUITY_CHARS:
        return excerpt
    return excerpt[-CONTINUITY_CHARS:]


def plan_chunks_from_version(version: TranscriptVersionRecord) -> tuple[list[PlannedChunk], ChunkBoundarySource]:
    """Build a chunk plan from an ELEVENLABS_ENHANCED transcript version."""
    content_text = (version.content_text or "").strip()
    if not content_text:
        raise ChunkPlanValidationError("enhanced version has no content_text")

    # Always sentence-split so pause stitching can insert silence after each
    # spoken sentence (paragraph grouping packed multiple sentences into one
    # chunk and merged holds away).
    texts = group_sentences_into_chunks(
        split_sentences(content_text),
        max_words=MAX_CHUNK_WORDS,
        max_sentences=MAX_SENTENCES_PER_CHUNK,
    )
    source = ChunkBoundarySource.SENTENCES

    chunks = _texts_to_planned_chunks(texts, source)
    chunks = _merge_incomplete_sentence_boundaries(chunks)
    chunks = _merge_weak_connector_fragments(chunks)
    chunks = _merge_undersized_chunks(chunks)
    chunks = _split_oversized_chunks(chunks)
    chunks = _merge_incomplete_sentence_boundaries(chunks)
    chunks = _reindex_with_continuity(chunks, source)
    validate_chunk_plan(chunks)
    return chunks, source


def validate_chunk_plan(chunks: list[PlannedChunk]) -> None:
    if not chunks:
        raise ChunkPlanValidationError("chunk plan must contain at least one chunk")

    for chunk in chunks:
        if chunk.character_count < MIN_CHUNK_CHARS:
            raise ChunkPlanValidationError(
                f"chunk {chunk.chunk_index} has {chunk.character_count} chars "
                f"(minimum {MIN_CHUNK_CHARS})"
            )
        if chunk.character_count > MAX_CHUNK_CHARS:
            raise ChunkPlanValidationError(
                f"chunk {chunk.chunk_index} has {chunk.character_count} chars "
                f"(maximum {MAX_CHUNK_CHARS})"
            )
        if not chunk.source_text.strip():
            raise ChunkPlanValidationError(f"chunk {chunk.chunk_index} source_text is empty")


def _group_paragraphs(paragraphs: list[str]) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for paragraph in paragraphs:
        words = count_words(paragraph)
        if current and current_words + words > MAX_CHUNK_WORDS:
            chunks.append("\n\n".join(current))
            current = [paragraph]
            current_words = words
        else:
            current.append(paragraph)
            current_words += words

    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _merge_incomplete_sentence_boundaries(chunks: list[PlannedChunk]) -> list[PlannedChunk]:
    """Merge chunks that end mid-sentence into the following chunk."""
    if len(chunks) < 2:
        return chunks

    merged: list[PlannedChunk] = []
    carry: PlannedChunk | None = None

    for chunk in chunks:
        if carry is None:
            if not ends_complete_sentence(chunk.source_text) or ends_with_weak_connector(chunk.source_text):
                carry = chunk
            else:
                merged.append(chunk)
            continue

        combined = f"{carry.source_text}\n\n{chunk.source_text}".strip()
        carry = PlannedChunk(
            chunk_index=carry.chunk_index,
            source_text=combined,
            previous_text=carry.previous_text,
            next_text=chunk.next_text,
            character_count=len(combined),
            estimated_duration_ms=estimate_chunk_duration_ms(combined),
            boundary_source=carry.boundary_source,
        )
        if ends_complete_sentence(combined) and not ends_with_weak_connector(combined):
            merged.append(carry)
            carry = None

    if carry is not None:
        if merged:
            prev = merged[-1]
            combined = f"{prev.source_text}\n\n{carry.source_text}".strip()
            merged[-1] = PlannedChunk(
                chunk_index=prev.chunk_index,
                source_text=combined,
                previous_text=prev.previous_text,
                next_text=carry.next_text,
                character_count=len(combined),
                estimated_duration_ms=estimate_chunk_duration_ms(combined),
                boundary_source=prev.boundary_source,
            )
        else:
            merged.append(carry)

    return merged


def _texts_to_planned_chunks(texts: list[str], source: ChunkBoundarySource) -> list[PlannedChunk]:
    planned: list[PlannedChunk] = []
    for index, text in enumerate(texts):
        normalized = text.strip()
        planned.append(
            PlannedChunk(
                chunk_index=index,
                source_text=normalized,
                previous_text=None,
                next_text=None,
                character_count=len(normalized),
                estimated_duration_ms=estimate_chunk_duration_ms(normalized),
                boundary_source=source,
            )
        )
    return planned


def _ends_with_weak_connector(text: str) -> bool:
    return ends_with_weak_connector(text)


def _merge_weak_connector_fragments(chunks: list[PlannedChunk]) -> list[PlannedChunk]:
    if len(chunks) < 2:
        return chunks

    merged: list[PlannedChunk] = [chunks[0]]
    for chunk in chunks[1:]:
        previous = merged[-1]
        if _ends_with_weak_connector(previous.source_text):
            combined = f"{previous.source_text}\n\n{chunk.source_text}".strip()
            merged[-1] = PlannedChunk(
                chunk_index=previous.chunk_index,
                source_text=combined,
                previous_text=previous.previous_text,
                next_text=chunk.next_text,
                character_count=len(combined),
                estimated_duration_ms=estimate_chunk_duration_ms(combined),
                boundary_source=previous.boundary_source,
            )
        else:
            merged.append(chunk)
    return merged


def _merge_undersized_chunks(chunks: list[PlannedChunk]) -> list[PlannedChunk]:
    if len(chunks) < 2:
        return chunks

    merged = list(chunks)
    index = 0
    while index < len(merged):
        chunk = merged[index]
        if chunk.character_count >= MIN_CHUNK_CHARS or len(merged) == 1:
            index += 1
            continue

        if index + 1 < len(merged):
            nxt = merged[index + 1]
            combined = f"{chunk.source_text}\n\n{nxt.source_text}".strip()
            merged[index] = PlannedChunk(
                chunk_index=chunk.chunk_index,
                source_text=combined,
                previous_text=chunk.previous_text,
                next_text=nxt.next_text,
                character_count=len(combined),
                estimated_duration_ms=estimate_chunk_duration_ms(combined),
                boundary_source=chunk.boundary_source,
            )
            merged.pop(index + 1)
            continue

        if index > 0:
            prev = merged[index - 1]
            combined = f"{prev.source_text}\n\n{chunk.source_text}".strip()
            merged[index - 1] = PlannedChunk(
                chunk_index=prev.chunk_index,
                source_text=combined,
                previous_text=prev.previous_text,
                next_text=chunk.next_text,
                character_count=len(combined),
                estimated_duration_ms=estimate_chunk_duration_ms(combined),
                boundary_source=prev.boundary_source,
            )
            merged.pop(index)
            index -= 1
            continue

        index += 1
    return merged


def _split_oversized_chunks(chunks: list[PlannedChunk]) -> list[PlannedChunk]:
    result: list[PlannedChunk] = []
    for chunk in chunks:
        if chunk.character_count <= MAX_CHUNK_CHARS:
            result.append(chunk)
            continue
        sentences = split_sentences(chunk.source_text)
        if len(sentences) <= 1:
            paragraphs = split_paragraphs(chunk.source_text)
            if len(paragraphs) <= 1:
                raise ChunkPlanValidationError(
                    f"chunk {chunk.chunk_index} exceeds max size and cannot be split safely"
                )
            split_texts = _group_paragraphs(paragraphs)
        else:
            split_texts = group_sentences_into_chunks(
                sentences,
                max_words=MAX_CHUNK_WORDS,
                max_sentences=MAX_SENTENCES_PER_CHUNK,
            )
        for text in split_texts:
            normalized = text.strip()
            result.append(
                PlannedChunk(
                    chunk_index=len(result),
                    source_text=normalized,
                    previous_text=None,
                    next_text=None,
                    character_count=len(normalized),
                    estimated_duration_ms=estimate_chunk_duration_ms(normalized),
                    boundary_source=ChunkBoundarySource.SIZE_SPLIT,
                )
            )
    return result


def _reindex_with_continuity(
    chunks: list[PlannedChunk],
    default_source: ChunkBoundarySource,
) -> list[PlannedChunk]:
    reindexed: list[PlannedChunk] = []
    for index, chunk in enumerate(chunks):
        previous_text = continuity_excerpt(chunks[index - 1].source_text) if index > 0 else None
        next_text = (
            continuity_excerpt(chunks[index + 1].source_text) if index + 1 < len(chunks) else None
        )
        reindexed.append(
            PlannedChunk(
                chunk_index=index,
                source_text=chunk.source_text,
                previous_text=previous_text,
                next_text=next_text,
                character_count=len(chunk.source_text),
                estimated_duration_ms=estimate_chunk_duration_ms(chunk.source_text),
                boundary_source=chunk.boundary_source or default_source,
            )
        )
    return reindexed
