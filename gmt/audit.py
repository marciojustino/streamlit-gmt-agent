from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .contracts import AuditRecord


class AuditWriteError(OSError):
    pass


class JsonlAuditLogger:
    def __init__(self, path: Path, retention_days: int | None):
        self.path = path
        self.retention_days = retention_days
        self._lock = threading.Lock()

    def write(self, record: AuditRecord) -> None:
        if self.retention_days is None:
            raise AuditWriteError("A retenção institucional dos logs não está configurada.")
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._prune_expired()
                with self.path.open("a", encoding="utf-8") as audit_file:
                    audit_file.write(
                        json.dumps(
                            _serialize(record),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise AuditWriteError("Não foi possível gravar o registro de auditoria.") from exc

    def _prune_expired(self) -> None:
        if not self.path.exists():
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days or 0)
        retained: list[str] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            timestamp = datetime.fromisoformat(event["timestamp"])
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            if timestamp >= cutoff:
                retained.append(line)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                if retained:
                    temporary_file.write("\n".join(retained) + "\n")
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


def _serialize(record: AuditRecord) -> dict[str, object]:
    return {
        "session_id": record.session_id,
        "audit_id": record.audit_id,
        "agent_version": record.agent_version,
        "timestamp": record.timestamp,
        "duration_ms": record.duration_ms,
        "status": record.status,
        "agents": [{"name": agent.name, "status": agent.status} for agent in record.agents],
        "sources": list(record.sources),
        "limitations": list(record.limitations),
        "failure_code": record.failure_code,
        "human_approvals": list(record.human_approvals),
    }
