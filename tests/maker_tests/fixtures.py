"""Maker test fixtures.

Factories for creating ToolRequest, ToolResult, mock envelopes, and modules.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterator, Optional
from unittest.mock import MagicMock, patch

from maker.pipeline import ToolRequest, ToolResult


def make_tool_request(
    module: str = "test_module",
    entry_point: str = "main",
) -> ToolRequest:
    """Create a ToolRequest for testing.

    Args:
        module: Module name to import (default: "test_module")
        entry_point: Entry point function name (default: "main")

    Returns:
        ToolRequest instance
    """
    return ToolRequest(module=module, entry_point=entry_point)


def make_tool_result(
    module: str = "test_module",
    return_code: int = 0,
    error: Optional[str] = None,
) -> ToolResult:
    """Create a ToolResult for testing.

    Args:
        module: Module name that was executed (default: "test_module")
        return_code: Exit code from tool execution (default: 0)
        error: Optional error message (default: None)

    Returns:
        ToolResult instance
    """
    return ToolResult(module=module, return_code=return_code, error=error)


def make_mock_envelope(
    ok: bool = True,
    payload: Optional[Any] = None,
    error: Optional[str] = None,
) -> MagicMock:
    """Create a mock ResultEnvelope for testing.

    Args:
        ok: Whether envelope represents success (default: True)
        payload: Optional payload object (default: None)
        error: Optional error message for diagnostics (default: None)

    Returns:
        MagicMock configured as ResultEnvelope with ok(), payload, and diagnostics

    Example:
        envelope = make_mock_envelope(ok=True, payload=ToolResult(...))
        assert envelope.ok()
        assert envelope.payload.return_code == 0
    """
    mock_env = MagicMock()
    mock_env.ok.return_value = ok
    mock_env.payload = payload

    if error:
        mock_env.diagnostics = {"message": error}
    else:
        mock_env.diagnostics = {}

    return mock_env


def make_mock_module(
    entry_point: str = "main",
    main_return: int = 0,
    custom_entries: Optional[Dict[str, Callable]] = None,
) -> SimpleNamespace:
    """Create a mock module with entry point functions.

    Args:
        entry_point: Name of default entry point (default: "main")
        main_return: Return value for default entry point (default: 0)
        custom_entries: Dict of additional entry_point_name -> callable

    Returns:
        SimpleNamespace with entry point functions as attributes

    Example:
        # Simple module with main() returning 0
        mod = make_mock_module()
        assert mod.main() == 0

        # Module with custom entry point
        mod = make_mock_module(entry_point="custom", main_return=42)
        assert mod.custom() == 42

        # Module with multiple entry points
        mod = make_mock_module(custom_entries={
            "main": MagicMock(return_value=0),
            "other": MagicMock(side_effect=ValueError("boom"))
        })
    """
    namespace = SimpleNamespace()

    # Add custom entry points if provided
    if custom_entries:
        for name, func in custom_entries.items():
            setattr(namespace, name, func)
    else:
        # Add default entry point
        default_func = MagicMock(return_value=main_return)
        setattr(namespace, entry_point, default_func)

    return namespace


@contextmanager
def mock_import_module(
    entry_point: str = "main",
    main_return: int = 0,
    custom_entries: Optional[Dict[str, Callable]] = None,
    side_effect: Optional[Exception] = None,
) -> Iterator[SimpleNamespace]:
    """Context manager that patches maker.pipeline.import_module.

    Args:
        entry_point: Name of default entry point (default: "main")
        main_return: Return value for default entry point (default: 0)
        custom_entries: Dict of additional entry_point_name -> callable
        side_effect: Optional exception to raise on import (default: None)

    Yields:
        Mock module from make_mock_module()

    Example:
        # Success case
        with mock_import_module(main_return=0) as mod:
            result = some_function_that_imports()
            mod.main.assert_called_once()

        # Failure case
        with mock_import_module(side_effect=ImportError("No module")):
            result = some_function_that_imports()
            assert not result.ok()
    """
    mock_module = make_mock_module(
        entry_point=entry_point,
        main_return=main_return,
        custom_entries=custom_entries,
    )

    patch_kwargs = {"return_value": mock_module}
    if side_effect:
        patch_kwargs = {"side_effect": side_effect}

    with patch("maker.pipeline.import_module", **patch_kwargs) as mock_import:
        # Expose the mock module for assertions
        mock_import.module = mock_module
        yield mock_module
