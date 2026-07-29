"""Import shim — split into test_accounts_processors.py and test_accounts_producers.py."""

from tests.mail_tests.accounts.test_accounts_processors import *  # noqa: F401, F403  # NOSONAR
from tests.mail_tests.accounts.test_accounts_producers import *  # noqa: F401, F403  # NOSONAR

if __name__ == "__main__":
    import unittest

    unittest.main()
