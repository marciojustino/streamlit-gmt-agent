from __future__ import annotations

import re

from .contracts import ResponseStatus
from .privacy import redact_personal_data


_FINANCIAL_ADVICE = re.compile(
    r"\b(recomende|recomendação|recomendacao|onde devo investir|"
    r"qual investimento devo|em que devo investir|invista meu dinheiro|"
    r"aplique meu dinheiro)\b",
    re.IGNORECASE,
)
_UNAUTHORIZED_ACTION = re.compile(
    r"\b(faça|faca|execute|realize|transfira|movimente|altere|modifique|"
    r"aprove|negue)\b.{0,60}\b(conta|valor|dinheiro|ordem|limite|crédito|credito|"
    r"investimento|resgate|cadastro)\b|"
    r"\b(resgate|transfira|aplique|compre|venda)\b.{0,30}\b(para mim|meu|minha)\b",
    re.IGNORECASE,
)
_INTERNAL_PROMPT_REQUEST = re.compile(
    r"\b(prompt|instruções internas|instrucoes internas|system prompt|"
    r"segredo|credencial|token)\b.{0,60}\b(revele|mostre|exiba|copie|imprima|"
    r"liste|informe|dump)\b|"
    r"\b(revele|mostre|exiba|copie|imprima)\b.{0,60}\b(prompt|instruções internas|"
    r"instrucoes internas|system prompt|segredo|credencial|token)\b",
    re.IGNORECASE,
)
_REGULATORY_OR_TAX = re.compile(
    r"\b(regulat\w*|tribut\w*|impost\w*|compliance|conformidade)\b",
    re.IGNORECASE,
)


def classify_question(question: str) -> tuple[ResponseStatus, str] | None:
    if _INTERNAL_PROMPT_REQUEST.search(question):
        return ResponseStatus.BLOCKED, "Solicitação de informação interna ou protegida."
    if _FINANCIAL_ADVICE.search(question):
        return (
            ResponseStatus.BLOCKED,
            "Aconselhamento financeiro individualizado está fora do escopo.",
        )
    if _UNAUTHORIZED_ACTION.search(question):
        return ResponseStatus.BLOCKED, "A aplicação não executa ações financeiras ou administrativas."
    if _REGULATORY_OR_TAX.search(question):
        return (
            ResponseStatus.NEEDS_HUMAN_REVIEW,
            "Questões regulatórias ou tributárias exigem validação humana e contexto confirmado.",
        )
    return None


def sanitize_question(question: str) -> tuple[str, bool]:
    return redact_personal_data(question)
