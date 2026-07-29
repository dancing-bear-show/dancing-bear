"""Shared test fixtures for wifi tests."""
from __future__ import annotations

from wifi.diagnostics import CommandResult, CommandRunner


class FakeRunner(CommandRunner):
    """Fake runner for tests."""
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def run(self, cmd, timeout=None):
        self.calls.append(cmd)
        key = cmd[0]
        if key in self.responses:
            return self.responses[key]
        return CommandResult(stdout="", stderr="not found", returncode=127)
