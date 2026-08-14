"""Shared test fixtures for wifi tests."""
from __future__ import annotations

from wifi.diagnostics_runners import CommandResult, CommandRunner


class FakeRunner(CommandRunner):
    """Fake runner for tests.

    Supports two lookup modes:
    - Dict constructor: ``FakeRunner({"ping": CommandResult(...)})`` — keyed by
      the first element of the command list (executable name only).
    - ``.add()`` method: ``runner.add(["ping", "-c", "5", "1.1.1.1"], stdout=...)``
      — keyed by the full command tuple for precise per-invocation control.

    Full-tuple keys (from ``.add()``) take priority over executable-name keys.
    """

    def __init__(self, responses=None):
        # responses keyed by executable name (first cmd element)
        self.responses = responses or {}
        # responses keyed by full command tuple (from .add())
        self._exact: dict = {}
        self.calls: list = []

    def add(self, cmd, stdout="", stderr="", returncode=0):
        """Register a response for an exact command list."""
        self._exact[tuple(cmd)] = CommandResult(
            stdout=stdout, stderr=stderr, returncode=returncode
        )

    def run(self, cmd, timeout=None):
        self.calls.append(cmd)
        key_exact = tuple(cmd)
        if key_exact in self._exact:
            return self._exact[key_exact]
        key_name = cmd[0]
        if key_name in self.responses:
            return self.responses[key_name]
        return CommandResult(stdout="", stderr="not found", returncode=127)
