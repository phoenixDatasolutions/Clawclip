"""Unit tests for SystemMonitorSkill (psutil mocked)."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from clawclip.skills.builtin.monitor import SystemMonitorSkill
from clawclip.core.types import SkillContext

pytestmark = pytest.mark.unit


def _make_psutil_mock() -> MagicMock:
    """Build a minimal psutil mock covering every code-path in SystemMonitorSkill."""
    mock = MagicMock(name="psutil")

    # cpu_percent / cpu_count
    mock.cpu_percent.return_value = 15.3
    mock.cpu_count.return_value = 8

    # virtual_memory
    mem = SimpleNamespace(used=4 * 1024**3, total=16 * 1024**3, percent=25.0)
    mock.virtual_memory.return_value = mem

    # boot_time  (Unix epoch, way in the past so uptime is always positive)
    mock.boot_time.return_value = 1_700_000_000.0

    # process_iter
    proc_info = {
        "pid": 1234,
        "name": "python",
        "cpu_percent": 5.0,
        "memory_info": SimpleNamespace(rss=50 * 1024**2),
        "status": "running",
    }
    fake_proc = MagicMock()
    fake_proc.info = proc_info
    mock.process_iter.return_value = [fake_proc]
    mock.NoSuchProcess = Exception
    mock.AccessDenied = Exception

    # disk_partitions
    part = SimpleNamespace(mountpoint="/", fstype="ext4", device="/dev/sda1", opts="rw")
    mock.disk_partitions.return_value = [part]
    disk = SimpleNamespace(total=500 * 1024**3, used=200 * 1024**3, free=300 * 1024**3, percent=40.0)
    mock.disk_usage.return_value = disk

    # net_io_counters
    net = SimpleNamespace(bytes_sent=1_000_000, bytes_recv=5_000_000, packets_sent=1000, packets_recv=5000)
    mock.net_io_counters.return_value = {"eth0": net}

    return mock


@pytest.fixture
def psutil_mock():
    mock = _make_psutil_mock()
    # Patch at both the module-attribute level and in the skill's module namespace
    with (
        patch.dict(sys.modules, {"psutil": mock}),
        patch("clawclip.skills.builtin.monitor.psutil", mock),
        patch("clawclip.skills.builtin.monitor._PSUTIL_AVAILABLE", True),
    ):
        yield mock


@pytest.fixture
def skill() -> SystemMonitorSkill:
    return SystemMonitorSkill()


@pytest.fixture
def context() -> SkillContext:
    return SkillContext(user_id="test_user")


class TestSystemMonitorSkillExecution:
    async def test_get_system_info(self, skill, context, psutil_mock):
        result = await skill.execute("get_system_info", {}, context)
        assert result.success is True
        output = result.output
        # The output string is built inside _collect() which runs in an executor;
        # key fields must appear.
        assert "CPU" in output
        assert "RAM" in output

    async def test_get_process_list(self, skill, context, psutil_mock):
        result = await skill.execute("get_process_list", {}, context)
        assert result.success is True
        assert "python" in result.output or "PID" in result.output

    async def test_get_disk_usage(self, skill, context, psutil_mock):
        result = await skill.execute("get_disk_usage", {}, context)
        assert result.success is True
        assert "/" in result.output or "Mount" in result.output

    def test_tool_definitions(self, skill):
        assert len(skill.tools) == 5

    async def test_graceful_no_psutil(self, skill, context):
        with patch("clawclip.skills.builtin.monitor._PSUTIL_AVAILABLE", False):
            result = await skill.execute("get_system_info", {}, context)
        assert result.success is False
        assert "psutil" in result.output.lower()
