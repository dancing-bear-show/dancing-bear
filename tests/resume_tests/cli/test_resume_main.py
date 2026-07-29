"""Resume main tests — shim re-exporting split test modules."""
from tests.resume_tests.cli.test_resume_main_core import (  # noqa: F401
    TestResumeMain,
    TestResumeCliMain,
    TestResumeCommandHelpers,
)
from tests.resume_tests.cli.test_resume_main_commands import (  # noqa: F401
    TestStructureHelpers,
    TestResumeCommands,
)

if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
