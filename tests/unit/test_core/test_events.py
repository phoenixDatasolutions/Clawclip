"""Unit tests for nexusai.core.events — EventBus publish/subscribe system."""

from __future__ import annotations

import asyncio

import pytest

from nexusai.core.events import (
    AgentTaskStarted,
    EventBus,
    MessageReceived,
    MessageSent,
)


# ── test_subscribe_and_publish ────────────────────────────────────────────────


async def test_subscribe_and_publish() -> None:
    """Subscribe to an event type, publish it, verify the handler was called."""
    bus = EventBus()
    received: list[MessageReceived] = []

    async def handler(event: MessageReceived) -> None:
        received.append(event)

    bus.subscribe(MessageReceived, handler)
    evt = MessageReceived(platform="telegram", text="hello")
    await bus.publish(evt)

    assert len(received) == 1
    assert received[0] is evt


# ── test_multiple_subscribers ─────────────────────────────────────────────────


async def test_multiple_subscribers() -> None:
    """Two handlers for the same event type — both must be called."""
    bus = EventBus()
    calls_a: list[MessageReceived] = []
    calls_b: list[MessageReceived] = []

    async def handler_a(event: MessageReceived) -> None:
        calls_a.append(event)

    async def handler_b(event: MessageReceived) -> None:
        calls_b.append(event)

    bus.subscribe(MessageReceived, handler_a)
    bus.subscribe(MessageReceived, handler_b)
    evt = MessageReceived(platform="slack", text="hi")
    await bus.publish(evt)

    assert len(calls_a) == 1
    assert len(calls_b) == 1


# ── test_different_event_types ────────────────────────────────────────────────


async def test_different_event_types() -> None:
    """Handler for MessageReceived must NOT fire when MessageSent is published."""
    bus = EventBus()
    received_msgs: list[MessageReceived] = []
    sent_msgs: list[MessageSent] = []

    async def on_received(event: MessageReceived) -> None:
        received_msgs.append(event)

    async def on_sent(event: MessageSent) -> None:
        sent_msgs.append(event)

    bus.subscribe(MessageReceived, on_received)
    bus.subscribe(MessageSent, on_sent)

    await bus.publish(MessageSent(platform="telegram", text="response"))

    assert len(received_msgs) == 0
    assert len(sent_msgs) == 1


# ── test_unsubscribe ──────────────────────────────────────────────────────────


async def test_unsubscribe() -> None:
    """After unsubscribing, the handler must not fire on subsequent publishes."""
    bus = EventBus()
    calls: list[MessageReceived] = []

    async def handler(event: MessageReceived) -> None:
        calls.append(event)

    bus.subscribe(MessageReceived, handler)
    await bus.publish(MessageReceived(text="first"))
    assert len(calls) == 1

    bus.unsubscribe(MessageReceived, handler)
    await bus.publish(MessageReceived(text="second"))
    assert len(calls) == 1  # still 1 — handler was not called again


# ── test_async_handler ────────────────────────────────────────────────────────


async def test_async_handler() -> None:
    """Async handlers that await internally are supported correctly."""
    bus = EventBus()
    results: list[str] = []

    async def slow_handler(event: MessageReceived) -> None:
        await asyncio.sleep(0)  # yields control
        results.append(event.text)

    bus.subscribe(MessageReceived, slow_handler)
    await bus.publish(MessageReceived(text="async-works"))

    assert results == ["async-works"]


# ── test_event_history ────────────────────────────────────────────────────────


async def test_event_history() -> None:
    """Published events are stored in the bus history."""
    bus = EventBus()
    evt1 = MessageReceived(text="one")
    evt2 = MessageSent(text="two")
    await bus.publish(evt1)
    await bus.publish(evt2)

    history = bus.recent_events()
    # recent_events returns newest first
    assert evt2 in history
    assert evt1 in history


# ── test_event_history_filtered ──────────────────────────────────────────────


async def test_event_history_filtered() -> None:
    """recent_events(event_type=...) only returns events of the given type."""
    bus = EventBus()
    await bus.publish(MessageReceived(text="msg"))
    await bus.publish(MessageSent(text="sent"))
    await bus.publish(MessageReceived(text="msg2"))

    received_only = bus.recent_events(MessageReceived)
    assert all(isinstance(e, MessageReceived) for e in received_only)
    assert len(received_only) == 2


# ── test_publish_no_subscribers ──────────────────────────────────────────────


async def test_publish_no_subscribers() -> None:
    """Publishing to an event type with no subscribers must not raise."""
    bus = EventBus()
    # Should complete without exception
    await bus.publish(AgentTaskStarted(agent_id="x", task_id="y"))


# ── test_priority_ordering ────────────────────────────────────────────────────


async def test_priority_ordering() -> None:
    """Higher-priority handlers fire before lower-priority ones."""
    bus = EventBus()
    order: list[str] = []

    async def low_handler(event: MessageReceived) -> None:
        order.append("low")

    async def high_handler(event: MessageReceived) -> None:
        order.append("high")

    bus.subscribe(MessageReceived, low_handler, priority=10)
    bus.subscribe(MessageReceived, high_handler, priority=90)

    await bus.publish(MessageReceived(text="prioritize"))

    # Both handlers run; high_handler was registered first in the sorted list
    assert "high" in order
    assert "low" in order
    assert order.index("high") < order.index("low")


# ── test_history_limit ────────────────────────────────────────────────────────


async def test_history_limit() -> None:
    """History is capped at the configured limit."""
    bus = EventBus(history_limit=3)
    for i in range(5):
        await bus.publish(MessageReceived(text=str(i)))

    history = bus.recent_events(limit=100)
    assert len(history) <= 3


# ── test_handler_exception_doesnt_crash_bus ───────────────────────────────────


async def test_handler_exception_doesnt_crash_bus() -> None:
    """A handler that raises must not prevent other handlers from running."""
    bus = EventBus()
    results: list[str] = []

    async def bad_handler(event: MessageReceived) -> None:
        raise RuntimeError("intentional failure")

    async def good_handler(event: MessageReceived) -> None:
        results.append("ok")

    bus.subscribe(MessageReceived, bad_handler, priority=90)
    bus.subscribe(MessageReceived, good_handler, priority=10)

    await bus.publish(MessageReceived(text="resilient"))

    assert results == ["ok"]
