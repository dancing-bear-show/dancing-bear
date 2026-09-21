"""Unit tests for core/llm_cli.py helper functions."""

import contextlib
import io
import unittest

from core.llm_cli import (
    bind_entrypoints,
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
        # The prescribed step must stay compact: the uncompacted capsule inlines
        # CONTEXT.md/MIGRATION_STATE.md/PATTERNS.md/AGENTS.md (~38KB vs ~2KB).
        self.assertIn('./bin/llm agentic --stdout --compact', content)

    def test_non_verbose(self):
        content = _familiar_content(verbose=False, compact=False)
        self.assertIn('agent_note:', content)
        self.assertIn('steps:', content)
        self.assertIn('./bin/llm agentic --stdout --compact', content)
        # Should not include extended commands
        self.assertNotIn('resume', content)

    def test_verbose_includes_extended(self):
        content = _familiar_content(verbose=True, compact=False)
        self.assertIn('resume', content)
        self.assertIn('desk', content)
        self.assertIn('maker', content)


class TestBindEntrypoints(unittest.TestCase):
    """bind_entrypoints() partially applies a config into module entrypoints.

    Every domain llm_cli module assigns its build_parser/main from this, and
    bin/llm dispatches via `module.main(argv)`, so both must stay plain
    module-level callables.
    """

    def setUp(self):
        import argparse

        from core.llm_cli import make_app_llm_config

        self.argparse = argparse
        self.config = make_app_llm_config(
            prog='llm-demo',
            description='Demo LLM utilities',
            agentic=lambda: 'agentic: demo',
            domain_map=lambda: 'map',
            inventory=lambda: 'inventory',
            familiar_compact=lambda: 'compact',
            familiar_extended=lambda: 'extended',
            policies=lambda: 'policies',
            agentic_filename='AGENTIC_DEMO.md',
            domain_map_filename='DOMAIN_MAP_DEMO.md',
        )
        self.build_parser, self.main = bind_entrypoints(self.config)

    def test_build_parser_returns_parser_for_the_bound_config(self):
        parser = self.build_parser()
        self.assertIsInstance(parser, self.argparse.ArgumentParser)
        self.assertEqual(parser.prog, 'llm-demo')

    def test_build_parser_returns_a_fresh_parser_each_call(self):
        """argparse parsers are stateful; callers must not share one."""
        self.assertIsNot(self.build_parser(), self.build_parser())

    def test_main_is_callable_with_no_arguments(self):
        """bin/llm and the __main__ guard both rely on the argv default."""
        self.assertTrue(callable(self.main))

    def test_main_reports_the_bound_prog_on_a_usage_error(self):
        """The bound config -- not a shared default -- drives argparse output."""
        with contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit):
                self.main([])
        self.assertIn('llm-demo', err.getvalue())

    def test_main_dispatches_a_subcommand(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = self.main(['agentic', '--stdout'])
        self.assertEqual(code, 0)
        self.assertIn('agentic: demo', out.getvalue())

    def test_separate_configs_stay_independent(self):
        """Each call closes over its own config -- no shared mutable state."""
        other = self.config.__class__(**{**vars(self.config), 'prog': 'llm-other'})
        _, _ = bind_entrypoints(self.config)
        other_build, _ = bind_entrypoints(other)
        self.assertEqual(self.build_parser().prog, 'llm-demo')
        self.assertEqual(other_build().prog, 'llm-other')


class TestDomainLlmConfigOverrides(unittest.TestCase):
    """Tests for DomainLlmConfig prog/description override fields."""

    def _make_config(self, **extra):
        from core.llm_builders import DomainLlmConfig, make_domain_llm_module
        cfg = DomainLlmConfig(
            app_id="testapp",
            app_title="TestApp",
            purpose="testing purposes",
            agentic_module="core.llm_builders",  # any importable module
            **extra,
        )
        return make_domain_llm_module(cfg)

    def test_prog_defaults_to_llm_dash_app_id(self):
        llm_config = self._make_config()
        self.assertEqual(llm_config.prog, "llm-testapp")

    def test_prog_override_is_honoured(self):
        llm_config = self._make_config(prog="llm")
        self.assertEqual(llm_config.prog, "llm")

    def test_description_defaults_to_generated_string(self):
        llm_config = self._make_config()
        self.assertIn("TestApp", llm_config.description)
        self.assertIn("inventory", llm_config.description)

    def test_description_override_is_honoured(self):
        llm_config = self._make_config(description="Custom description")
        self.assertEqual(llm_config.description, "Custom description")


if __name__ == '__main__':
    unittest.main()
