"""Tests for core.preflight — invariant-check framework."""

from __future__ import annotations

import json
import unittest

from core.preflight import (
    InvariantViolation,
    PreflightReport,
    evaluate_invariants,
)


# ---------------------------------------------------------------------------
# Helper check functions used across test cases
# ---------------------------------------------------------------------------

def _always_pass(changes, baseline):
    return "always_pass", []


def _always_fail(changes, baseline):
    return "always_fail", [{"item": c} for c in changes]


def _raises(changes, baseline):
    raise ValueError("boom")


def _deletes_more_than_half(changes, baseline):
    total = baseline.get("total", len(changes))
    bad = [c for c in changes if c.get("op") == "delete"]
    if total and len(bad) > total / 2:
        return "deletes_more_than_half", bad
    return "deletes_more_than_half", []


def _no_new_labels(changes, baseline):
    bad = [c for c in changes if c.get("op") == "add_label"]
    return "no_new_labels", bad


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAllChecksPass(unittest.TestCase):
    def test_passed_true_when_all_clear(self):
        changes = [{"op": "modify", "id": "1"}]
        report = evaluate_invariants(changes, {}, [_always_pass])
        self.assertTrue(report.passed)

    def test_no_violations_when_all_clear(self):
        report = evaluate_invariants([{"op": "x"}], {}, [_always_pass])
        self.assertEqual(report.violations, [])

    def test_tallies_include_total_and_violation_count(self):
        changes = [{"op": "a"}, {"op": "b"}, {"op": "c"}]
        report = evaluate_invariants(changes, {}, [_always_pass])
        self.assertEqual(report.tallies["total_changes"], 3)
        self.assertEqual(report.tallies["violation_count"], 0)


class TestOneFailingCheck(unittest.TestCase):
    def _make_changes(self, n=5):
        return [{"op": "delete", "id": str(i)} for i in range(n)]

    def test_passed_false_on_violation(self):
        changes = self._make_changes()
        report = evaluate_invariants(changes, {"total": 6}, [_deletes_more_than_half])
        self.assertFalse(report.passed)

    def test_correct_code(self):
        changes = self._make_changes()
        report = evaluate_invariants(changes, {"total": 6}, [_deletes_more_than_half])
        self.assertEqual(len(report.violations), 1)
        self.assertEqual(report.violations[0].code, "deletes_more_than_half")

    def test_correct_samples(self):
        changes = self._make_changes(3)
        report = evaluate_invariants(changes, {"total": 4}, [_deletes_more_than_half])
        self.assertEqual(len(report.violations[0].samples), 3)

    def test_default_message_derived_from_code(self):
        changes = self._make_changes()
        report = evaluate_invariants(changes, {"total": 6}, [_deletes_more_than_half])
        self.assertEqual(report.violations[0].message, "deletes more than half")

    def test_custom_message_used_when_provided(self):
        changes = self._make_changes()
        report = evaluate_invariants(
            changes,
            {"total": 6},
            [_deletes_more_than_half],
            messages={"deletes_more_than_half": "Too many deletes — check your plan."},
        )
        self.assertEqual(
            report.violations[0].message, "Too many deletes — check your plan."
        )

    def test_tallies_violation_count(self):
        changes = self._make_changes()
        report = evaluate_invariants(changes, {"total": 6}, [_deletes_more_than_half])
        self.assertEqual(report.tallies["violation_count"], 1)


class TestMultipleFailingChecksAreAllCollected(unittest.TestCase):
    """Proves evaluate_invariants does NOT short-circuit on first failure."""

    def test_both_violations_collected(self):
        changes = [
            {"op": "delete", "id": "1"},
            {"op": "delete", "id": "2"},
            {"op": "add_label", "id": "3"},
        ]
        report = evaluate_invariants(
            changes,
            {"total": 3},
            [_deletes_more_than_half, _no_new_labels],
        )
        self.assertFalse(report.passed)
        codes = {v.code for v in report.violations}
        self.assertIn("deletes_more_than_half", codes)
        self.assertIn("no_new_labels", codes)
        self.assertEqual(len(report.violations), 2)

    def test_tallies_reflect_all_violations(self):
        changes = [
            {"op": "delete", "id": "x"},
            {"op": "delete", "id": "y"},
            {"op": "add_label", "id": "z"},
        ]
        report = evaluate_invariants(
            changes, {"total": 3}, [_deletes_more_than_half, _no_new_labels]
        )
        self.assertEqual(report.tallies["violation_count"], 2)


class TestMaxSamplesTruncation(unittest.TestCase):
    def test_samples_capped_at_max_samples(self):
        changes = [{"op": "add_label", "id": str(i)} for i in range(20)]
        report = evaluate_invariants(changes, {}, [_no_new_labels], max_samples=5)
        self.assertEqual(len(report.violations[0].samples), 5)

    def test_samples_not_truncated_below_cap(self):
        changes = [{"op": "add_label", "id": str(i)} for i in range(3)]
        report = evaluate_invariants(changes, {}, [_no_new_labels], max_samples=10)
        self.assertEqual(len(report.violations[0].samples), 3)

    def test_violation_still_recorded_when_truncated(self):
        changes = [{"op": "add_label", "id": str(i)} for i in range(20)]
        report = evaluate_invariants(changes, {}, [_no_new_labels], max_samples=5)
        self.assertFalse(report.passed)
        self.assertEqual(len(report.violations), 1)


class TestRaisingCheckBehavior(unittest.TestCase):
    def test_raising_check_produces_violation(self):
        report = evaluate_invariants([{"op": "x"}], {}, [_raises])
        self.assertFalse(report.passed)
        self.assertEqual(len(report.violations), 1)

    def test_raising_check_code_is_check_error(self):
        report = evaluate_invariants([{"op": "x"}], {}, [_raises])
        self.assertEqual(report.violations[0].code, "check_error")

    def test_raising_check_sample_contains_error_text(self):
        report = evaluate_invariants([{"op": "x"}], {}, [_raises])
        sample = report.violations[0].samples[0]
        self.assertIn("boom", sample["error"])

    def test_raising_check_sample_contains_check_name(self):
        report = evaluate_invariants([{"op": "x"}], {}, [_raises])
        sample = report.violations[0].samples[0]
        self.assertIn("_raises", sample["check"])

    def test_other_checks_still_run_after_raising_check(self):
        """A raising check must not abort the run — subsequent checks still execute."""
        changes = [{"op": "add_label", "id": "1"}]
        report = evaluate_invariants(changes, {}, [_raises, _no_new_labels])
        codes = {v.code for v in report.violations}
        self.assertIn("check_error", codes)
        self.assertIn("no_new_labels", codes)

    def test_raising_check_custom_message(self):
        report = evaluate_invariants(
            [{"op": "x"}],
            {},
            [_raises],
            messages={"check_error": "A check threw an exception."},
        )
        self.assertEqual(report.violations[0].message, "A check threw an exception.")


class TestToDict(unittest.TestCase):
    def _round_trip(self, obj):
        return json.loads(json.dumps(obj))

    def test_evaluate_invariants_returns_preflight_report(self):
        report = evaluate_invariants([], {}, [])
        self.assertIsInstance(report, PreflightReport)

    def test_violation_to_dict_round_trips(self):
        v = InvariantViolation(
            code="my_code",
            message="my message",
            samples=[{"id": "1", "op": "delete"}],
        )
        d = self._round_trip(v.to_dict())
        self.assertEqual(d["code"], "my_code")
        self.assertEqual(d["message"], "my message")
        self.assertEqual(d["samples"], [{"id": "1", "op": "delete"}])

    def test_report_to_dict_round_trips(self):
        changes = [{"op": "delete", "id": "1"}, {"op": "delete", "id": "2"}]
        report = evaluate_invariants(changes, {"total": 2}, [_deletes_more_than_half])
        d = self._round_trip(report.to_dict())
        self.assertIn("passed", d)
        self.assertIn("violations", d)
        self.assertIn("tallies", d)
        self.assertIsInstance(d["violations"], list)

    def test_passing_report_to_dict_round_trips(self):
        report = evaluate_invariants([{"op": "x"}], {}, [_always_pass])
        d = self._round_trip(report.to_dict())
        self.assertTrue(d["passed"])
        self.assertEqual(d["violations"], [])

    def test_to_dict_is_json_serializable_with_samples(self):
        changes = [{"op": "add_label", "id": str(i)} for i in range(5)]
        report = evaluate_invariants(changes, {}, [_no_new_labels])
        # must not raise
        encoded = json.dumps(report.to_dict())
        self.assertIn("no_new_labels", encoded)


class TestSummary(unittest.TestCase):
    def test_passing_summary_starts_with_passed(self):
        report = evaluate_invariants([{"op": "x"}, {"op": "y"}], {}, [_always_pass])
        s = report.summary()
        self.assertTrue(s.startswith("PASSED"))
        self.assertIn("2 changes", s)
        self.assertIn("0 violations", s)

    def test_failing_summary_starts_with_failed(self):
        changes = [{"op": "add_label", "id": "1"}]
        report = evaluate_invariants(changes, {}, [_no_new_labels])
        s = report.summary()
        self.assertTrue(s.startswith("FAILED"))
        # Singular at a count of one — this is user-facing CLI output.
        self.assertEqual(s.splitlines()[0], "FAILED: 1 change, 1 violation")

    def test_failing_summary_lists_violation_codes(self):
        changes = [{"op": "add_label", "id": "1"}]
        report = evaluate_invariants(changes, {}, [_no_new_labels])
        s = report.summary()
        self.assertIn("no_new_labels", s)

    def test_multiple_violations_each_get_a_line(self):
        changes = [
            {"op": "delete", "id": "1"},
            {"op": "delete", "id": "2"},
            {"op": "add_label", "id": "3"},
        ]
        report = evaluate_invariants(
            changes, {"total": 3}, [_deletes_more_than_half, _no_new_labels]
        )
        s = report.summary()
        self.assertIn("deletes_more_than_half", s)
        self.assertIn("no_new_labels", s)


class TestMessageDerivation(unittest.TestCase):
    def test_underscores_become_spaces(self):
        changes = [{"op": "add_label"}]
        report = evaluate_invariants(changes, {}, [_no_new_labels])
        self.assertEqual(report.violations[0].message, "no new labels")

    def test_messages_mapping_takes_priority(self):
        changes = [{"op": "add_label"}]
        report = evaluate_invariants(
            changes, {}, [_no_new_labels], messages={"no_new_labels": "Custom text"}
        )
        self.assertEqual(report.violations[0].message, "Custom text")

    def test_missing_key_in_messages_falls_back_to_derivation(self):
        changes = [{"op": "add_label"}]
        report = evaluate_invariants(
            changes, {}, [_no_new_labels], messages={"other_code": "irrelevant"}
        )
        self.assertEqual(report.violations[0].message, "no new labels")


class TestSummaryPluralization(unittest.TestCase):
    """summary() is user-facing CLI output, so counts read naturally."""

    @staticmethod
    def _fail_check(changes, baseline):
        return "bad_thing", list(changes)

    def test_singular_forms_at_count_one(self):
        report = evaluate_invariants([{"id": "1"}], {}, [self._fail_check])
        first = report.summary().splitlines()[0]
        self.assertEqual(first, "FAILED: 1 change, 1 violation")

    def test_plural_forms_above_one(self):
        changes = [{"id": "1"}, {"id": "2"}]
        report = evaluate_invariants(changes, {}, [self._fail_check])
        self.assertIn("2 changes", report.summary().splitlines()[0])

    def test_plural_forms_at_zero(self):
        report = evaluate_invariants([], {}, [])
        first = report.summary().splitlines()[0]
        self.assertEqual(first, "PASSED: 0 changes, 0 violations")

    def test_sample_count_is_pluralized(self):
        one = evaluate_invariants([{"id": "1"}], {}, [self._fail_check])
        self.assertIn("(1 sample)", one.summary())
        two = evaluate_invariants(
            [{"id": "1"}, {"id": "2"}], {}, [self._fail_check]
        )
        self.assertIn("(2 samples)", two.summary())


class TestMaskValueEdgeCases(unittest.TestCase):
    """Branches of the sample masker that ordinary change records miss."""

    SECRET = "yyyy3333444455556666"

    def _flag_all(self, changes, baseline):
        return "leaks", list(changes)

    def _sample(self, change):
        report = evaluate_invariants([change], {}, [self._flag_all])
        return report.violations[0].samples[0]

    def test_non_string_key_does_not_crash_or_mask(self):
        # A change record keyed by an int is unusual but legal; the key
        # cannot be sensitive, and normalizing it must not raise.
        sample = self._sample({1: "plain", "op": "sync"})
        self.assertEqual(sample[1], "plain")
        self.assertEqual(sample["op"], "sync")

    def test_tuple_values_are_masked_elementwise(self):
        sample = self._sample({"token": ("a", self.SECRET)})
        self.assertIsInstance(sample["token"], tuple)
        self.assertNotIn(self.SECRET, str(sample["token"]))

    def test_tuple_under_insensitive_key_keeps_benign_values(self):
        sample = self._sample({"tags": ("alpha", "beta")})
        self.assertEqual(sample["tags"], ("alpha", "beta"))

    def test_deeply_nested_mix_is_masked_throughout(self):
        change = {"a": [{"b": ("c", {"api_key": self.SECRET})}]}
        report = evaluate_invariants([change], {}, [self._flag_all])
        self.assertNotIn(self.SECRET, json.dumps(report.to_dict(), default=str))


class TestSamplesContainerIsImmutable(unittest.TestCase):
    """The samples COLLECTION cannot be resized after the report returns.

    frozen=True blocks attribute reassignment but not mutation of a list
    held in the attribute, so `violation.samples.append(...)` silently
    rewrote evidence that PreflightReport also references. A tuple closes
    that hole.

    The guarantee is deliberately scoped to the container -- individual
    samples are still plain dicts. test_individual_samples_remain_mutable
    pins that so the docstring and the behaviour cannot drift apart.
    """

    @staticmethod
    def _flag_all(changes, baseline):
        return "leaks", list(changes)

    def _report(self):
        return evaluate_invariants([{"id": "1"}], {}, [self._flag_all])

    def test_samples_is_a_tuple(self):
        self.assertIsInstance(self._report().violations[0].samples, tuple)

    def test_samples_cannot_be_appended_to(self):
        samples = self._report().violations[0].samples
        with self.assertRaises(AttributeError):
            samples.append({"injected": "yes"})

    def test_check_error_samples_are_also_a_tuple(self):
        def boom(changes, baseline):
            raise RuntimeError("boom")

        report = evaluate_invariants([{"id": "1"}], {}, [boom])
        self.assertIsInstance(report.violations[0].samples, tuple)

    def test_to_dict_still_emits_a_json_list(self):
        # The dict claims to be JSON-serializable, so a caller inspecting it
        # before serializing should see a list rather than a tuple.
        payload = self._report().to_dict()
        self.assertIsInstance(payload["violations"][0]["samples"], list)
        json.dumps(payload)

    def test_individual_samples_remain_mutable(self):
        # Documents the limit of the guarantee rather than implying one the
        # code does not provide: the tuple protects the collection, not the
        # dicts inside it. If this ever starts failing, the docstring on
        # InvariantViolation.samples needs updating with it.
        sample = self._report().violations[0].samples[0]
        sample["injected"] = "yes"
        self.assertEqual(sample["injected"], "yes")


class TestSensitiveKeyMasking(unittest.TestCase):
    """A bare value under a sensitive key must be redacted.

    mask_text recognizes credentials by surrounding text -- "?api_key=x",
    "Authorization: Bearer x". A value stored under a sensitive KEY has no
    such marker, so masking has to use the key as context.

    Every value here is deliberately OPAQUE: no "ghp_" prefix, no URL, no
    "Bearer". An earlier version of these tests used GitHub-token-shaped
    values, which mask_text catches by pattern -- so they passed even with
    no key handling at all and hid this gap entirely. If a value in this
    class ever becomes self-describing, the test stops proving anything.
    """

    OPAQUE = "zzz1111222233334444"

    def _flag_all(self, changes, baseline):
        return "leaks", list(changes)

    def _sample_for(self, change):
        report = evaluate_invariants([change], {}, [self._flag_all])
        return report.violations[0].samples[0]

    def _assert_no_leak(self, change):
        report = evaluate_invariants([change], {}, [self._flag_all])
        self.assertNotIn(self.OPAQUE, json.dumps(report.to_dict()))

    def test_opaque_value_is_not_caught_by_pattern_alone(self):
        # Guards the guard: proves OPAQUE really is invisible to mask_text,
        # so a pass below is attributable to key handling and nothing else.
        from core.secrets import mask_text

        self.assertIn(self.OPAQUE, mask_text(self.OPAQUE))

    def test_common_sensitive_keys_are_redacted(self):
        for key in (
            "api_key", "apikey", "api-key", "API_KEY",
            "token", "access_token", "refresh_token",
            "password", "secret", "client_secret",
            "authorization", "Authorization",
            "aws_secret_access_key",
        ):
            with self.subTest(key=key):
                self._assert_no_leak({key: self.OPAQUE})

    def test_header_style_keys_are_redacted(self):
        for key in ("X-Api-Key", "x_api_key", "X-Auth-Token"):
            with self.subTest(key=key):
                self._assert_no_leak({key: self.OPAQUE})

    def test_nested_sensitive_key_is_redacted(self):
        self._assert_no_leak({"meta": {"headers": {"api_key": self.OPAQUE}}})

    def test_sensitive_key_holding_a_list_redacts_every_leaf(self):
        self._assert_no_leak({"token": [self.OPAQUE, self.OPAQUE]})

    def test_insensitive_key_keeps_its_value(self):
        # Redaction must be targeted, or the report stops being evidence.
        sample = self._sample_for({"op": "sync", "count_label": "42 items"})
        self.assertEqual(sample["op"], "sync")
        self.assertEqual(sample["count_label"], "42 items")

    def test_key_names_are_preserved(self):
        # Knowing WHICH field was redacted is the point of the sample.
        sample = self._sample_for({"api_key": self.OPAQUE, "op": "sync"})
        self.assertIn("api_key", sample)
        self.assertNotIn(self.OPAQUE, sample["api_key"])

    def test_non_string_under_sensitive_key_is_untouched(self):
        sample = self._sample_for({"token": None, "secret": 42})
        self.assertIsNone(sample["token"])
        self.assertEqual(sample["secret"], 42)


class TestOffendingSampleMasking(unittest.TestCase):
    """Offending items are the caller's change records and may carry secrets.

    A change describing an API call carries the URL or headers that would
    make it, so an unmasked sample puts a live key in to_dict() output.

    These cases cover values mask_text recognizes from their surrounding
    text. Bare values under a sensitive key are a different mechanism and
    are covered by TestSensitiveKeyMasking above -- with deliberately
    pattern-less values, since a token-shaped one proves nothing there.
    """

    TOKEN = "ghp_EEEEEEEEEEEEEEEEEEEEEEEEEEEEEE"

    def _flag_all(self, changes, baseline):
        return "leaks_secret", list(changes)

    def test_secret_in_a_sample_value_is_masked(self):
        changes = [{"op": "sync", "url": f"https://x.example?api_key={self.TOKEN}"}]
        report = evaluate_invariants(changes, {}, [self._flag_all])
        self.assertNotIn(self.TOKEN, json.dumps(report.to_dict()))

    def test_samples_attribute_is_masked_too(self):
        # samples is public on the dataclass, so reading it directly must
        # give the same guarantee to_dict() does.
        changes = [{"url": f"https://x.example?api_key={self.TOKEN}"}]
        report = evaluate_invariants(changes, {}, [self._flag_all])
        self.assertNotIn(self.TOKEN, report.violations[0].samples[0]["url"])

    def test_nested_structures_are_masked(self):
        changes = [{
            "meta": {"headers": {"Authorization": f"Bearer {self.TOKEN}"}},
            "items": [f"token={self.TOKEN}"],
        }]
        report = evaluate_invariants(changes, {}, [self._flag_all])
        self.assertNotIn(self.TOKEN, json.dumps(report.to_dict()))

    def test_structure_and_non_secret_values_survive(self):
        changes = [{"op": "sync", "count": 5, "ok": True, "tags": ["a", "b"]}]
        report = evaluate_invariants(changes, {}, [self._flag_all])
        sample = report.violations[0].samples[0]
        self.assertEqual(sample["op"], "sync")
        self.assertEqual(sample["count"], 5)
        self.assertIs(sample["ok"], True)
        self.assertEqual(sample["tags"], ["a", "b"])

    def test_non_string_leaves_are_untouched(self):
        changes = [{"value": None, "ratio": 1.5}]
        report = evaluate_invariants(changes, {}, [self._flag_all])
        sample = report.violations[0].samples[0]
        self.assertIsNone(sample["value"])
        self.assertEqual(sample["ratio"], 1.5)


class TestApiKeyMasking(unittest.TestCase):
    """api_key/apikey were absent from the shared masking patterns.

    They are the most common spellings in public API query strings, so a
    masked-looking URL still carried the key.
    """

    SECRET = "SECRETVALUE123456"

    def test_query_spellings_are_masked(self):
        from core.secrets import mask_text

        for param in ("api_key", "apikey", "apiKey", "api-key"):
            with self.subTest(param=param):
                text = f"GET https://svc.example/?{param}={self.SECRET}"
                self.assertNotIn(self.SECRET, mask_text(text))

    def test_json_field_is_masked(self):
        from core.secrets import mask_text

        self.assertNotIn(
            self.SECRET, mask_text(f'{{"api_key": "{self.SECRET}"}}')
        )

    def test_previously_covered_params_still_masked(self):
        from core.secrets import mask_text

        for param in ("access_token", "token", "client_secret"):
            with self.subTest(param=param):
                text = f"https://svc.example/?{param}={self.SECRET}"
                self.assertNotIn(self.SECRET, mask_text(text))

    def test_all_three_masking_paths_agree_on_every_sensitive_key(self):
        """Every key in the shared set must mask on all three paths.

        mask_url, mask_headers and the preflight sample masker each answer
        "is this name sensitive?" -- and each used to answer it from its
        own list. A name in one list and not another was redacted on one
        path and emitted on the other, which is how x_auth_token,
        proxy_authorization, private_key and session_token leaked through
        mask_url while preflight redacted them.

        Driving the loop off SENSITIVE_PARAM_KEYS rather than a literal
        list means a key added later is covered here automatically.
        """
        from core.secrets import SENSITIVE_PARAM_KEYS, mask_headers, mask_url

        secret = "opaquevalue987654"

        def flag_all(changes, baseline):
            return "leaks", list(changes)

        for key in sorted(SENSITIVE_PARAM_KEYS):
            with self.subTest(key=key):
                self.assertNotIn(
                    secret,
                    mask_url(f"https://svc.example/v1?{key}={secret}"),
                    "mask_url leaked",
                )
                self.assertNotIn(
                    secret,
                    json.dumps(mask_headers({key: secret})),
                    "mask_headers leaked",
                )
                report = evaluate_invariants([{key: secret}], {}, [flag_all])
                self.assertNotIn(
                    secret, json.dumps(report.to_dict()), "preflight leaked"
                )

    def test_every_bare_pair_spelling_is_also_masked_in_urls(self):
        """The two masking paths must agree on what counts as a secret.

        mask_text() matches a bare-pair regex; mask_url() consults
        SENSITIVE_PARAM_KEYS. A spelling covered by one and not the other
        leaks through whichever path the caller happens to take -- which is
        exactly how api_secret regressed after being added to the regex
        alone. Driving both from one list makes the drift fail here rather
        than in production.
        """
        from core.secrets import mask_text, mask_url

        for spelling in (
            "api_key", "apikey", "api-key",
            "api_secret", "apisecret", "api-secret",
            "token",
        ):
            with self.subTest(spelling=spelling):
                bare = mask_text(f"{spelling}={self.SECRET}")
                url = mask_url(f"https://svc.example/v1?{spelling}={self.SECRET}")
                self.assertNotIn(self.SECRET, bare, "bare pair leaked")
                self.assertNotIn(self.SECRET, url, "url query leaked")

    def test_bare_key_value_pairs_are_masked(self):
        # No ? or & to mark these as query params, and no JSON quoting --
        # the shape exception and log text actually takes.
        from core.secrets import mask_text

        for param in ("api_key", "apikey", "api-key", "API_KEY", "api_secret"):
            with self.subTest(param=param):
                self.assertNotIn(
                    self.SECRET, mask_text(f"{param}={self.SECRET}")
                )

    def test_bare_pair_masked_inside_a_sentence(self):
        from core.secrets import mask_text

        text = f"connection failed (api_key={self.SECRET}) after 3 tries"
        masked = mask_text(text)
        self.assertNotIn(self.SECRET, masked)
        # Surrounding context survives so the message stays diagnostic.
        self.assertIn("connection failed", masked)
        self.assertIn("after 3 tries", masked)

    def test_similar_but_harmless_keys_are_not_masked(self):
        # Widening a shared regex risks over-masking: these are not secrets
        # and redacting them would degrade every log line in the repo.
        from core.secrets import mask_text

        for pair in (
            "api_version=2",
            "api_keys_count=4",
            "monkey=banana",
            "key=value",
        ):
            with self.subTest(pair=pair):
                self.assertEqual(mask_text(pair), pair)

    def test_bare_pair_reaches_retry_error_message(self):
        # End-to-end: the finding was reported against the retry surfaces,
        # so assert there and not only at the helper.
        from core.retry import RetryExhaustedError

        exc = RuntimeError(f"upstream rejected api_key={self.SECRET}")
        self.assertNotIn(self.SECRET, str(RetryExhaustedError(2, exc)))


class TestCheckLabelIsSafe(unittest.TestCase):
    """The check label must not serialize arbitrary repr output.

    A repr fallback leaks a functools.partial's bound arguments into the
    report, and a custom __repr__ is user code that can raise -- which would
    escape the handler whose whole job is to stop a buggy check from
    aborting the run.

    TOKEN is deliberately OPAQUE. An earlier version used a "ghp_"-shaped
    value, which mask_text catches by pattern -- so the partial test passed
    even when _check_label fell back to repr(), the exact bug it guards.
    """

    TOKEN = "wwww4444555566667777"

    @staticmethod
    def _boom(changes, baseline, api_key=None):
        raise RuntimeError("boom")

    def test_token_is_not_caught_by_pattern_alone(self):
        # Guards the guard: if mask_text redacted TOKEN on its own, every
        # assertion below would pass regardless of _check_label's behaviour.
        from core.secrets import mask_text

        self.assertIn(self.TOKEN, mask_text(self.TOKEN))

    def test_partial_bound_args_are_not_serialized(self):
        import functools

        check = functools.partial(self._boom, api_key=self.TOKEN)
        report = evaluate_invariants([{"id": "1"}], {}, [check])
        self.assertNotIn(self.TOKEN, json.dumps(report.to_dict()))

    def test_partial_still_identifies_the_wrapped_function(self):
        # Safety must not cost the diagnostic value the label exists for.
        import functools

        check = functools.partial(self._boom, api_key=self.TOKEN)
        report = evaluate_invariants([{"id": "1"}], {}, [check])
        self.assertIn("_boom", report.violations[0].samples[0]["check"])

    def test_raising_repr_does_not_escape_the_handler(self):
        class Hostile:
            def __call__(self, changes, baseline):
                raise RuntimeError("boom")

            def __repr__(self):
                raise ValueError("repr exploded")

        report = evaluate_invariants([{"id": "1"}], {}, [Hostile()])
        self.assertFalse(report.passed)
        self.assertEqual(report.violations[0].samples[0]["check"], "Hostile")

    def test_plain_function_label_is_its_name(self):
        report = evaluate_invariants([{"id": "1"}], {}, [self._boom])
        self.assertEqual(report.violations[0].samples[0]["check"], "_boom")

    def test_other_checks_still_run_after_a_hostile_one(self):
        class Hostile:
            def __call__(self, changes, baseline):
                raise RuntimeError("boom")

            def __repr__(self):
                raise ValueError("repr exploded")

        def ok(changes, baseline):
            return "clean", []

        report = evaluate_invariants([{"id": "1"}], {}, [Hostile(), ok])
        self.assertEqual(len(report.violations), 1)
        # Assert the type-name fallback actually fired. Without this the
        # test would pass even if the label were empty or wrong -- it would
        # only prove the run continued, not that the hostile repr was
        # sidestepped rather than swallowed some other way.
        self.assertEqual(report.violations[0].samples[0]["check"], "Hostile")


class TestCheckErrorMasking(unittest.TestCase):
    """A crashing check must not leak credentials into the report.

    Checks commonly wrap an HTTP or API call, and this report is built to be
    serialized via to_dict(), so both the exception text and the traceback
    (which quotes source lines) go through mask_text.
    """

    TOKEN = "ghp_CCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"

    def _raising_check(self, changes, baseline):
        raise RuntimeError(
            f"HTTP 401 for https://api.example.com?access_token={self.TOKEN}"
        )

    def test_error_text_is_masked(self):
        report = evaluate_invariants([{"id": "1"}], {}, [self._raising_check])
        sample = report.violations[0].samples[0]
        self.assertNotIn(self.TOKEN, sample["error"])
        self.assertIn("REDACTED", sample["error"])

    def test_traceback_is_masked(self):
        report = evaluate_invariants([{"id": "1"}], {}, [self._raising_check])
        sample = report.violations[0].samples[0]
        self.assertNotIn(self.TOKEN, sample["traceback"])

    def test_serialized_report_carries_no_token(self):
        report = evaluate_invariants([{"id": "1"}], {}, [self._raising_check])
        self.assertNotIn(self.TOKEN, json.dumps(report.to_dict()))

    def test_summary_carries_no_token(self):
        report = evaluate_invariants([{"id": "1"}], {}, [self._raising_check])
        self.assertNotIn(self.TOKEN, report.summary())

    def test_check_name_is_still_identifiable(self):
        # Masking must not cost the diagnostic value the sample exists for.
        report = evaluate_invariants([{"id": "1"}], {}, [self._raising_check])
        sample = report.violations[0].samples[0]
        self.assertIn("_raising_check", sample["check"])
        self.assertIn("HTTP 401", sample["error"])


if __name__ == "__main__":
    unittest.main()
