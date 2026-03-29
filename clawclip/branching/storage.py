"""Branch tree persistence — JSON file-backed storage for conversation branches."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

_DATA_DIR = Path("data")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid4())


@dataclass
class ConversationBranch:
    """A forked branch of a conversation."""

    id: str = field(default_factory=_uuid)
    parent_id: str | None = None
    conversation_id: str = ""
    name: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    forked_at_message_id: str | None = None

    # ── Serialisation ────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationBranch:
        data = dict(data)
        created_raw = data.get("created_at")
        if isinstance(created_raw, str):
            data["created_at"] = datetime.fromisoformat(created_raw)
        return cls(**data)


class BranchStore:
    """JSON file-backed store for ConversationBranch records.

    All records are persisted to ``data/branches.json``.
    """

    def __init__(self, path: Path | None = None) -> None:
        _DATA_DIR.mkdir(exist_ok=True)
        self._path = path or (_DATA_DIR / "branches.json")
        self._branches: dict[str, ConversationBranch] = {}
        self._load()

    # ── Persistence ──────────────────────────────────────────────

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw: list[dict[str, Any]] = json.loads(self._path.read_text(encoding="utf-8"))
                self._branches = {item["id"]: ConversationBranch.from_dict(item) for item in raw}
                logger.debug("Loaded %d branches from %s", len(self._branches), self._path)
            except Exception as exc:
                logger.error("Failed to load branches: %s", exc)

    def _save(self) -> None:
        try:
            data = [b.to_dict() for b in self._branches.values()]
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to save branches: %s", exc)

    # ── CRUD ─────────────────────────────────────────────────────

    async def create_branch(
        self,
        conv_id: str,
        parent_id: str | None,
        name: str,
        forked_at: str | None = None,
    ) -> ConversationBranch:
        branch = ConversationBranch(
            conversation_id=conv_id,
            parent_id=parent_id,
            name=name,
            forked_at_message_id=forked_at,
        )
        self._branches[branch.id] = branch
        self._save()
        logger.info("Created branch '%s' (%s) for conv %s", name, branch.id[:8], conv_id)
        return branch

    async def list_branches(self, conv_id: str) -> list[ConversationBranch]:
        return [b for b in self._branches.values() if b.conversation_id == conv_id]

    async def get_branch(self, branch_id: str) -> ConversationBranch | None:
        return self._branches.get(branch_id)

    async def delete_branch(self, branch_id: str) -> None:
        if branch_id in self._branches:
            del self._branches[branch_id]
            self._save()
            logger.info("Deleted branch %s", branch_id[:8])
