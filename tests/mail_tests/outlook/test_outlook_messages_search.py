"""Import shim — split into test_outlook_search_core.py and test_outlook_search_extra.py."""

from tests.mail_tests.outlook.test_outlook_search_core import *  # noqa: F401, F403  # NOSONAR
from tests.mail_tests.outlook.test_outlook_search_extra import *  # noqa: F401, F403  # NOSONAR

if __name__ == "__main__":
    import unittest
    unittest.main()
