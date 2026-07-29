"""Import shim — split into test_outlook_auth_device.py and test_outlook_auth_validate.py."""

from importlib import import_module

for _mod_name in (
    "tests.mail_tests.outlook.test_outlook_auth_device",
    "tests.mail_tests.outlook.test_outlook_auth_validate",
):
    _mod = import_module(_mod_name)
    for _name in getattr(_mod, "__all__", None) or (n for n in dir(_mod) if not n.startswith("_")):
        globals()[_name] = getattr(_mod, _name)
del _mod_name, _mod, _name

if __name__ == "__main__":
    import unittest

    unittest.main()
