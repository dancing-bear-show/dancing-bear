"""Re-import shim — keeps 'python3 -m unittest tests.metals_tests.spot.test_metals_spot' green."""
from tests.metals_tests.spot.test_spot_fetch import (  # noqa: F401
    TestTodayIso,
    TestFetchYahooSeries,
    TestFetchStooqSeries,
    TestAutoStartDate,
)
from tests.metals_tests.spot.test_spot_run import (  # noqa: F401
    TestRun,
    TestMain,
)

if __name__ == '__main__':
    import unittest
    unittest.main()
