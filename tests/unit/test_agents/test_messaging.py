"""Unit tests for clawclip.agents.messaging — AgentMessageBus."""

from __future__ import annotations

import asyncio

import pytest

from clawclip.agents.messaging import AgentMessageBus


@pytest.fixture(autouse=True)
def reset_singleton() -> None:
    """Ensure a fresh singleton for every test."""
    AgentMessageBus.reset_instance()
    yield
    AgentMessageBus.reset_instance()


@pytest.mark.unit
class TestAgentMessageBus:

    async def test_register_and_receive(self) -> None:
        """Registered agent can receive a message sent to it."""
        bus = AgentMessageBus()
        await bus.register("agent-1")
        await bus.send("sender", "agent-1", {"text": "hello"})

        msg = await bus.receive("agent-1")
        assert msg["text"] == "hello"
        assert msg["_from"] == "sender"

    async def test_broadcast_reaches_all(self) -> None:
        """Broadcast delivers a copy to every registered agent except sender."""
        bus = AgentMessageBus()
        for aid in ("a1", "a2", "a3", "sender"):
            await bus.register(aid)

        await bus.broadcast("sender", {"event": "ping"})

        for aid in ("a1", "a2", "a3"):
            msg = await bus.receive(aid)
            assert msg["event"] == "ping"
            assert msg["_from"] == "sender"

    async def test_unregister_no_receive(self) -> None:
        """Sending to an unregistered agent raises KeyError (not silently dropped)."""
        bus = AgentMessageBus()
        await bus.register("agent-x")
        await bus.unregister("agent-x")

        with pytest.raises(KeyError):
            await bus.send("s", "agent-x", {"text": "oops"})

    async def test_priority_ordering(self) -> None:
        """Higher priority messages are received before lower priority ones."""
        bus = AgentMessageBus()
        await bus.register("agent-p")

        await bus.send("s", "agent-p", {"order": "low"}, priority=0)
        await bus.send("s", "agent-p", {"order": "high"}, priority=10)

        first = await bus.receive("agent-p")
        second = await bus.receive("agent-p")

        assert first["order"] == "high"
        assert second["order"] == "low"

    async def test_singleton(self) -> None:
        """get_instance() returns the same object on repeated calls."""
        bus_a = AgentMessageBus.get_instance()
        bus_b = AgentMessageBus.get_instance()
        assert bus_a is bus_b

    async def test_send_to_unknown_drops(self) -> None:
        """Sending to an unregistered agent raises KeyError — no silent swallow."""
        bus = AgentMessageBus()
        with pytest.raises(KeyError):
            await bus.send("s", "does-not-exist", {"x": 1})
