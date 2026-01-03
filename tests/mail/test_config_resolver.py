"""Tests for mail/config_resolver.py path and profile resolution."""

import os
import tempfile
import unittest

from mail.config_resolver import (
    expand_path,
    default_gmail_credentials_path,
    default_gmail_token_path,
    default_outlook_token_path,
    default_outlook_flow_path,
    _read_ini,
    _write_ini,
    resolve_paths,
    resolve_paths_profile,
    persist_if_provided,
    _get_ini_section,
    get_outlook_client_id,
    get_outlook_tenant,
    get_outlook_token_path,
)


class ExpandPathTests(unittest.TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(expand_path(None))

    def test_empty_returns_empty(self):
        self.assertEqual(expand_path(""), "")

    def test_expands_tilde(self):
        result = expand_path("~/some/path")
        self.assertFalse(result.startswith("~"))
        self.assertIn(os.path.expanduser("~"), result)

    def test_absolute_path_unchanged(self):
        path = "/absolute/path/to/file"
        self.assertEqual(expand_path(path), path)

    def test_relative_path_unchanged(self):
        path = "relative/path"
        self.assertEqual(expand_path(path), path)


class DefaultPathTests(unittest.TestCase):
    def test_gmail_credentials_path_exists(self):
        path = default_gmail_credentials_path()
        self.assertIsInstance(path, str)
        self.assertTrue(path.endswith("credentials.json"))

    def test_gmail_token_path_exists(self):
        path = default_gmail_token_path()
        self.assertIsInstance(path, str)
        self.assertTrue(path.endswith("token.json"))

    def test_outlook_token_path_exists(self):
        path = default_outlook_token_path()
        self.assertIsInstance(path, str)
        self.assertTrue(path.endswith("outlook_token.json"))

    def test_outlook_flow_path_exists(self):
        path = default_outlook_flow_path()
        self.assertIsInstance(path, str)
        self.assertTrue(path.endswith("msal_flow.json"))


class IniOperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ini_path = os.path.join(self.tmpdir, "credentials.ini")
        # Patch the INI paths to use our temp file
        import mail.config_resolver as cr
        self._orig_ini_paths = cr._INI_PATHS
        cr._INI_PATHS = [self.ini_path]

    def tearDown(self):
        import shutil
        import mail.config_resolver as cr
        cr._INI_PATHS = self._orig_ini_paths
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_read_ini_empty_when_no_file(self):
        result = _read_ini()
        self.assertEqual(result, {})

    def test_write_and_read_ini(self):
        _write_ini("/path/to/creds.json", "/path/to/token.json")
        result = _read_ini()

        self.assertIn("mail", result)
        self.assertEqual(result["mail"]["credentials"], "/path/to/creds.json")
        self.assertEqual(result["mail"]["token"], "/path/to/token.json")

    def test_write_with_profile(self):
        _write_ini("/path/to/creds.json", "/path/to/token.json", profile="personal")
        result = _read_ini()

        self.assertIn("mail.personal", result)
        self.assertEqual(result["mail.personal"]["credentials"], "/path/to/creds.json")

    def test_write_outlook_settings(self):
        _write_ini(
            None,
            None,
            outlook_client_id="client-123",
            tenant="consumers",
            outlook_token="/path/to/outlook.json",  # nosec B106 - test file path
        )
        result = _read_ini()

        self.assertEqual(result["mail"]["outlook_client_id"], "client-123")
        self.assertEqual(result["mail"]["tenant"], "consumers")
        self.assertEqual(result["mail"]["outlook_token"], "/path/to/outlook.json")

    def test_write_creates_parent_dirs(self):
        import mail.config_resolver as cr
        nested_path = os.path.join(self.tmpdir, "nested", "dir", "creds.ini")
        cr._INI_PATHS = [nested_path]

        _write_ini("/path/to/creds.json", None)

        self.assertTrue(os.path.exists(nested_path))


class ResolvePathsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ini_path = os.path.join(self.tmpdir, "credentials.ini")
        import mail.config_resolver as cr
        self._orig_ini_paths = cr._INI_PATHS
        cr._INI_PATHS = [self.ini_path]

    def tearDown(self):
        import shutil
        import mail.config_resolver as cr
        cr._INI_PATHS = self._orig_ini_paths
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_arg_credentials_takes_precedence(self):
        _write_ini("/ini/creds.json", "/ini/token.json")
        creds, token = resolve_paths(
            arg_credentials="/arg/creds.json",
            arg_token=None,
        )
        self.assertEqual(creds, "/arg/creds.json")

    def test_arg_token_takes_precedence(self):
        _write_ini("/ini/creds.json", "/ini/token.json")
        creds, token = resolve_paths(
            arg_credentials=None,
            arg_token="/arg/token.json",  # nosec B106 - test fixture path
        )
        self.assertEqual(token, "/arg/token.json")

    def test_falls_back_to_ini(self):
        _write_ini("/ini/creds.json", "/ini/token.json")
        creds, token = resolve_paths(arg_credentials=None, arg_token=None)
        self.assertEqual(creds, "/ini/creds.json")
        self.assertEqual(token, "/ini/token.json")

    def test_falls_back_to_defaults(self):
        # No INI file, no args
        creds, token = resolve_paths(arg_credentials=None, arg_token=None)
        self.assertTrue(creds.endswith("credentials.json"))
        self.assertTrue(token.endswith("token.json"))


class ResolvePathsProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ini_path = os.path.join(self.tmpdir, "credentials.ini")
        import mail.config_resolver as cr
        self._orig_ini_paths = cr._INI_PATHS
        cr._INI_PATHS = [self.ini_path]

    def tearDown(self):
        import shutil
        import mail.config_resolver as cr
        cr._INI_PATHS = self._orig_ini_paths
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_with_profile(self):
        _write_ini("/personal/creds.json", "/personal/token.json", profile="personal")
        creds, token = resolve_paths_profile(
            arg_credentials=None,
            arg_token=None,
            profile="personal",
        )
        self.assertEqual(creds, "/personal/creds.json")

    def test_without_profile_uses_default_section(self):
        _write_ini("/default/creds.json", "/default/token.json")
        creds, token = resolve_paths_profile(
            arg_credentials=None,
            arg_token=None,
            profile=None,
        )
        self.assertEqual(creds, "/default/creds.json")


class PersistIfProvidedTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ini_path = os.path.join(self.tmpdir, "credentials.ini")
        import mail.config_resolver as cr
        self._orig_ini_paths = cr._INI_PATHS
        cr._INI_PATHS = [self.ini_path]

    def tearDown(self):
        import shutil
        import mail.config_resolver as cr
        cr._INI_PATHS = self._orig_ini_paths
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_persists_when_provided(self):
        persist_if_provided(arg_credentials="/new/creds.json", arg_token=None)
        result = _read_ini()
        self.assertEqual(result["mail"]["credentials"], "/new/creds.json")

    def test_skips_when_not_provided(self):
        persist_if_provided(arg_credentials=None, arg_token=None)
        self.assertFalse(os.path.exists(self.ini_path))

    def test_persists_with_profile(self):
        persist_if_provided(
            arg_credentials="/work/creds.json",
            arg_token="/work/token.json",  # nosec B106 - test fixture path
            profile="work",
        )
        result = _read_ini()
        self.assertIn("mail.work", result)


class GetIniSectionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ini_path = os.path.join(self.tmpdir, "credentials.ini")
        import mail.config_resolver as cr
        self._orig_ini_paths = cr._INI_PATHS
        cr._INI_PATHS = [self.ini_path]

    def tearDown(self):
        import shutil
        import mail.config_resolver as cr
        cr._INI_PATHS = self._orig_ini_paths
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_section_with_profile(self):
        _write_ini("/profile/creds.json", None, profile="myprofile")
        section = _get_ini_section("myprofile")
        self.assertEqual(section["credentials"], "/profile/creds.json")

    def test_get_section_falls_back_to_default(self):
        _write_ini("/default/creds.json", None)
        section = _get_ini_section("nonexistent")
        self.assertEqual(section.get("credentials"), "/default/creds.json")

    def test_get_section_no_profile(self):
        _write_ini("/default/creds.json", None)
        section = _get_ini_section(None)
        self.assertEqual(section["credentials"], "/default/creds.json")


class OutlookSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ini_path = os.path.join(self.tmpdir, "credentials.ini")
        import mail.config_resolver as cr
        self._orig_ini_paths = cr._INI_PATHS
        cr._INI_PATHS = [self.ini_path]

    def tearDown(self):
        import shutil
        import mail.config_resolver as cr
        cr._INI_PATHS = self._orig_ini_paths
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_outlook_client_id(self):
        _write_ini(None, None, outlook_client_id="my-client-id")
        result = get_outlook_client_id()
        self.assertEqual(result, "my-client-id")

    def test_get_outlook_client_id_with_profile(self):
        _write_ini(None, None, profile="work", outlook_client_id="work-client")
        result = get_outlook_client_id(profile="work")
        self.assertEqual(result, "work-client")

    def test_get_outlook_tenant(self):
        _write_ini(None, None, tenant="consumers")
        result = get_outlook_tenant()
        self.assertEqual(result, "consumers")

    def test_get_outlook_token_path(self):
        _write_ini(None, None, outlook_token="/path/to/outlook.json")  # nosec B106 - test file path
        result = get_outlook_token_path()
        self.assertEqual(result, "/path/to/outlook.json")

    def test_get_outlook_token_path_defaults(self):
        result = get_outlook_token_path()
        self.assertTrue(result.endswith("outlook_token.json"))


if __name__ == "__main__":
    unittest.main()
