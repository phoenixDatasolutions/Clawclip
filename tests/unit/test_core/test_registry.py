"""Unit tests for nexusai.core.registry — typed Registry."""

from __future__ import annotations

import pytest

from nexusai.core.registry import Registry


# ── test_register_and_get ─────────────────────────────────────────────────────


def test_register_and_get() -> None:
    """Registered object is retrievable by the same name."""
    reg: Registry[str] = Registry("test")
    reg.register("alpha", "value-a")

    assert reg.get("alpha") == "value-a"


# ── test_get_missing_returns_none ─────────────────────────────────────────────


def test_get_missing_returns_none() -> None:
    """get() returns None for unknown keys (no exception)."""
    reg: Registry[int] = Registry("numbers")
    assert reg.get("nope") is None


# ── test_require_missing_raises ───────────────────────────────────────────────


def test_require_missing_raises() -> None:
    """require() raises KeyError when the key is not registered."""
    reg: Registry[str] = Registry("things")
    with pytest.raises(KeyError, match="things"):
        reg.require("missing")


# ── test_require_returns_value ────────────────────────────────────────────────


def test_require_returns_value() -> None:
    """require() returns the registered value when present."""
    reg: Registry[int] = Registry("nums")
    reg.register("pi", 3)
    assert reg.require("pi") == 3


# ── test_list_all ─────────────────────────────────────────────────────────────


def test_list_all() -> None:
    """list_all() returns a dict with all registered items."""
    reg: Registry[str] = Registry("stuff")
    reg.register("a", "A")
    reg.register("b", "B")

    all_items = reg.list_all()
    assert all_items == {"a": "A", "b": "B"}


# ── test_has ──────────────────────────────────────────────────────────────────


def test_has() -> None:
    """has() correctly reports presence and absence of keys."""
    reg: Registry[str] = Registry("check")
    reg.register("exists", "yes")

    assert reg.has("exists") is True
    assert reg.has("nope") is False


# ── test_overwrite_registration ───────────────────────────────────────────────


def test_overwrite_registration() -> None:
    """Re-registering an existing key overwrites the old value (with a warning)."""
    reg: Registry[int] = Registry("vals")
    reg.register("x", 1)
    reg.register("x", 2)  # overwrite — must not raise

    assert reg.get("x") == 2


# ── test_names ────────────────────────────────────────────────────────────────


def test_names() -> None:
    """names() returns all registered keys as a list."""
    reg: Registry[str] = Registry("keys")
    reg.register("foo", "f")
    reg.register("bar", "b")

    assert set(reg.names()) == {"foo", "bar"}


# ── test_remove ───────────────────────────────────────────────────────────────


def test_remove() -> None:
    """remove() deletes the entry and returns it; get() is None afterwards."""
    reg: Registry[str] = Registry("rm")
    reg.register("item", "value")
    removed = reg.remove("item")

    assert removed == "value"
    assert reg.get("item") is None


# ── test_contains ─────────────────────────────────────────────────────────────


def test_contains() -> None:
    """The __contains__ dunder supports the 'in' operator."""
    reg: Registry[str] = Registry("c")
    reg.register("here", "x")

    assert "here" in reg
    assert "not_here" not in reg


# ── test_len ──────────────────────────────────────────────────────────────────


def test_len() -> None:
    """len() returns the number of registered items."""
    reg: Registry[int] = Registry("len")
    assert len(reg) == 0
    reg.register("a", 1)
    reg.register("b", 2)
    assert len(reg) == 2


# ── test_clear ────────────────────────────────────────────────────────────────


def test_clear() -> None:
    """clear() removes all items from the registry."""
    reg: Registry[str] = Registry("clr")
    reg.register("x", "val")
    reg.clear()

    assert len(reg) == 0
    assert reg.get("x") is None
