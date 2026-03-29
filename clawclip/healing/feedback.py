"""Feedback store — learn which healing strategies work best per failure type."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from clawclip.healing.detector import FailureType
from clawclip.healing.strategies import RetryStrategy

logger = logging.getLogger(__name__)

_DATA_DIR = Path("data")


def _context_hash(context: dict[str, Any]) -> str:
    """Stable short hash of a context dict (for grouping similar failures)."""
    serialised = json.dumps(context, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode()).hexdigest()[:16]


@dataclass
class SuccessRecord:
    """Tracks how often a strategy succeeded for a given failure type."""

    failure_type: str
    strategy: str
    context_hash: str
    success_count: int = 0
    failure_count: int = 0

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SuccessRecord:
        return cls(**data)


class FeedbackStore:
    """Persists strategy success/failure counts to ``data/healing_feedback.json``.

    Allows :class:`~clawclip.healing.escalation.EscalationManager` to prefer
    historically successful strategies.
    """

    def __init__(self, path: Path | None = None) -> None:
        _DATA_DIR.mkdir(exist_ok=True)
        self._path = path or (_DATA_DIR / "healing_feedback.json")
        # Key: (failure_type, strategy, context_hash)
        self._records: dict[tuple[str, str, str], SuccessRecord] = {}
        self._load()

    # ── Persistence ──────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw: list[dict[str, Any]] = json.loads(
                self._path.read_text(encoding="utf-8")
            )
            for item in raw:
                rec = SuccessRecord.from_dict(item)
                key = (rec.failure_type, rec.strategy, rec.context_hash)
                self._records[key] = rec
            logger.debug("Loaded %d feedback records", len(self._records))
        except Exception as exc:
            logger.error("Failed to load feedback: %s", exc)

    def _save(self) -> None:
        try:
            data = [rec.to_dict() for rec in self._records.values()]
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to save feedback: %s", exc)

    def _get_or_create(
        self,
        failure_type: FailureType,
        strategy: RetryStrategy,
        context_hash: str,
    ) -> SuccessRecord:
        key = (failure_type.value, strategy.value, context_hash)
        if key not in self._records:
            self._records[key] = SuccessRecord(
                failure_type=failure_type.value,
                strategy=strategy.value,
                context_hash=context_hash,
            )
        return self._records[key]

    # ── Recording ────────────────────────────────────────────────

    async def record_success(
        self,
        failure_type: FailureType,
        strategy: RetryStrategy,
        context: dict[str, Any],
    ) -> None:
        h = _context_hash(context)
        rec = self._get_or_create(failure_type, strategy, h)
        rec.success_count += 1
        self._save()
        logger.debug("Recorded success: %s + %s", failure_type, strategy)

    async def record_failure(
        self,
        failure_type: FailureType,
        strategy: RetryStrategy,
        context: dict[str, Any],
    ) -> None:
        h = _context_hash(context)
        rec = self._get_or_create(failure_type, strategy, h)
        rec.failure_count += 1
        self._save()
        logger.debug("Recorded failure: %s + %s", failure_type, strategy)

    # ── Query ────────────────────────────────────────────────────

    async def get_best_strategy(
        self, failure_type: FailureType
    ) -> RetryStrategy | None:
        """Return the strategy with the highest success rate for *failure_type*.

        Returns None when there is no recorded data.
        """
        candidates = [
            rec
            for (ft, _s, _h), rec in self._records.items()
            if ft == failure_type.value and (rec.success_count + rec.failure_count) > 0
        ]
        if not candidates:
            return None
        best = max(candidates, key=lambda r: r.success_rate)
        try:
            return RetryStrategy(best.strategy)
        except ValueError:
            return None

    async def get_stats(self) -> list[dict[str, Any]]:
        """Return all records as a list of dicts (for dashboards / debug)."""
        return [
            {**rec.to_dict(), "success_rate": rec.success_rate}
            for rec in self._records.values()
        ]
