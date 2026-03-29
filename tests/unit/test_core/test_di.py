"""Unit tests for clawclip.core.di — DI Container."""

from __future__ import annotations

import pytest

from clawclip.core.di import Container


# ── test_register_and_resolve ─────────────────────────────────────────────────


def test_register_and_resolve() -> None:
    """A registered singleton instance is returned by resolve()."""
    container = Container()
    container.register("my_value", 42)

    assert container.resolve("my_value") == 42


# ── test_resolve_typed ────────────────────────────────────────────────────────


def test_resolve_typed() -> None:
    """resolve_typed() returns the value when the type matches."""
    container = Container()
    container.register("msg", "hello")

    result = container.resolve_typed("msg", str)
    assert result == "hello"


# ── test_resolve_typed_wrong_type_raises ──────────────────────────────────────


def test_resolve_typed_wrong_type_raises() -> None:
    """resolve_typed() raises TypeError when the registered value has the wrong type."""
    container = Container()
    container.register("num", 123)

    with pytest.raises(TypeError, match="num"):
        container.resolve_typed("num", str)


# ── test_register_factory ─────────────────────────────────────────────────────


def test_register_factory() -> None:
    """A factory callable is called lazily on first resolve()."""
    container = Container()
    calls = []

    def factory() -> list:
        calls.append(1)
        return [1, 2, 3]

    container.register_factory("items", factory)
    assert calls == []  # not called yet

    result = container.resolve("items")
    assert result == [1, 2, 3]
    assert calls == [1]  # called exactly once


# ── test_singleton_factory ────────────────────────────────────────────────────


def test_singleton_factory() -> None:
    """Factory is called only once; subsequent resolves return the cached instance."""
    container = Container()
    calls = []

    def factory() -> dict:
        calls.append(1)
        return {"created": True}

    container.register_factory("singleton", factory)

    first = container.resolve("singleton")
    second = container.resolve("singleton")

    assert first is second
    assert len(calls) == 1  # factory called exactly once


# ── test_resolve_missing_raises ───────────────────────────────────────────────


def test_resolve_missing_raises() -> None:
    """resolve() raises KeyError when the key is not registered."""
    container = Container()
    with pytest.raises(KeyError, match="ghost"):
        container.resolve("ghost")


# ── test_has ─────────────────────────────────────────────────────────────────


def test_has() -> None:
    """has() returns True for both direct registrations and registered factories."""
    container = Container()
    container.register("inst", object())
    container.register_factory("fact", lambda: None)

    assert container.has("inst") is True
    assert container.has("fact") is True
    assert container.has("unknown") is False


# ── test_contains_dunder ──────────────────────────────────────────────────────


def test_contains_dunder() -> None:
    """The __contains__ dunder supports the 'in' operator."""
    container = Container()
    container.register("x", 1)

    assert "x" in container
    assert "y" not in container


# ── test_keys ────────────────────────────────────────────────────────────────


def test_keys() -> None:
    """keys() returns all registered instance and factory keys (sorted)."""
    container = Container()
    container.register("b", 2)
    container.register("a", 1)
    container.register_factory("c", lambda: 3)

    assert container.keys() == ["a", "b", "c"]


# ── test_factory_key_removed_after_resolve ────────────────────────────────────


def test_factory_key_removed_after_resolve() -> None:
    """After a factory is resolved, the factory dict entry is removed (replaced by instance)."""
    container = Container()
    container.register_factory("item", lambda: "built")

    # Before resolve — factory registered, no instance yet
    assert container.has("item")

    container.resolve("item")

    # After resolve — still accessible as a cached instance
    assert container.resolve("item") == "built"
