from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import yaml
from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError

from .contracts import Confidence, KnowledgeResult, SourceReference


class KnowledgeBaseError(RuntimeError):
    pass


_SUPPORTED = {".md", ".txt", ".yaml", ".yml", ".pdf", ".docx", ".xlsx"}
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")
_INJECTION = re.compile(
    r"(ignore (all |any )?(previous|prior) instructions|ignore as instruções|"
    r"ignore as instrucoes|reveal (the )?(system )?prompt|revele o prompt|"
    r"envie (as )?(credenciais|senhas|tokens)|exfiltrate|bypass (the )?policy)",
    re.IGNORECASE,
)
_NEGATIONS = {"não", "nao", "nunca", "sem", "impossível", "impossivel"}
_STOP_WORDS = {
    "a", "ao", "aos", "as", "com", "como", "da", "das", "de", "do", "dos",
    "e", "em", "é", "essa", "esse", "esta", "este", "eu", "me", "minha",
    "meu", "na", "nas", "no", "nos", "o", "os", "para", "por", "qual",
    "quais", "que", "se", "sobre", "um", "uma", "voce", "você",
}


@dataclass(frozen=True)
class KnowledgeDocument:
    document_id: str
    version: str
    updated_at: date
    valid_until: date
    approval_reference: str
    content: str
    path: Path


class KnowledgeBase:
    def __init__(self, root: Path, max_document_bytes: int, max_excerpt_chars: int):
        self.root = root.resolve()
        self.max_document_bytes = max_document_bytes
        self.max_excerpt_chars = max_excerpt_chars

    def answer(self, question: str, top_k: int) -> KnowledgeResult:
        documents, limitations = self._load_documents()
        question_tokens = _tokens(question)
        if not question_tokens:
            return KnowledgeResult(
                answer="",
                missing_context=("A pergunta não contém termos suficientes para recuperar evidências.",),
                limitations=tuple(limitations),
            )

        current_hits: list[tuple[float, KnowledgeDocument, str]] = []
        stale_hits: list[tuple[float, KnowledgeDocument, str]] = []
        injection_detected = False
        for document in documents:
            best_sentence, score, document_injection = self._best_sentence(
                document.content, question_tokens
            )
            injection_detected = injection_detected or document_injection
            if not best_sentence or score <= 0:
                continue
            if document.valid_until < date.today():
                stale_hits.append((score, document, best_sentence))
                continue
            current_hits.append((score, document, best_sentence))

        current_hits.sort(key=lambda hit: (hit[0], hit[1].updated_at), reverse=True)
        selected = current_hits[:top_k]
        stale_hits.sort(key=lambda hit: (hit[0], hit[1].updated_at), reverse=True)
        stale_selected = stale_hits[:top_k]
        stale_ids = tuple(sorted({document.document_id for _, document, _ in stale_selected}))
        if stale_selected:
            limitations.append("Há fonte aprovada relacionada cuja validade expirou; revisão humana necessária.")

        conflicts = _find_conflicts(selected)
        sources = tuple(
            SourceReference(
                document_id=document.document_id,
                version=document.version,
                updated_at=document.updated_at.isoformat(),
                excerpt=excerpt[: self.max_excerpt_chars],
                approval_reference=document.approval_reference,
            )
            for _, document, excerpt in selected
        )
        stale_references = tuple(
            SourceReference(
                document_id=document.document_id,
                version=document.version,
                updated_at=document.updated_at.isoformat(),
                excerpt="",
                approval_reference=document.approval_reference,
            )
            for _, document, _ in stale_selected
        )
        coverage = selected[0][0] if selected else 0.0
        if coverage >= 0.6:
            confidence = Confidence.HIGH
        elif coverage >= 0.45:
            confidence = Confidence.MEDIUM
        else:
            confidence = Confidence.LOW

        if conflicts or stale_ids:
            answer = ""
        elif sources:
            answer = "\n".join(f"- {source.excerpt}" for source in sources)
        else:
            answer = ""

        missing_context = () if sources and not stale_ids else (
            "Não há evidência atual, aprovada e suficiente para responder.",
        )
        return KnowledgeResult(
            answer=answer,
            sources=sources,
            consulted_sources=sources + stale_references,
            confidence=confidence,
            missing_context=missing_context,
            contradictions=tuple(conflicts),
            stale_sources=stale_ids,
            limitations=tuple(limitations),
            injection_detected=injection_detected,
        )

    def _load_documents(self) -> tuple[list[KnowledgeDocument], list[str]]:
        if not self.root.is_dir():
            return [], ["A base de conhecimento local não está disponível."]

        documents: list[KnowledgeDocument] = []
        limitations: list[str] = []
        try:
            candidates = sorted(path for path in self.root.rglob("*") if path.is_file())
            for path in candidates:
                if path.suffix.casefold() not in _SUPPORTED or path.name.casefold().endswith(".meta.yaml"):
                    continue
                resolved = path.resolve()
                try:
                    resolved.relative_to(self.root)
                except ValueError as exc:
                    raise KnowledgeBaseError("A base contém um caminho fora do diretório autorizado.") from exc

                if resolved.stat().st_size > self.max_document_bytes:
                    limitations.append("Um arquivo excede o limite de tamanho e foi ignorado.")
                    continue

                metadata, content = self._read_document(resolved)
                if metadata is None:
                    limitations.append("Um arquivo sem metadados de aprovação foi ignorado.")
                    continue
                if metadata.get("status") != "approved":
                    limitations.append("Um arquivo não aprovado foi ignorado.")
                    continue

                required = (
                    "id",
                    "version",
                    "updated_at",
                    "valid_until",
                    "approval_reference",
                    "approved_by",
                )
                if any(not isinstance(metadata.get(key), str) or not metadata[key].strip() for key in required):
                    limitations.append("Um arquivo aprovado sem metadados completos foi ignorado.")
                    continue
                try:
                    updated_at = date.fromisoformat(metadata["updated_at"])
                    valid_until = date.fromisoformat(metadata["valid_until"])
                except ValueError:
                    limitations.append("Um arquivo com datas inválidas foi ignorado.")
                    continue
                if updated_at > date.today():
                    limitations.append("Um arquivo com data futura foi ignorado.")
                    continue

                if not content.strip():
                    continue
                documents.append(
                    KnowledgeDocument(
                        document_id=metadata["id"].strip(),
                        version=metadata["version"].strip(),
                        updated_at=updated_at,
                        valid_until=valid_until,
                        approval_reference=metadata["approval_reference"].strip(),
                        content=content,
                        path=resolved,
                    )
                )
        except (OSError, UnicodeDecodeError, yaml.YAMLError, zipfile.BadZipFile) as exc:
            raise KnowledgeBaseError("Não foi possível ler com segurança a base de conhecimento.") from exc
        except (ValueError, KeyError, TypeError, ElementTree.ParseError) as exc:
            raise KnowledgeBaseError("Um documento da base possui estrutura inválida.") from exc

        return documents, limitations

    def _read_document(self, path: Path) -> tuple[dict[str, Any] | None, str]:
        suffix = path.suffix.casefold()
        if suffix == ".md":
            text = path.read_text(encoding="utf-8")
            metadata, content = _markdown_frontmatter(text)
            return metadata, content

        if suffix in {".yaml", ".yml"}:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return None, ""
            content = raw.get("content")
            return raw, content if isinstance(content, str) else ""

        metadata_path = path.with_suffix(path.suffix + ".meta.yaml")
        if not metadata_path.is_file():
            return None, ""
        if metadata_path.stat().st_size > self.max_document_bytes:
            return None, ""
        metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            return None, ""
        if metadata.get("status") != "approved":
            return metadata, ""

        try:
            if suffix == ".txt":
                content = path.read_text(encoding="utf-8")
            elif suffix == ".pdf":
                reader = PdfReader(str(path))
                if reader.is_encrypted:
                    raise KnowledgeBaseError("Documento PDF criptografado não pode ser processado.")
                content = "\n".join(page.extract_text() or "" for page in reader.pages)
            elif suffix == ".docx":
                document = Document(str(path))
                content = "\n".join(paragraph.text for paragraph in document.paragraphs)
                content += "\n" + "\n".join(
                    " ".join(cell.text for cell in row.cells)
                    for table in document.tables
                    for row in table.rows
                )
            elif suffix == ".xlsx":
                workbook = load_workbook(path, read_only=True, data_only=True)
                try:
                    content = "\n".join(
                        " ".join(str(value) for value in row if value is not None)
                        for sheet in workbook.worksheets
                        for row in sheet.iter_rows(values_only=True)
                    )
                finally:
                    workbook.close()
            else:
                return None, ""
        except (
            FileNotDecryptedError,
            InvalidFileException,
            PackageNotFoundError,
            PdfReadError,
            zipfile.BadZipFile,
        ) as exc:
            raise KnowledgeBaseError("Um documento não pôde ser processado com segurança.") from exc
        return metadata, content

    def _best_sentence(
        self, content: str, query_tokens: set[str]
    ) -> tuple[str, float, bool]:
        best_sentence = ""
        best_score = 0.0
        injection_detected = False
        for sentence in _SENTENCE_BOUNDARY.split(content):
            sentence = " ".join(sentence.split())
            if not sentence:
                continue
            if _INJECTION.search(sentence):
                injection_detected = True
                continue
            sentence_tokens = _tokens(sentence)
            score = len(query_tokens & sentence_tokens) / len(query_tokens)
            if score > best_score:
                best_sentence = sentence
                best_score = score
        return best_sentence, best_score, injection_detected


def _markdown_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    if not text.startswith("---\n"):
        return None, ""
    end = text.find("\n---", 4)
    if end < 0:
        return None, ""
    metadata = yaml.safe_load(text[4:end])
    if not isinstance(metadata, dict):
        return None, ""
    return metadata, text[end + 4 :].strip()


def _tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in _WORD.findall(text)
        if len(token) > 1 and token.casefold() not in _STOP_WORDS
    }


def _find_conflicts(hits: list[tuple[float, KnowledgeDocument, str]]) -> list[str]:
    conflicts: list[str] = []
    for index, (_, first_document, first_excerpt) in enumerate(hits):
        first_tokens = _tokens(first_excerpt)
        first_base = first_tokens - _NEGATIONS
        first_negated = bool(first_tokens & _NEGATIONS)
        for _, second_document, second_excerpt in hits[index + 1 :]:
            second_tokens = _tokens(second_excerpt)
            second_base = second_tokens - _NEGATIONS
            second_negated = bool(second_tokens & _NEGATIONS)
            union = first_base | second_base
            similarity = len(first_base & second_base) / len(union) if union else 0.0
            if similarity >= 0.8 and first_negated != second_negated:
                conflicts.extend((first_document.document_id, second_document.document_id))
    return sorted(set(conflicts))
