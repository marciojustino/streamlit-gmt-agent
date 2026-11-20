from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Callable

from .agents import AgentRegistry, FinalAgent, FinalInput
from .audit import AuditWriteError, JsonlAuditLogger
from .config import AppConfig
from .contracts import (
    AgentOutcome,
    AuditRecord,
    KnowledgeResult,
    MemoryStatus,
    OrchestratorInput,
    OrchestratorResult,
    ResponseStatus,
)
from .knowledge import KnowledgeBase, KnowledgeBaseError
from .memory import MemoryAgent
from .policy import classify_question, sanitize_question


class GMTKnowledgeAgent:
    name = "gmt_knowledge"

    def __init__(self, knowledge_base: KnowledgeBase, top_k: int):
        self.knowledge_base = knowledge_base
        self.top_k = top_k

    def run(self, question: str) -> KnowledgeResult:
        return self.knowledge_base.answer(question, self.top_k)


class GMTOrchestrator:
    name = "gmt_orchestrator"
    max_question_chars = 4000
    _SESSION_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

    def __init__(
        self,
        config: AppConfig,
        knowledge_agent: GMTKnowledgeAgent,
        memory_agent: MemoryAgent,
        final_agent: FinalAgent,
        audit_logger: JsonlAuditLogger,
        clock: Callable[[], datetime] | None = None,
    ):
        self.config = config
        self.knowledge_agent = knowledge_agent
        self.memory_agent = memory_agent
        self.final_agent = final_agent
        self.audit_logger = audit_logger
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.registry = AgentRegistry()
        for agent in (knowledge_agent, memory_agent, final_agent, self):
            self.registry.register(agent)

    def process(self, request: OrchestratorInput) -> OrchestratorResult:
        started = time.monotonic()
        audit_id = str(uuid.uuid4())
        outcomes = [AgentOutcome(self.name, "started")]
        failure_code: str | None = None

        if not self._authorized(request.user_id, request.environment):
            result = self._result(
                "A sessão não está autorizada para este ambiente.",
                ResponseStatus.BLOCKED,
                audit_id,
                ("Autenticação institucional ou autorização explícita não foi confirmada.",),
            )
            outcomes[0] = AgentOutcome(self.name, "blocked")
            return self._finish(request, result, outcomes, started, failure_code)

        if not isinstance(request.session_id, str) or not self._SESSION_ID.fullmatch(
            request.session_id
        ):
            result = self._result(
                "A identificação da sessão é inválida.",
                ResponseStatus.BLOCKED,
                audit_id,
                ("A identificação da sessão não passou pela validação.",),
            )
            outcomes[0] = AgentOutcome(self.name, "blocked")
            return self._finish(request, result, outcomes, started, failure_code)

        if (
            not isinstance(request.question, str)
            or not request.question.strip()
            or len(request.question) > self.max_question_chars
        ):
            result = self._result(
                "A pergunta está vazia ou excede o limite permitido.",
                ResponseStatus.BLOCKED,
                audit_id,
                ("A entrada não passou pela validação de tamanho.",),
            )
            outcomes[0] = AgentOutcome(self.name, "blocked")
            return self._finish(request, result, outcomes, started, failure_code)

        if not isinstance(request.question, str):
            result = self._result(
                "A pergunta está vazia ou excede o limite permitido.",
                ResponseStatus.BLOCKED,
                audit_id,
                ("A entrada não passou pela validação de tipo.",),
            )
            outcomes[0] = AgentOutcome(self.name, "blocked")
            return self._finish(request, result, outcomes, started, failure_code)

        sanitized_question, contains_personal_data = sanitize_question(request.question)
        if contains_personal_data:
            result = self._result(
                "Remova dados pessoais desnecessários e envie novamente a pergunta.",
                ResponseStatus.BLOCKED,
                audit_id,
                ("A entrada aparenta conter dado pessoal; ela não foi consultada nem persistida.",),
            )
            outcomes[0] = AgentOutcome(self.name, "blocked")
            return self._finish(request, result, outcomes, started, failure_code)

        policy_assessment = classify_question(request.question)
        if policy_assessment:
            policy_status, policy_limitation = policy_assessment
            answer = (
                "Esta solicitação requer revisão humana antes de uma resposta."
                if policy_status == ResponseStatus.NEEDS_HUMAN_REVIEW
                else "Não posso atender a esta solicitação neste fluxo."
            )
            result = self._result(
                answer,
                policy_status,
                audit_id,
                (policy_limitation,),
            )
            outcomes[0] = AgentOutcome(self.name, policy_status.value)
            return self._finish(request, result, outcomes, started, failure_code)

        outcomes.append(AgentOutcome(self.memory_agent.name, "started"))
        memory = self.memory_agent.read(request.session_id, request.user_id)
        outcomes[-1] = AgentOutcome(self.memory_agent.name, memory.status.value)
        if memory.status == MemoryStatus.BLOCKED:
            result = self._result(
                "O contexto desta sessão não está autorizado.",
                ResponseStatus.BLOCKED,
                audit_id,
                ("O histórico pertence a outra identidade autorizada.",),
            )
            outcomes[0] = AgentOutcome(self.name, "blocked")
            return self._finish(request, result, outcomes, started, failure_code)

        outcomes.append(AgentOutcome(self.knowledge_agent.name, "started"))
        try:
            knowledge = self.knowledge_agent.run(request.question)
        except KnowledgeBaseError:
            failure_code = "knowledge_base_unavailable"
            outcomes[-1] = AgentOutcome(self.knowledge_agent.name, "failed")
            result = self._result(
                "Não foi possível validar a base de conhecimento. Encaminhe para revisão humana.",
                ResponseStatus.NEEDS_HUMAN_REVIEW,
                audit_id,
                ("A consulta à base de conhecimento falhou.",),
            )
            outcomes[0] = AgentOutcome(self.name, "needs_human_review")
            return self._finish(request, result, outcomes, started, failure_code)
        outcomes[-1] = AgentOutcome(self.knowledge_agent.name, "completed")

        outcomes.append(AgentOutcome(self.final_agent.name, "started"))
        final = self.final_agent.synthesize(
            FinalInput(question=request.question, knowledge=knowledge, memory=memory)
        )
        outcomes[-1] = AgentOutcome(self.final_agent.name, final.status.value)

        if final.status in {ResponseStatus.ANSWERED, ResponseStatus.INSUFFICIENT_CONTEXT}:
            updated_memory = self.memory_agent.remember(
                request.session_id, request.user_id, sanitized_question
            )
            if updated_memory.status == MemoryStatus.BLOCKED:
                result = self._result(
                    "O contexto desta sessão não está autorizado.",
                    ResponseStatus.BLOCKED,
                    audit_id,
                    ("O histórico pertence a outra identidade autorizada.",),
                )
                outcomes[0] = AgentOutcome(self.name, "blocked")
                return self._finish(request, result, outcomes, started, failure_code)
            outcomes[-1] = AgentOutcome(
                self.final_agent.name,
                f"{final.status.value};memory_{updated_memory.status.value}",
            )

        outcomes[0] = AgentOutcome(self.name, "completed")
        result = OrchestratorResult(
            answer=final.answer,
            status=final.status,
            sources=final.sources,
            limitations=final.limitations,
            audit_id=audit_id,
            audited_sources=final.consulted_sources,
        )
        return self._finish(request, result, outcomes, started, failure_code)

    def _authorized(self, user_id: str, environment: str) -> bool:
        if self.config.authorization_mode == "local":
            return (
                self.config.environment == "local"
                and environment == "local"
                and user_id == "local-developer"
            )
        return (
            isinstance(user_id, str)
            and bool(user_id.strip())
            and isinstance(environment, str)
            and environment == self.config.environment
            and user_id.casefold() in self.config.allowed_user_ids
        )

    def _result(
        self,
        answer: str,
        status: ResponseStatus,
        audit_id: str,
        limitations: tuple[str, ...],
    ) -> OrchestratorResult:
        return OrchestratorResult(
            answer=answer,
            status=status,
            sources=(),
            limitations=limitations,
            audit_id=audit_id,
        )

    def _finish(
        self,
        request: OrchestratorInput,
        result: OrchestratorResult,
        outcomes: list[AgentOutcome],
        started: float,
        failure_code: str | None,
    ) -> OrchestratorResult:
        record = AuditRecord(
            session_id=(
                request.session_id
                if isinstance(request.session_id, str)
                and self._SESSION_ID.fullmatch(request.session_id)
                else "invalid-session"
            ),
            audit_id=result.audit_id,
            agent_version="0.1.0",
            timestamp=self.clock().isoformat(),
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            status=result.status.value,
            agents=tuple(outcomes),
            sources=tuple(
                source.audit_dict()
                for source in (result.audited_sources or result.sources)
            ),
            limitations=result.limitations,
            failure_code=failure_code,
        )
        try:
            self.audit_logger.write(record)
        except AuditWriteError:
            return OrchestratorResult(
                answer="A execução foi interrompida porque não foi possível registrar a auditoria.",
                status=ResponseStatus.BLOCKED,
                sources=(),
                limitations=("Falha no registro de auditoria; resposta não concluída.",),
                audit_id=result.audit_id,
            )
        return result


def build_system(
    config: AppConfig, project_root: Path
) -> GMTOrchestrator:
    knowledge_base = KnowledgeBase(
        root=project_root / "kb",
        max_document_bytes=config.max_document_bytes,
        max_excerpt_chars=config.max_excerpt_chars,
    )
    knowledge_agent = GMTKnowledgeAgent(knowledge_base, config.top_k)
    memory_agent = MemoryAgent(config.memory_ttl_seconds, config.memory_max_turns)
    return GMTOrchestrator(
        config=config,
        knowledge_agent=knowledge_agent,
        memory_agent=memory_agent,
        final_agent=FinalAgent(),
        audit_logger=JsonlAuditLogger(
            config.audit_path
            if config.audit_path.is_absolute()
            else project_root / config.audit_path,
            config.audit_retention_days,
        ),
    )
