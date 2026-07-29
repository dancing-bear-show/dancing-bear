"""Import shim — split into test_gmail_client_init.py and test_gmail_client_ops.py."""

from tests.mail_tests.gmail.test_gmail_client_init import *  # noqa: F401, F403  # NOSONAR
from tests.mail_tests.gmail.test_gmail_client_ops import *  # noqa: F401, F403  # NOSONAR

if __name__ == "__main__":
    import unittest
    unittest.main()
