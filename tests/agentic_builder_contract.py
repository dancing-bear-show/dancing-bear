"""Shared contract for the per-domain agentic builder modules.

Ten domains expose the same three functions from ``<domain>/agentic.py``:
``build_agentic_capsule()``, ``build_domain_map()`` and
``emit_agentic_context()``. Each domain had hand-copied assertions against them,
which produced the usual result of copy-pasted tests: the coverage was whatever
the last person copied. ``emit_agentic_context`` was exercised in 16 test files
while ``build_domain_map`` was exercised in 9, even though 10 domains define it.

State the contract once here and let each domain supply its identifiers.

Usage::

    class TestWifiAgentic(AgenticBuilderContractMixin, unittest.TestCase):
        MODULE_PATH = "wifi.agentic"
        APP_ID = "wifi"

The invariants below were derived by running all ten modules, not assumed:
every capsule opens with ``agentic: <app_id>``, every domain map opens with
``Top-Level``, and ``emit_agentic_context()`` returns 0 while writing the
capsule to stdout.
"""

from __future__ import annotations

import contextlib
import importlib
import io


class AgenticBuilderContractMixin:
    """Contract tests for a ``<domain>/agentic.py`` module.

    Subclasses must set :attr:`MODULE_PATH` and :attr:`APP_ID`, and must also
    inherit from ``unittest.TestCase``.
    """

    #: Importable path of the agentic module, e.g. ``"wifi.agentic"``.
    MODULE_PATH: str
    #: Identifier the capsule announces itself with. Not always the package
    #: name -- ``calendars.agentic`` emits ``agentic: calendar`` (singular).
    APP_ID: str
    #: Whether the capsule embeds a derived CLI tree. ``maker`` and ``qlty``
    #: deliberately build no tree, so they set this False. For every other
    #: domain a missing tree means the parser failed to load and was swallowed
    #: by ``core.agentic.cached_parser_loader``, which is a real defect that
    #: leaves the capsule silently less useful.
    EXPECT_CLI_TREE: bool = True

    def _module(self):
        return importlib.import_module(self.MODULE_PATH)

    # -- build_agentic_capsule ------------------------------------------

    def test_capsule_is_a_nonempty_string(self):
        capsule = self._module().build_agentic_capsule()
        self.assertIsInstance(capsule, str)
        self.assertGreater(len(capsule.strip()), 0)

    def test_capsule_announces_the_app_id(self):
        capsule = self._module().build_agentic_capsule()
        self.assertEqual(capsule.splitlines()[0].strip(), f"agentic: {self.APP_ID}")

    def test_capsule_declares_a_purpose(self):
        capsule = self._module().build_agentic_capsule()
        self.assertIn("purpose:", capsule)

    def test_capsule_includes_cli_tree_when_expected(self):
        capsule = self._module().build_agentic_capsule()
        if self.EXPECT_CLI_TREE:
            self.assertIn("CLI Tree", capsule)
        else:
            self.assertNotIn("CLI Tree", capsule)

    # -- build_domain_map -----------------------------------------------

    def test_domain_map_is_a_nonempty_string(self):
        domain_map = self._module().build_domain_map()
        self.assertIsInstance(domain_map, str)
        self.assertGreater(len(domain_map.strip()), 0)

    def test_domain_map_starts_with_top_level(self):
        domain_map = self._module().build_domain_map()
        self.assertEqual(domain_map.splitlines()[0].strip(), "Top-Level")

    def test_domain_map_is_not_the_unavailable_placeholder(self):
        """``core.meta_base`` falls back to this when no map can be built."""
        self.assertNotIn("Domain Map not available", self._module().build_domain_map())

    # -- emit_agentic_context -------------------------------------------

    def test_emit_returns_zero_and_writes_the_capsule(self):
        module = self._module()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = module.emit_agentic_context()
        self.assertEqual(rc, 0)
        self.assertIn(f"agentic: {self.APP_ID}", buf.getvalue())

    def test_emit_output_matches_the_builder(self):
        """The CLI path and the library path must not drift apart."""
        module = self._module()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            module.emit_agentic_context()
        self.assertEqual(buf.getvalue().strip(), module.build_agentic_capsule().strip())

    def test_emit_accepts_the_shared_positional_signature(self):
        """Every domain takes (fmt, compact) positionally, even where ignored.

        Positional only: the parameter *names* differ across domains -- nine
        use ``_compact`` to mark it unused while ``mail.agentic`` actually
        consumes it and names it ``compact``. The CLI wiring calls
        positionally, so that difference is invisible to callers, but a domain
        that dropped the second parameter entirely would break at runtime.
        """
        module = self._module()
        for args in ((), ("yaml",), ("text", True)):
            with self.subTest(args=args):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = module.emit_agentic_context(*args)
                self.assertEqual(rc, 0)
