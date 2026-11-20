from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass

from .contracts import MemoryResult, MemoryStatus


@dataclass(frozen=True)
class MemoryTurn:
    turn_id: str
    question: str
    created_at: float


class MemoryAgent:
    name = "gmt_memory"

    def __init__(self, ttl_seconds: int, max_turns: int):
        self.ttl_seconds = ttl_seconds
        self.max_turns = max_turns
        self._sessions: dict[str, tuple[str, deque[MemoryTurn]]] = {}

    def read(self, session_id: str, user_id: str) -> MemoryResult:
        entry = self._sessions.get(session_id)
        if entry is None:
            self._purge_expired()
            return MemoryResult(context_summary="", status=MemoryStatus.EMPTY)

        owner, turns = entry
        if owner != user_id:
            self._purge_expired()
            return MemoryResult(context_summary="", status=MemoryStatus.BLOCKED)
        if turns and time.time() - turns[-1].created_at > self.ttl_seconds:
            del self._sessions[session_id]
            self._purge_expired()
            return MemoryResult(context_summary="", status=MemoryStatus.EXPIRED)

        self._purge_expired()
        return MemoryResult(
            context_summary="\n".join(turn.question for turn in turns),
            referenced_turn_ids=tuple(turn.turn_id for turn in turns),
            status=MemoryStatus.AVAILABLE if turns else MemoryStatus.EMPTY,
        )

    def remember(self, session_id: str, user_id: str, sanitized_question: str) -> MemoryResult:
        self._purge_expired()
        entry = self._sessions.get(session_id)
        if entry is not None and entry[0] != user_id:
            return MemoryResult(context_summary="", status=MemoryStatus.BLOCKED)
        turns = entry[1] if entry is not None else deque(maxlen=self.max_turns)
        turns.append(
            MemoryTurn(
                turn_id=str(uuid.uuid4()),
                question=sanitized_question,
                created_at=time.time(),
            )
        )
        self._sessions[session_id] = (user_id, turns)
        return self.read(session_id, user_id)

    def _purge_expired(self) -> None:
        now = time.time()
        expired = [
            session_id
            for session_id, (_, turns) in self._sessions.items()
            if turns and now - turns[-1].created_at > self.ttl_seconds
        ]
        for session_id in expired:
            del self._sessions[session_id]
