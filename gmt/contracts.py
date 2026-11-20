from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ResponseStatus(str, Enum):
    ANSWERED = "answered"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    BLOCKED = "blocked"
    INSUFFICIENT_CONTEXT = "insufficient_context"


class MemoryStatus(str, Enum):
    AVAILABLE = "available"
    EMPTY = "empty"
    EXPIRED = "expired"
    BLOCKED = "blocked"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class OrchestratorInput:
    session_id: str
    user_id: str
    question: str
    environment: str
    locale: str = "pt-BR"


@dataclass(frozen=True)
class SourceReference:
    document_id: str
    version: str
    updated_at: str
    excerpt: str
    approval_reference: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.document_id,
            "version": self.version,
            "updated_at": self.updated_at,
            "excerpt": self.excerpt,
            "approval_reference": self.approval_reference,
        }

    def audit_dict(self) -> dict[str, str]:
        return {
            "id": self.document_id,
            "version": self.version,
            "updated_at": self.updated_at,
            "approval_reference": self.approval_reference,
        }


@dataclass(frozen=True)
class KnowledgeResult:
    answer: str
    sources: tuple[SourceReference, ...] = ()
    consulted_sources: tuple[SourceReference, ...] = ()
    confidence: Confidence = Confidence.LOW
    missing_context: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    stale_sources: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    injection_detected: bool = False


@dataclass(frozen=True)
class MemoryResult:
    context_summary: str
    referenced_turn_ids: tuple[str, ...] = ()
    personal_data_present: bool = False
    status: MemoryStatus = MemoryStatus.EMPTY


@dataclass(frozen=True)
class FinalResult:
    answer: str
    status: ResponseStatus
    sources: tuple[SourceReference, ...] = ()
    consulted_sources: tuple[SourceReference, ...] = ()
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrchestratorResult:
    answer: str
    status: ResponseStatus
    sources: tuple[SourceReference, ...]
    limitations: tuple[str, ...]
    audit_id: str
    audited_sources: tuple[SourceReference, ...] = ()


@dataclass(frozen=True)
class AgentOutcome:
    name: str
    status: str


@dataclass(frozen=True)
class AuditRecord:
    session_id: str
    audit_id: str
    agent_version: str
    timestamp: str
    duration_ms: int
    status: str
    agents: tuple[AgentOutcome, ...] = field(default_factory=tuple)
    sources: tuple[dict[str, str], ...] = field(default_factory=tuple)
    limitations: tuple[str, ...] = field(default_factory=tuple)
    failure_code: str | None = None
    human_approvals: tuple[str, ...] = field(default_factory=tuple)
