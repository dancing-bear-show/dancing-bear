"""Tests for phone CLI command functions — re-import shim.

Implementation has moved to:
  - test_cli_pipeline_cmds.py  (TestPipelineCommands)
  - test_cli_inline_cmds.py   (TestInlineCommandHelpers, TestInlineCommands, TestAutoFoldersCommand)
"""

from __future__ import annotations

from tests.phone_tests.cli.test_cli_pipeline_cmds import TestPipelineCommands  # noqa: F401
from tests.phone_tests.cli.test_cli_inline_cmds import (  # noqa: F401
    TestAutoFoldersCommand,
    TestInlineCommandHelpers,
    TestInlineCommands,
)

if __name__ == "__main__":
    import unittest
    unittest.main()
