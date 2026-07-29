"""Import shim — split into test_accounts_processors.py and test_accounts_producers.py."""

from importlib import import_module

for _mod_name in (
    "tests.mail_tests.accounts.test_accounts_processors",
    "tests.mail_tests.accounts.test_accounts_producers",
):
    _mod = import_module(_mod_name)
    for _name in getattr(_mod, "__all__", None) or (n for n in dir(_mod) if not n.startswith("_")):
        globals()[_name] = getattr(_mod, _name)
del _mod_name, _mod, _name

if __name__ == "__main__":
    import unittest

    unittest.main()
