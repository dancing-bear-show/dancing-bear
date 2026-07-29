"""Import shim — split into test_filters_pipeline_plan.py and test_filters_pipeline_sweep.py."""

from tests.mail_tests.filters.test_filters_pipeline_plan import *  # noqa: F401, F403  # NOSONAR - intentional re-export shim, see module docstring
from tests.mail_tests.filters.test_filters_pipeline_sweep import *  # noqa: F401, F403  # NOSONAR - intentional re-export shim, see module docstring

if __name__ == "__main__":
    import unittest

    unittest.main()
