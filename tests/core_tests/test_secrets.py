"""Tests for core/secrets.py secret masking utilities."""

import unittest

from core.secrets import (
    mask_headers,
    mask_url,
    mask_text,
    _mask_value,
)


class MaskValueTests(unittest.TestCase):
    def test_empty_value(self):
        self.assertEqual(_mask_value(""), "")
        self.assertIsNone(_mask_value(None))  # NOSONAR - intentional None test for defensive handling

    def test_bearer_token(self):
        self.assertEqual(_mask_value("Bearer abc123"), "Bearer ***REDACTED***")
        self.assertEqual(_mask_value("bearer xyz"), "Bearer ***REDACTED***")

    def test_token_prefix(self):
        self.assertEqual(_mask_value("Token secret123"), "Token ***REDACTED***")

    def test_basic_auth(self):
        self.assertEqual(_mask_value("Basic dXNlcjpwYXNz"), "Basic ***REDACTED***")

    def test_plain_value(self):
        self.assertEqual(_mask_value("some-api-key"), "***REDACTED***")


class MaskHeadersTests(unittest.TestCase):
    def test_empty_headers(self):
        self.assertEqual(mask_headers({}), {})
        self.assertEqual(mask_headers(None), {})

    def test_authorization_header(self):
        headers = {"Authorization": "Bearer secret123"}
        result = mask_headers(headers)
        self.assertEqual(result["Authorization"], "Bearer ***REDACTED***")

    def test_proxy_authorization(self):
        headers = {"Proxy-Authorization": "Basic creds"}
        result = mask_headers(headers)
        self.assertEqual(result["Proxy-Authorization"], "Basic ***REDACTED***")

    def test_x_api_key(self):
        headers = {"X-API-Key": "my-secret-key"}
        result = mask_headers(headers)
        self.assertEqual(result["X-API-Key"], "***REDACTED***")

    def test_x_auth_token(self):
        headers = {"X-Auth-Token": "token123"}
        result = mask_headers(headers)
        self.assertEqual(result["X-Auth-Token"], "***REDACTED***")

    def test_non_sensitive_headers_unchanged(self):
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/html",
        }
        result = mask_headers(headers)
        self.assertEqual(result["Content-Type"], "application/json")
        self.assertEqual(result["Accept"], "text/html")

    def test_mixed_headers(self):
        headers = {
            "Authorization": "Bearer secret",
            "Content-Type": "application/json",
        }
        result = mask_headers(headers)
        self.assertEqual(result["Authorization"], "Bearer ***REDACTED***")
        self.assertEqual(result["Content-Type"], "application/json")


class MaskUrlTests(unittest.TestCase):
    def test_empty_url(self):
        self.assertEqual(mask_url(""), "")
        self.assertEqual(mask_url(None), "")  # NOSONAR - intentional None test for defensive handling

    def test_url_without_query(self):
        url = "https://api.example.com/v1/users"
        self.assertEqual(mask_url(url), url)

    def test_url_with_token_param(self):
        url = "https://api.example.com?token=secret123"
        result = mask_url(url)
        self.assertIn("token=***REDACTED***", result)
        self.assertNotIn("secret123", result)

    def test_url_with_access_token(self):
        url = "https://api.example.com?access_token=xyz789"
        result = mask_url(url)
        self.assertIn("access_token=***REDACTED***", result)

    def test_url_with_password(self):
        url = "https://api.example.com?password=hunter2"
        result = mask_url(url)
        self.assertIn("password=***REDACTED***", result)

    def test_url_with_mixed_params(self):
        url = "https://api.example.com?user=john&token=secret&page=1"
        result = mask_url(url)
        self.assertIn("user=john", result)
        self.assertIn("token=***REDACTED***", result)
        self.assertIn("page=1", result)

    def test_url_preserves_structure(self):
        url = "https://api.example.com:8080/path?token=x#fragment"
        result = mask_url(url)
        self.assertTrue(result.startswith("https://api.example.com:8080/path"))
        self.assertIn("#fragment", result)


class MaskTextTests(unittest.TestCase):
    def test_empty_text(self):
        self.assertEqual(mask_text(""), "")
        self.assertEqual(mask_text(None), "")  # NOSONAR - intentional None test for defensive handling

    def test_authorization_bearer(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = mask_text(text)
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("eyJ", result)

    def test_authorization_basic(self):
        text = "Authorization: Basic dXNlcm5hbWU6cGFzc3dvcmQ="
        result = mask_text(text)
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("dXNlcm5hbWU", result)

    def test_x_api_key_header(self):
        text = "X-API-KEY: sk-1234567890abcdef"
        result = mask_text(text)
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("sk-1234567890", result)

    def test_token_equals(self):
        text = "token=abc123def456"
        result = mask_text(text)
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("abc123", result)

    def test_json_token_field(self):
        text = '{"access_token": "secret-value-here"}'
        result = mask_text(text)
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("secret-value-here", result)

    def test_json_password_field(self):
        text = '{"password": "hunter2"}'
        result = mask_text(text)
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("hunter2", result)

    def test_github_token(self):
        text = "Using token ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        result = mask_text(text)
        self.assertIn("gh_***REDACTED***", result)
        self.assertNotIn("ghp_x", result)

    def test_github_oauth_token(self):
        text = "gho_abcdefghijklmnopqrstuvwxyz123456"
        result = mask_text(text)
        self.assertIn("gh_***REDACTED***", result)

    def test_aws_secret_key(self):
        text = "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        result = mask_text(text)
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("wJalrXUtnFEMI", result)

    def test_aws_session_token(self):
        text = "aws_session_token: FwoGZXIvYXdzEBYaDPxxx"
        result = mask_text(text)
        self.assertIn("***REDACTED***", result)

    def test_url_query_token(self):
        text = "GET /api?token=secret123&user=john"
        result = mask_text(text)
        self.assertIn("***REDACTED***", result)
        self.assertIn("user=john", result)

    def test_non_sensitive_text_unchanged(self):
        text = "This is a normal log message with no secrets"
        result = mask_text(text)
        self.assertEqual(result, text)

    def test_atlassian_token(self):
        text = "ATATT3xFfGF0abcdefghijklmnopqrst"
        result = mask_text(text)
        self.assertIn("AT***REDACTED***", result)


class TestUriEmbeddedCredentials(unittest.TestCase):
    """user:password@host survived both maskers.

    mask_url inspected only the query string and urlunsplit reassembled the
    netloc verbatim; mask_text had no pattern for the shape at all. Database
    drivers and HTTP clients quote the whole URI when auth fails, so this is
    one of the likeliest shapes to reach a log.
    """

    PW = "s3cr3tpassword"

    def test_mask_url_redacts_netloc_password(self):
        out = mask_url(f"https://user:{self.PW}@api.example.com/endpoint")
        self.assertNotIn(self.PW, out)
        # The username identifies which account failed, so it is kept.
        self.assertIn("user", out)
        self.assertIn("api.example.com", out)

    def test_mask_url_preserves_port(self):
        out = mask_url(f"https://user:{self.PW}@db.host:5432/path")
        self.assertNotIn(self.PW, out)
        self.assertIn("5432", out)

    def test_mask_url_leaves_credential_free_url_alone(self):
        url = "https://api.example.com/v1?page=2"
        self.assertEqual(mask_url(url), url)

    def test_malformed_port_does_not_leak_the_password(self):
        # urlsplit's .password/.port properties raise ValueError on a bad
        # port, which sent mask_url into its except branch and returned the
        # ORIGINAL url -- password intact. A masking function that emits
        # the secret on malformed input is worse than none.
        for url in (
            f"https://user:{self.PW}@host:bad/",
            f"https://user:{self.PW}@host:99999999/",
            f"https://user:{self.PW}@host:/path",
        ):
            with self.subTest(url=url):
                self.assertNotIn(self.PW, mask_url(url))

    def test_username_without_password_is_left_alone(self):
        url = "https://justauser@host/path"
        self.assertEqual(mask_url(url), url)

    def test_password_containing_an_at_sign(self):
        url = "https://user:p@ssw0rd@host/path"
        self.assertNotIn("ssw0rd", mask_url(url))

    def test_mask_text_redacts_connection_string(self):
        text = f"connection failed: postgres://dbuser:{self.PW}@db.host/mydb"
        out = mask_text(text)
        self.assertNotIn(self.PW, out)
        self.assertIn("dbuser", out)

    def test_mask_text_covers_any_scheme(self):
        for scheme in ("postgres", "mysql", "redis", "amqp", "https"):
            with self.subTest(scheme=scheme):
                text = f"{scheme}://u:{self.PW}@host/db"
                self.assertNotIn(self.PW, mask_text(text))

    def test_uri_without_password_is_untouched(self):
        text = "postgres://dbuser@db.host/mydb"
        self.assertEqual(mask_text(text), text)

    def test_mask_text_password_containing_an_at_sign(self):
        # The password group stopped at the FIRST '@', so an unescaped '@'
        # in the password ended the match early and left the tail visible.
        out = mask_text("connect failed: postgres://u:p@ssw0rd@host/db")
        self.assertNotIn("ssw0rd", out)
        self.assertIn("host/db", out)

    def test_mask_text_password_with_several_at_signs(self):
        out = mask_text("mysql://u:a@b@c@host:3306/db")
        self.assertNotIn("a@b@c", out)
        self.assertIn("host:3306/db", out)

    def test_mask_url_preserves_ipv6_host(self):
        # Rebuilding from parts.hostname would drop the brackets.
        out = mask_url(f"https://user:{self.PW}@[2001:db8::1]:8080/path")
        self.assertNotIn(self.PW, out)
        self.assertIn("[2001:db8::1]:8080", out)

    def test_error_path_masks_the_query_too(self):
        # A malformed IPv6 literal makes urlsplit raise, so mask_url falls
        # back to string surgery. Masking only the password there meant the
        # function leaked a query secret precisely on its own error path.
        url = f"https://user:{self.PW}@[bad::ipv6::host]:99/p?api_key=SECRETQUERY"
        out = mask_url(url)
        self.assertNotIn(self.PW, out)
        self.assertNotIn("SECRETQUERY", out)

    def test_error_path_keeps_benign_query_params(self):
        url = "https://user:pw@[bad::ipv6::host]:99/p?page=2&sort=name"
        out = mask_url(url)
        self.assertIn("page=2", out)
        self.assertIn("sort=name", out)

    def test_error_path_preserves_the_fragment(self):
        url = f"https://u:{self.PW}@[bad::ipv6::x]:9/p?token=SECRETQ#frag"
        out = mask_url(url)
        self.assertNotIn("SECRETQ", out)
        self.assertIn("#frag", out)


class TestMappingLiteralMasking(unittest.TestCase):
    """Both JSON and Python-repr mapping forms must mask.

    An exception carrying a dict stringifies as repr with single quotes, so
    a double-quote-only rule left RuntimeError({'api_key': ...}) unmasked
    in the RetryExhaustedError message built from it.
    """

    SECRET = "opaquevalue987654"  # nosec B105 - synthetic fixture, not a real credential - the masking tests need it to look like a secret

    def test_python_repr_dict_is_masked(self):
        text = f"RuntimeError({{'api_key': '{self.SECRET}'}})"
        self.assertNotIn(self.SECRET, mask_text(text))

    def test_json_form_still_masked(self):
        text = f'{{"api_key": "{self.SECRET}"}}'
        self.assertNotIn(self.SECRET, mask_text(text))

    def test_both_quote_styles_across_key_names(self):
        for key in ("api_key", "api_secret", "token", "password", "client_secret"):
            for quote in ("'", '"'):
                with self.subTest(key=key, quote=quote):
                    text = f"{{{quote}{key}{quote}: {quote}{self.SECRET}{quote}}}"
                    self.assertNotIn(self.SECRET, mask_text(text))

    def test_quote_styles_are_not_mixed(self):
        # A single-quoted value must be closed by a single quote, so a
        # stray double quote inside it cannot terminate the match early.
        text = "{'api_key': 'has\"double\"inside'}"
        out = mask_text(text)
        self.assertNotIn("has", out)
        self.assertTrue(out.endswith("'}"), out)

    def test_reaches_retry_error_message(self):
        from core.retry import RetryExhaustedError

        exc = RuntimeError(f"rejected: {{'api_key': '{self.SECRET}'}}")
        self.assertNotIn(self.SECRET, str(RetryExhaustedError(2, exc)))

    def test_escaped_quote_inside_value_does_not_end_the_match(self):
        # A plain .*? stopped at the first quote character and redacted
        # only the head: "abc\"def_TAIL" became ***REDACTED***"def_TAIL,
        # which reads as masked while leaving the tail in the log.
        for text in (
            r'{"api_key": "abc\"def_SECRETTAIL"}',
            r"{'api_key': 'abc\'def_SECRETTAIL'}",
        ):
            with self.subTest(text=text):
                out = mask_text(text)
                self.assertNotIn("SECRETTAIL", out)
                self.assertNotIn("def", out)

    def test_escaped_backslash_before_closing_quote(self):
        out = mask_text(r'{"api_key": "value\\"}')
        self.assertNotIn("value", out)

    def test_benign_mapping_fields_survive(self):
        for text in (
            "{'api_version': '2'}",
            '{"name": "widget"}',
            "{'sort_key': 'name'}",
        ):
            with self.subTest(text=text):
                self.assertEqual(mask_text(text), text)


class TestVendorTokenShapes(unittest.TestCase):
    """Tokens recognizable by shape, with no key= context around them."""

    def test_slack_token(self):
        self.assertNotIn(
            "12345-67890-abcdefghijklmnop",
            mask_text("auth failed with xoxb-12345-67890-abcdefghijklmnop"),
        )

    def test_stripe_tokens(self):
        for tok in ("sk_live_abcdefghij1234567890", "rk_test_abcdefghij1234567890"):
            with self.subTest(tok=tok):
                self.assertNotIn(tok, mask_text(f"charge failed: {tok}"))

    def test_openai_token(self):
        tok = "sk-" + "a" * 40
        self.assertNotIn(tok, mask_text(f"request rejected: {tok}"))

    def test_pem_private_key_block(self):
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEAsecretkeymaterial\n"
            "-----END RSA PRIVATE KEY-----"
        )
        out = mask_text(f"failed to load key:\n{pem}")
        self.assertNotIn("MIIEowIBAAKCAQEAsecretkeymaterial", out)


class TestBareCredentialPairs(unittest.TestCase):
    """password=/secret=/client_secret= in unstructured text.

    The JSON and query-param rules already covered these key names; the
    bare key=value shape that exception text actually takes did not.
    """

    SECRET = "opaquevalue987654"  # nosec B105 - synthetic fixture, not a real credential - the masking tests need it to look like a secret

    def test_password_style_keys_are_masked(self):
        for key in ("password", "passwd", "secret", "client_secret", "private_key"):
            with self.subTest(key=key):
                self.assertNotIn(
                    self.SECRET, mask_text(f"{key}={self.SECRET}")
                )

    def test_dot_separated_spelling_is_masked(self):
        self.assertNotIn(self.SECRET, mask_text(f"api.key={self.SECRET}"))

    def test_percent_encoded_values_are_fully_masked(self):
        # An allow-list value class stopped at the '%': "abc%2Fdef" was
        # redacted up to the escape and the tail emitted, which reads as
        # masked while still leaking most of the credential.
        for value in ("%2Fabc123def456", "abc%2Fdef456ghi", "a%2Bb%3Dc"):
            with self.subTest(value=value):
                out = mask_text(f"api_key={value}")
                self.assertNotIn("%2F", out)
                self.assertNotIn("abc", out)
                self.assertEqual(out, "api_key=***REDACTED***")

    def test_value_stops_at_a_delimiter(self):
        # Masking must not swallow the rest of the line.
        out = mask_text("api_key=abc123, retrying in 5s")
        self.assertNotIn("abc123", out)
        self.assertIn("retrying in 5s", out)

    def test_value_stops_at_a_closing_quote(self):
        out = mask_text('called with "api_key=abc123" and failed')
        self.assertNotIn("abc123", out)
        self.assertIn("and failed", out)


class TestJsonFieldSpellings(unittest.TestCase):
    """The JSON rule maintained its own key list and fell behind.

    api_secret was added to the sensitive-key set and the bare-pair rule
    but not here, so {"api_secret": "..."} in a RetryExhaustedError message
    still emitted the value.
    """

    SECRET = "s3cr3tvalue123"  # nosec B105 - synthetic fixture, not a real credential - the masking tests need it to look like a secret

    def test_api_secret_json_field_is_masked(self):
        for key in ("api_secret", "api-secret", "api.secret"):
            with self.subTest(key=key):
                self.assertNotIn(
                    self.SECRET, mask_text(f'{{"{key}": "{self.SECRET}"}}')
                )

    def test_other_sensitive_json_fields_are_masked(self):
        for key in (
            "api_key", "api_token", "token", "access_token", "refresh_token",
            "secret", "client_secret", "private_key", "password", "passwd",
        ):
            with self.subTest(key=key):
                self.assertNotIn(
                    self.SECRET, mask_text(f'{{"{key}": "{self.SECRET}"}}')
                )

    def test_benign_json_fields_survive(self):
        payload = '{"api_version": "2", "name": "widget"}'
        self.assertEqual(mask_text(payload), payload)

    def test_masked_json_stays_parseable(self):
        import json as _json

        out = mask_text(f'{{"api_secret": "{self.SECRET}"}}')
        self.assertEqual(_json.loads(out)["api_secret"], "***REDACTED***")


class TestNoOverMasking(unittest.TestCase):
    """Widening these patterns must not redact ordinary log content.

    Over-masking is the quieter failure: nobody files a bug because a log
    line says ***REDACTED*** too often, but every log in the repo gets
    worse.
    """

    def test_benign_key_value_pairs_survive(self):
        for text in (
            "api_version=2",
            "sort_key=name",
            "primary_key=id",
            "public_key_id=42",
            "monkey=banana",
            "key=value",
            "secretary=alice",
        ):
            with self.subTest(text=text):
                self.assertEqual(mask_text(text), text)

    def test_ordinary_urls_and_prose_survive(self):
        for text in (
            "https://example.com/path?page=2&limit=50",
            "GET https://api.example.com/v1/users/123 -> 200",
            "Traceback (most recent call last):",
        ):
            with self.subTest(text=text):
                self.assertEqual(mask_text(text), text)

    def test_benign_key_names_are_not_sensitive(self):
        from core.secrets import is_sensitive_key

        for key in ("sort_key", "primary_key", "keyboard", "tokenizer", "id"):
            with self.subTest(key=key):
                self.assertFalse(is_sensitive_key(key))


class TestHeaderMaskingUsesSharedPolicy(unittest.TestCase):
    """mask_headers had its own 4-name list and missed live credentials.

    apple_music/client.py sends Music-User-Token on every request, and
    http.py logs headers at DEBUG through mask_headers -- so the token was
    emitted while Authorization beside it was redacted.
    """

    def test_vendor_token_header_is_masked(self):
        out = mask_headers(
            {"Authorization": "Bearer devtok", "Music-User-Token": "usertok456"}
        )
        self.assertNotIn("usertok456", str(out))
        self.assertNotIn("devtok", str(out))

    def test_shared_key_set_applies_to_headers(self):
        from core.secrets import SENSITIVE_PARAM_KEYS

        for key in sorted(SENSITIVE_PARAM_KEYS):
            with self.subTest(key=key):
                out = mask_headers({key: "opaquevalue987654"})
                self.assertNotIn("opaquevalue987654", str(out))

    def test_benign_headers_pass_through(self):
        headers = {"Accept": "application/json", "User-Agent": "dancing-bear/1.0"}
        self.assertEqual(mask_headers(headers), headers)


class TestSeparatorFolding(unittest.TestCase):
    """One spelling of a key must not be sensitive on only some paths.

    mask_text's bare-pair regex accepts api.key, but is_sensitive_key
    folded only -/_ -- so mask_url returned "?api.key=SECRET" untouched
    while mask_text redacted the same name in prose.
    """

    SECRET = "opaquevalue987654"  # nosec B105 - synthetic fixture, not a real credential - the masking tests need it to look like a secret

    def test_dotted_spellings_are_sensitive(self):
        from core.secrets import is_sensitive_key

        for key in ("api.key", "api.secret", "access.token", "client.secret"):
            with self.subTest(key=key):
                self.assertTrue(is_sensitive_key(key))

    def test_dotted_spellings_are_masked_in_urls(self):
        for key in ("api.key", "api.secret"):
            with self.subTest(key=key):
                url = f"https://svc.example/v1?{key}={self.SECRET}"
                self.assertNotIn(self.SECRET, mask_url(url))

    def test_all_separator_spellings_agree(self):
        # The three separators are interchangeable in the wild; none of
        # them should be the one that slips through.
        from core.secrets import is_sensitive_key

        for key in ("api_key", "api-key", "api.key", "API.KEY", "Api-Key"):
            with self.subTest(key=key):
                self.assertTrue(is_sensitive_key(key))

    def test_benign_dotted_names_are_still_benign(self):
        from core.secrets import is_sensitive_key

        for key in ("api.version", "sort.key", "user.id"):
            with self.subTest(key=key):
                self.assertFalse(is_sensitive_key(key))


if __name__ == "__main__":
    unittest.main()
