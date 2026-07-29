"""Import shim — split into test_filters_list_delete.py and test_filters_sync_plan.py."""

from tests.mail_tests.filters.test_filters_list_delete import *  # noqa: F401, F403  # NOSONAR - intentional re-export shim, see module docstring
from tests.mail_tests.filters.test_filters_sync_plan import *  # noqa: F401, F403  # NOSONAR - intentional re-export shim, see module docstring

if __name__ == "__main__":
    import unittest

    unittest.main()
