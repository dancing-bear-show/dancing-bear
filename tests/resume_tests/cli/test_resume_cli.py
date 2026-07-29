"""Resume CLI tests — shim re-exporting split test modules."""
from tests.resume_tests.cli.test_resume_cli_core import (  # noqa: F401
    TestResumeCLIHelp,
    TestResumeCLISubcommandHelp,
    TestResumeCLIGroupHelp,
    TestResumeCLIMain,
    TestResumeCLIResolveOut,
    TestResumeCLIHelpers,
    TestResumeCLIFindStructureInConfig,
    TestResumeCLILoadStructure,
    TestResumeCLIMainErrorHandling,
)
from tests.resume_tests.cli.test_resume_cli_commands import (  # noqa: F401
    TestResumeCLIExtract,
    TestResumeCLISummarize,
    TestResumeCLICandidateInit,
    TestResumeCLIAlign,
    TestResumeCLIRender,
    TestResumeCLIStructure,
    TestResumeCLIStyleBuild,
    TestResumeCLIFilesTidy,
    TestResumeCLIExperienceExport,
    TestResumeCLICandidateInitExtended,
    TestResumeCLIAlignExtended,
    TestResumeCLISummarizeExtended,
)

if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
