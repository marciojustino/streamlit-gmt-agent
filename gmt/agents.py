from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import (
    Confidence,
    FinalResult,
    KnowledgeResult,
    MemoryResult,
    ResponseStatus,
)


class RegisteredAgent(Protocol):
    name: str


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, RegisteredAgent] = {}

    def register(self, agent: RegisteredAgent) -> None:
        if agent.name in self._agents:
            raise ValueError(f"Agente já registrado: {agent.name}")
        self._agents[agent.name] = agent

    def get(self, name: str) -> RegisteredAgent:
        return self._agents[name]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._agents)


@dataclass(frozen=True)
class FinalInput:
    question: str
    knowledge: KnowledgeResult
    memory: MemoryResult


class FinalAgent:
    name = "gmt_final"

    def synthesize(self, request: FinalInput) -> FinalResult:
        knowledge = request.knowledge
        if knowledge.contradictions:
            return FinalResult(
                answer="Encontrei divergência entre fontes aprovadas. Encaminhe a pergunta para revisão humana.",
                status=ResponseStatus.NEEDS_HUMAN_REVIEW,
                sources=knowledge.sources,
                consulted_sources=knowledge.consulted_sources or knowledge.sources,
                limitations=("Fontes conflitantes não foram consolidadas.",),
            )
        if knowledge.stale_sources:
            return FinalResult(
                answer="A evidência relacionada está fora da validade. É necessária revisão humana.",
                status=ResponseStatus.NEEDS_HUMAN_REVIEW,
                sources=knowledge.sources,
                consulted_sources=knowledge.consulted_sources or knowledge.sources,
                limitations=("Fonte aprovada vencida não foi usada como evidência.",),
            )
        if not knowledge.answer:
            return FinalResult(
                answer="Não encontrei contexto aprovado suficiente para responder.",
                status=ResponseStatus.INSUFFICIENT_CONTEXT,
                consulted_sources=knowledge.consulted_sources,
                limitations=knowledge.missing_context or (
                    "A base de conhecimento não contém evidência aplicável.",
                ),
            )

        limitations = list(knowledge.limitations)
        if knowledge.injection_detected:
            limitations.append("Trecho com instruções não confiáveis foi ignorado.")
        if knowledge.confidence == Confidence.LOW:
            return FinalResult(
                answer="A evidência encontrada é insuficiente para uma resposta segura.",
                status=ResponseStatus.INSUFFICIENT_CONTEXT,
                sources=knowledge.sources,
                consulted_sources=knowledge.consulted_sources or knowledge.sources,
                limitations=tuple(limitations + ["Correspondência fraca com a pergunta."]),
            )
        return FinalResult(
            answer=f"Com base exclusivamente nos trechos aprovados recuperados:\n{knowledge.answer}",
            status=ResponseStatus.ANSWERED,
            sources=knowledge.sources,
            consulted_sources=knowledge.consulted_sources or knowledge.sources,
            limitations=tuple(limitations),
        )
