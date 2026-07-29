"""Import shim — split into test_outlook_auth_device.py and test_outlook_auth_validate.py."""

from tests.mail_tests.outlook.test_outlook_auth_device import *  # noqa: F401, F403  # NOSONAR
from tests.mail_tests.outlook.test_outlook_auth_validate import *  # noqa: F401, F403  # NOSONAR

if __name__ == "__main__":
    import unittest
    unittest.main()
