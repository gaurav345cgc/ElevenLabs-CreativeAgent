"""TTS workflow orchestration errors."""


class OrchestratorError(Exception):
    """Base orchestrator error."""


class WorkflowValidationError(OrchestratorError):
    """Workflow input or preconditions are invalid."""


class WorkflowStateError(OrchestratorError):
    """A workflow state failed in a non-recoverable way."""
