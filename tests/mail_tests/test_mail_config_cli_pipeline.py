"""Import shim — split into test_config_cli_cache.py and test_config_cli_derive.py."""

from tests.mail_tests.test_config_cli_cache import *  # noqa: F401, F403  # NOSONAR
from tests.mail_tests.test_config_cli_derive import *  # noqa: F401, F403  # NOSONAR

if __name__ == "__main__":
    import unittest
    unittest.main()
