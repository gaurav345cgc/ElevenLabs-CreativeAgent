"""LangGraph orchestrator for compose -> QA repair -> enhance -> TTS."""

from __future__ import annotations

from typing import Any

__all__ = ["PipelineRunConfig", "build_pipeline_graph", "run_pipeline"]


def __getattr__(name: str) -> Any:
    if name == "PipelineRunConfig":
        from pipeline_orchestrator.runner import PipelineRunConfig

        return PipelineRunConfig
    if name == "run_pipeline":
        from pipeline_orchestrator.runner import run_pipeline

        return run_pipeline
    if name == "build_pipeline_graph":
        from pipeline_orchestrator.graph import build_pipeline_graph

        return build_pipeline_graph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
