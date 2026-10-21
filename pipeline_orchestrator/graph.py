"""LangGraph workflow definition for compose -> enhance -> TTS."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from observability.logging import log_orchestrator_event
from pipeline_orchestrator.client import CreativeAgentClient
from pipeline_orchestrator.config import OrchestratorSettings
from pipeline_orchestrator.nodes import (
    route_entry,
    run_compose,
    run_download,
    run_enhance,
    run_tts,
)
from pipeline_orchestrator.state import TERMINAL_STAGES, PipelineState


def _route_after(state: PipelineState) -> str:
    stage = state.get("stage", "route")
    if stage in TERMINAL_STAGES:
        return stage
    return stage


def build_pipeline_graph(
    *,
    client: CreativeAgentClient,
    settings: OrchestratorSettings,
    compose_brief: dict[str, Any],
):
    """Build a compiled LangGraph that resumes from the last incomplete stage."""

    def route_node(state: PipelineState) -> PipelineState:
        log_orchestrator_event("graph node: route", event_type="graph_node", node="route")
        return route_entry(state, client=client)

    def compose_node(state: PipelineState) -> PipelineState:
        log_orchestrator_event(
            "graph node: compose",
            event_type="graph_node",
            node="compose",
            correlation_id=state.get("correlation_id"),
        )
        return run_compose(
            state,
            client=client,
            settings=settings,
            compose_brief=compose_brief,
        )

    def enhance_node(state: PipelineState) -> PipelineState:
        log_orchestrator_event(
            "graph node: enhance",
            event_type="graph_node",
            node="enhance",
            correlation_id=state.get("correlation_id"),
            transcript_id=state.get("transcript_id"),
        )
        return run_enhance(state, client=client, settings=settings)

    def tts_node(state: PipelineState) -> PipelineState:
        log_orchestrator_event(
            "graph node: tts",
            event_type="graph_node",
            node="tts",
            correlation_id=state.get("correlation_id"),
            transcript_id=state.get("transcript_id"),
            audio_job_id=state.get("audio_job_id"),
        )
        return run_tts(state, client=client, settings=settings)

    def download_node(state: PipelineState) -> PipelineState:
        log_orchestrator_event(
            "graph node: download",
            event_type="graph_node",
            node="download",
            correlation_id=state.get("correlation_id"),
            audio_job_id=state.get("audio_job_id"),
        )
        return run_download(state, client=client, settings=settings)

    graph = StateGraph(PipelineState)
    graph.add_node("route", route_node)
    graph.add_node("compose", compose_node)
    graph.add_node("enhance", enhance_node)
    graph.add_node("tts", tts_node)
    graph.add_node("download", download_node)

    graph.add_edge(START, "route")

    graph.add_conditional_edges(
        "route",
        _route_after,
        {
            "compose": "compose",
            "enhance": "enhance",
            "tts": "tts",
            "download": "download",
            "done": END,
            "failed": END,
        },
    )

    graph.add_conditional_edges(
        "compose",
        _route_after,
        {"compose": "compose", "enhance": "enhance", "failed": END},
    )

    graph.add_conditional_edges(
        "enhance",
        _route_after,
        {"enhance": "enhance", "tts": "tts", "done": END, "failed": END},
    )

    graph.add_conditional_edges(
        "tts",
        _route_after,
        {"tts": "tts", "download": "download", "failed": END},
    )

    graph.add_edge("download", END)

    return graph.compile()
