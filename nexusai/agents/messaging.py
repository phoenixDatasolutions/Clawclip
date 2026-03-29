"""Agent Message Bus — inter-agent communication via priority asyncio queues."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Sentinel to mark a queue slot as priority-ordered; we use (neg_priority, seq, msg)
# tuples so asyncio.PriorityQueue works with higher-priority = lower tuple value.


class AgentMessageBus:
    """Singleton message bus for inter-agent communication.

    Each registered agent gets its own asyncio.PriorityQueue.  Messages are
    delivered as plain dicts and include the sender's agent_id under the
    reserved key ``"_from"``.  Higher ``priority`` values are delivered first.
    """

    _instance: AgentMessageBus | None = None

    def __init__(self) -> None:
        # agent_id -> PriorityQueue of (-priority, seq, message)
        self._queues: dict[str, asyncio.PriorityQueue[tuple[int, int, dict[str, Any]]]] = {}
        self._seq: int = 0  # monotonic sequence number used to break priority ties (FIFO)
        self._lock = asyncio.Lock()

    # ── Singleton ────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> AgentMessageBus:
        """Return the process-wide singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton (useful for tests)."""
        cls._instance = None

    # ── Registration ─────────────────────────────────────────────

    async def register(self, agent_id: str) -> None:
        """Create a message queue for *agent_id*.

        Idempotent — calling again for an already-registered agent is a no-op.
        """
        async with self._lock:
            if agent_id not in self._queues:
                self._queues[agent_id] = asyncio.PriorityQueue()
                logger.debug("AgentMessageBus: registered agent %s", agent_id)

    async def unregister(self, agent_id: str) -> None:
        """Remove *agent_id* and discard any pending messages."""
        async with self._lock:
            self._queues.pop(agent_id, None)
            logger.debug("AgentMessageBus: unregistered agent %s", agent_id)

    # ── Messaging ────────────────────────────────────────────────

    async def send(
        self,
        from_agent_id: str,
        to_agent_id: str,
        message: dict[str, Any],
        priority: int = 0,
    ) -> None:
        """Send a message from one agent to another.

        The message dict is shallow-copied and a ``"_from"`` key is injected so
        the receiver knows who sent it.

        Args:
            from_agent_id: Sender's agent ID.
            to_agent_id: Recipient's agent ID.
            message: Arbitrary payload dict.
            priority: Higher numbers are delivered first (default 0).

        Raises:
            KeyError: If *to_agent_id* has not been registered.
        """
        queue = self._queues.get(to_agent_id)
        if queue is None:
            raise KeyError(
                f"Agent '{to_agent_id}' is not registered on the message bus."
            )

        async with self._lock:
            self._seq += 1
            seq = self._seq

        envelope: dict[str, Any] = {**message, "_from": from_agent_id}
        # PriorityQueue is a min-heap; negate priority so higher values come first.
        await queue.put((-priority, seq, envelope))
        logger.debug(
            "AgentMessageBus: %s -> %s (priority=%d)", from_agent_id, to_agent_id, priority
        )

    async def receive(self, agent_id: str) -> dict[str, Any]:
        """Block until a message is available in *agent_id*'s queue and return it.

        Args:
            agent_id: The receiving agent's ID.

        Returns:
            The next message dict (highest priority, then FIFO).

        Raises:
            KeyError: If *agent_id* has not been registered.
        """
        queue = self._queues.get(agent_id)
        if queue is None:
            raise KeyError(
                f"Agent '{agent_id}' is not registered on the message bus."
            )

        _neg_priority, _seq, envelope = await queue.get()
        queue.task_done()
        logger.debug("AgentMessageBus: %s received message from %s", agent_id, envelope.get("_from"))
        return envelope

    async def broadcast(
        self,
        from_agent_id: str,
        message: dict[str, Any],
        priority: int = 0,
    ) -> None:
        """Send *message* to every registered agent except *from_agent_id*.

        Args:
            from_agent_id: Sender's agent ID (excluded from recipients).
            message: Arbitrary payload dict.
            priority: Delivery priority for all recipients (default 0).
        """
        recipients = [aid for aid in self._queues if aid != from_agent_id]
        if not recipients:
            logger.debug("AgentMessageBus: broadcast from %s — no other agents", from_agent_id)
            return

        await asyncio.gather(
            *(self.send(from_agent_id, aid, message, priority=priority) for aid in recipients)
        )
        logger.debug(
            "AgentMessageBus: %s broadcast to %d agents", from_agent_id, len(recipients)
        )

    # ── Introspection ────────────────────────────────────────────

    @property
    def registered_agents(self) -> list[str]:
        """Return a snapshot of all currently registered agent IDs."""
        return list(self._queues.keys())

    def pending_count(self, agent_id: str) -> int:
        """Return the number of messages waiting in *agent_id*'s queue."""
        queue = self._queues.get(agent_id)
        return queue.qsize() if queue is not None else 0
