"""Unit tests for core/llm_cli.py helper functions."""

import unittest

from core.llm_cli import (
    _extract_app_arg,
    _parse_sla_env,
    _split_list,
    _status_for_area,
    _fail_on_stale,
    _safe_call,
    _familiar_content,
    DEFAULT_SLA_DAYS,
)


class TestExtractAppArg(unittest.TestCase):
    def test_no_app_arg(self):
        app, remaining = _extract_app_arg(['inventory', '--stdout'])
        self.assertIsNone(app)
        self.assertEqual(remaining, ['inventory', '--stdout'])

    def test_app_with_space(self):
        app, remaining = _extract_app_arg(['--app', 'calendar', 'agentic'])
        self.assertEqual(app, 'calendar')
        self.assertEqual(remaining, ['agentic'])

    def test_app_with_equals(self):
        app, remaining = _extract_app_arg(['--app=schedule', 'domain-map'])
        self.assertEqual(app, 'schedule')
        self.assertEqual(remaining, ['domain-map'])

    def test_short_flag(self):
        app, remaining = _extract_app_arg(['-a', 'phone', 'familiar'])
        self.assertEqual(app, 'phone')
        self.assertEqual(remaining, ['familiar'])

    def test_missing_value_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _extract_app_arg(['--app'])
        self.assertIn('Missing value', str(ctx.exception))

    def test_preserves_other_args(self):
        app, remaining = _extract_app_arg(['--app', 'desk', 'agentic', '--stdout', '--write', 'out.md'])
        self.assertEqual(app, 'desk')
        self.assertEqual(remaining, ['agentic', '--stdout', '--write', 'out.md'])


class TestParseSlaEnv(unittest.TestCase):
    def test_empty_string(self):
        import os
        old = os.environ.get('LLM_SLA')
        try:
            os.environ['LLM_SLA'] = ''
            result = _parse_sla_env()
            self.assertEqual(result, {})
        finally:
            if old is None:
                os.environ.pop('LLM_SLA', None)
            else:
                os.environ['LLM_SLA'] = old

    def test_single_entry(self):
        import os
        old = os.environ.get('LLM_SLA')
        try:
            os.environ['LLM_SLA'] = 'mail:30'
            result = _parse_sla_env()
            self.assertEqual(result, {'mail': 30})
        finally:
            if old is None:
                os.environ.pop('LLM_SLA', None)
            else:
                os.environ['LLM_SLA'] = old

    def test_multiple_entries_comma(self):
        import os
        old = os.environ.get('LLM_SLA')
        try:
            os.environ['LLM_SLA'] = 'mail:30,calendar:60,Root:90'
            result = _parse_sla_env()
            self.assertEqual(result, {'mail': 30, 'calendar': 60, 'Root': 90})
        finally:
            if old is None:
                os.environ.pop('LLM_SLA', None)
            else:
                os.environ['LLM_SLA'] = old

    def test_semicolon_separator(self):
        import os
        old = os.environ.get('LLM_SLA')
        try:
            os.environ['LLM_SLA'] = 'mail:30;calendar:60'
            result = _parse_sla_env()
            self.assertEqual(result, {'mail': 30, 'calendar': 60})
        finally:
            if old is None:
                os.environ.pop('LLM_SLA', None)
            else:
                os.environ['LLM_SLA'] = old

    def test_invalid_value_skipped(self):
        import os
        old = os.environ.get('LLM_SLA')
        try:
            os.environ['LLM_SLA'] = 'mail:abc,calendar:60'
            result = _parse_sla_env()
            self.assertEqual(result, {'calendar': 60})
        finally:
            if old is None:
                os.environ.pop('LLM_SLA', None)
            else:
                os.environ['LLM_SLA'] = old

    def test_strips_whitespace(self):
        import os
        old = os.environ.get('LLM_SLA')
        try:
            os.environ['LLM_SLA'] = ' mail : 30 , calendar : 60 '
            result = _parse_sla_env()
            self.assertEqual(result, {'mail': 30, 'calendar': 60})
        finally:
            if old is None:
                os.environ.pop('LLM_SLA', None)
            else:
                os.environ['LLM_SLA'] = old


class TestSplitList(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(_split_list(''), [])

    def test_none(self):
        self.assertEqual(_split_list(None), [])

    def test_single_item(self):
        self.assertEqual(_split_list('mail'), ['mail'])

    def test_comma_separated(self):
        self.assertEqual(_split_list('mail,calendar,phone'), ['mail', 'calendar', 'phone'])

    def test_semicolon_separated(self):
        self.assertEqual(_split_list('mail;calendar;phone'), ['mail', 'calendar', 'phone'])

    def test_strips_whitespace(self):
        self.assertEqual(_split_list(' mail , calendar , phone '), ['mail', 'calendar', 'phone'])

    def test_filters_empty_parts(self):
        self.assertEqual(_split_list('mail,,calendar'), ['mail', 'calendar'])


class TestStatusForArea(unittest.TestCase):
    def test_ok_within_threshold(self):
        status = _status_for_area('mail', 30.0, {'mail': 60})
        self.assertEqual(status, 'OK')

    def test_stale_exceeds_threshold(self):
        status = _status_for_area('mail', 90.0, {'mail': 60})
        self.assertEqual(status, 'STALE')

    def test_uses_root_fallback(self):
        status = _status_for_area('unknown', 100.0, {'Root': 90})
        self.assertEqual(status, 'STALE')

    def test_uses_default_sla_days(self):
        status = _status_for_area('unknown', DEFAULT_SLA_DAYS - 1, {})
        self.assertEqual(status, 'OK')

    def test_exact_threshold_is_ok(self):
        status = _status_for_area('mail', 60.0, {'mail': 60})
        self.assertEqual(status, 'OK')


class TestFailOnStale(unittest.TestCase):
    def test_no_stale(self):
        stats = [
            {'area': 'mail', 'staleness_days': 30.0},
            {'area': 'calendar', 'staleness_days': 50.0},
        ]
        result = _fail_on_stale(stats, {'mail': 60, 'calendar': 60})
        self.assertFalse(result)

    def test_one_stale(self):
        stats = [
            {'area': 'mail', 'staleness_days': 70.0},
            {'area': 'calendar', 'staleness_days': 50.0},
        ]
        result = _fail_on_stale(stats, {'mail': 60, 'calendar': 60})
        self.assertTrue(result)

    def test_uses_root_fallback(self):
        stats = [{'area': 'unknown', 'staleness_days': 100.0}]
        result = _fail_on_stale(stats, {'Root': 90})
        self.assertTrue(result)

    def test_empty_stats(self):
        result = _fail_on_stale([], {'mail': 60})
        self.assertFalse(result)


class TestSafeCall(unittest.TestCase):
    def test_returns_builder_result(self):
        result = _safe_call(lambda: 'hello', 'fallback')
        self.assertEqual(result, 'hello')

    def test_returns_fallback_on_none_builder(self):
        result = _safe_call(None, 'fallback')
        self.assertEqual(result, 'fallback')

    def test_returns_fallback_on_exception(self):
        def bad_builder():
            raise RuntimeError('oops')
        result = _safe_call(bad_builder, 'fallback')
        self.assertEqual(result, 'fallback')

    def test_returns_fallback_on_empty_result(self):
        result = _safe_call(lambda: '', 'fallback')
        self.assertEqual(result, 'fallback')

    def test_error_message_in_fallback(self):
        def bad_builder():
            raise ValueError('test error')
        result = _safe_call(bad_builder, '')
        self.assertIn('test error', result)


class TestFamiliarContent(unittest.TestCase):
    def test_compact_mode(self):
        content = _familiar_content(verbose=False, compact=True)
        self.assertIn('agent_note:', content)
        self.assertIn('skip_paths:', content)
        self.assertIn('heavy_files:', content)

    def test_non_verbose(self):
        content = _familiar_content(verbose=False, compact=False)
        self.assertIn('agent_note:', content)
        self.assertIn('steps:', content)
        self.assertIn('./bin/llm agentic --stdout', content)
        # Should not include extended commands
        self.assertNotIn('resume', content)

    def test_verbose_includes_extended(self):
        content = _familiar_content(verbose=True, compact=False)
        self.assertIn('resume', content)
        self.assertIn('desk', content)
        self.assertIn('maker', content)


if __name__ == '__main__':
    unittest.main()
