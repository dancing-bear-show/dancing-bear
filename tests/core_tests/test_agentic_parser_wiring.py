"""Every domain agentic module that declares a parser must actually load one.

``core.agentic.cached_parser_loader`` wraps the per-domain import in a bare
``except Exception`` and returns ``None`` on failure, so a broken loader is
SILENT: ``_cli_tree()`` and ``_flow_map()`` just return empty strings and the
agentic capsule renders without its CLI Tree and Flow Map sections. Nothing
raises, no test fails, and the capsule still looks plausible.

That is not hypothetical. Four domains shipped this way at once:

- ``resume``   imported a module-level ``build_parser`` that does not exist
                (the CLI is built with the CLIApp framework) -> ImportError
- ``schedule`` reached ``app`` through ``__main__``            -> AttributeError
- ``whatsapp`` called ``__main__.build_parser()``              -> AttributeError
- ``desk``     called ``cli.build_parser()``                   -> AttributeError

``phone`` had the identical bug earlier and carries a comment describing it,
which is why these tests exist: the fix keeps getting re-broken because the
failure mode produces no signal.

These assert on the OBSERVABLE consequence (a parser resolves, subcommands are
discoverable) rather than on how each domain reaches its parser, so a domain is
free to restructure as long as its capsule still describes a real CLI.
"""
from __future__ import annotations

import ast
import contextlib
import importlib
import io
import pathlib
import unittest

from core.agentic import list_subcommands

# Domains whose agentic module declares `_get_parser`. Domains that
# deliberately build no parser-derived tree (wifi, maker) are absent by design
# -- add a domain here when it gains a `_get_parser`.
PARSER_DOMAINS = [
    "calendars",
    "desk",
    "mail",
    "phone",
    "resume",
    "schedule",
    "whatsapp",
]


class AgenticParserResolutionTests(unittest.TestCase):
    def test_every_listed_domain_declares_a_parser_loader(self):
        # Guards the list above against a domain being renamed or dropped:
        # without this, a typo'd entry would make the real assertions vacuous.
        for domain in PARSER_DOMAINS:
            with self.subTest(domain=domain):
                mod = importlib.import_module(f"{domain}.agentic")
                self.assertTrue(
                    hasattr(mod, "_get_parser"),
                    f"{domain}.agentic lost its _get_parser; remove it from "
                    "PARSER_DOMAINS or restore the loader",
                )

    def test_parser_actually_resolves(self):
        # The core regression: cached_parser_loader returns None on any
        # exception, so this is the only place a broken import surfaces.
        for domain in PARSER_DOMAINS:
            with self.subTest(domain=domain):
                mod = importlib.import_module(f"{domain}.agentic")
                parser = mod._get_parser()
                self.assertIsNotNone(
                    parser,
                    f"{domain}.agentic._get_parser() returned None -- its "
                    "_load_parser raised and cached_parser_loader swallowed it. "
                    "The capsule will silently omit its CLI Tree and Flow Map.",
                )

    def test_parser_exposes_subcommands(self):
        # A parser that resolves but exposes nothing would still yield an empty
        # tree, so resolution alone is not enough.
        for domain in PARSER_DOMAINS:
            with self.subTest(domain=domain):
                mod = importlib.import_module(f"{domain}.agentic")
                subcommands = list_subcommands(mod._get_parser())
                self.assertTrue(
                    subcommands,
                    f"{domain}.agentic._get_parser() exposes no subcommands",
                )

    def test_load_parser_raises_loudly_when_called_directly(self):
        # cached_parser_loader is the thing that swallows; the underlying
        # _load_parser must not swallow on its own, or this whole suite could
        # pass against a loader that quietly returns None.
        for domain in PARSER_DOMAINS:
            with self.subTest(domain=domain):
                mod = importlib.import_module(f"{domain}.agentic")
                loader = getattr(mod, "_load_parser", None)
                if loader is None:
                    continue
                self.assertIsNotNone(
                    loader(),
                    f"{domain}.agentic._load_parser() returned None instead of "
                    "raising; a failure here would be undetectable",
                )


class FlowMapRendersTests(unittest.TestCase):
    """Domains with a _flow_map must emit something, not a silent empty string."""

    def test_flow_map_is_non_empty(self):
        for domain in PARSER_DOMAINS:
            with self.subTest(domain=domain):
                mod = importlib.import_module(f"{domain}.agentic")
                flow_map = getattr(mod, "_flow_map", None)
                if flow_map is None:
                    continue
                self.assertTrue(
                    flow_map().strip(),
                    f"{domain}.agentic._flow_map() is empty -- every guarded "
                    "branch failed its _cli_path_exists check",
                )


class CapsuleEmitterTests(unittest.TestCase):
    """The second swallow: BaseAssistant.maybe_emit_agentic's except-Exception.

    If `emit_func` raises for ANY reason, maybe_emit_agentic prints the
    two-line `fallback_banner` and returns 0. The CLI exits successfully and
    prints something plausible, so nothing looks wrong.

    Two domains shipped that way. Both used a single-dot relative import from
    inside `<domain>.cli.main`, which resolves to `<domain>.cli.agentic` rather
    than `<domain>.agentic`:

        schedule/cli/main.py   from .agentic import emit_agentic_context
        calendars/cli/main.py  from .agentic import build_agentic_capsule

    `./bin/schedule --agentic` emitted 79 bytes instead of 1601, and
    `./bin/calendar --agentic` 66 instead of 2242.

    Asserting on a byte floor rather than exact content: the capsules change as
    CLIs gain commands, but a banner-only fallback can never approach this.
    """

    # Domains whose capsule is built by a module-level agentic.py. Domains with
    # no agentic.py (apple_music) legitimately emit only the banner.
    CAPSULE_DOMAINS = ["calendars", "phone", "resume", "schedule", "whatsapp"]

    # The banner is two short lines; every real capsule carries a commands
    # block or a CLI tree on top of it.
    MIN_CAPSULE_BYTES = 200

    def test_capsule_builder_is_importable_from_the_domain_root(self):
        # The exact failure: the builder lives at <domain>.agentic, and a
        # single-dot import from <domain>.cli.main missed it.
        for domain in self.CAPSULE_DOMAINS:
            with self.subTest(domain=domain):
                mod = importlib.import_module(f"{domain}.agentic")
                self.assertTrue(
                    hasattr(mod, "build_agentic_capsule"),
                    f"{domain}.agentic has no build_agentic_capsule",
                )

    def test_capsule_is_substantially_more_than_the_fallback_banner(self):
        for domain in self.CAPSULE_DOMAINS:
            with self.subTest(domain=domain):
                mod = importlib.import_module(f"{domain}.agentic")
                capsule = mod.build_agentic_capsule()
                self.assertGreater(
                    len(capsule),
                    self.MIN_CAPSULE_BYTES,
                    f"{domain} capsule is {len(capsule)} bytes -- close enough "
                    "to the two-line fallback banner to suggest emit_func is "
                    "raising and being swallowed",
                )

    def test_capsule_names_its_own_domain(self):
        # Guards against a domain accidentally emitting another's capsule.
        for domain in self.CAPSULE_DOMAINS:
            with self.subTest(domain=domain):
                mod = importlib.import_module(f"{domain}.agentic")
                self.assertIn("agentic:", mod.build_agentic_capsule())

    def test_cli_entry_point_emits_the_real_capsule(self):
        """Invoke main(['--agentic']) and capture what a user actually sees.

        THIS is the test that catches the bug. The three above call
        build_agentic_capsule() directly, which never exercises the wiring
        between <domain>/cli/main.py and <domain>/agentic.py -- and the wiring
        is exactly where the single-dot import failed. Verified by
        reintroducing the bug: the direct-call tests stayed green while this
        one fails.

        The lesson generalises: when a swallowed exception substitutes a
        fallback, only running the real entry point can tell you which branch
        you got.
        """
        entry_points = {
            "calendars": "calendars.cli.main",
            "schedule": "schedule.cli.main",
            "whatsapp": "whatsapp.cli.main",
            "resume": "resume.cli.main",
            "phone": "phone.cli.main",
        }
        for domain, module_path in entry_points.items():
            with self.subTest(domain=domain):
                mod = importlib.import_module(module_path)
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = mod.main(["--agentic"])
                emitted = buf.getvalue()

                self.assertEqual(rc, 0, f"{domain} --agentic exited {rc}")
                self.assertGreater(
                    len(emitted),
                    self.MIN_CAPSULE_BYTES,
                    f"{domain} --agentic emitted {len(emitted)} bytes. That is "
                    "the fallback banner: emit_func raised and "
                    "maybe_emit_agentic swallowed it. Check the relative "
                    "import depth in the CLI's agentic emitter -- from inside "
                    f"{module_path} the builder is `..agentic`, not `.agentic`.",
                )


class GuardsResolveTests(unittest.TestCase):
    """Every `_cli_path_exists` guard must name a path the CLI really exposes.

    A guard naming something the parser does not have is **silently False**:
    its line is never appended, so the capsule is quietly missing an entry.
    Nothing raises, and no output-based test can catch it -- asserting on what
    the capsule contains cannot detect a line that was never emitted. The
    capsule-drift test (#293) is blind to it for the same reason: it validates
    the commands a capsule advertises, and this one advertises nothing.

    resume guarded on `["cleanup"]`, which is the internal module name; the CLI
    surface is `files tidy`. The entry never rendered, and the command it would
    have printed was wrong on the subcommand and both flags.

    This walks the AST for literal guard arguments and evaluates each against
    the domain's real parser, which is the only way this class of defect
    surfaces.
    """

    def _literal_guards(self, source: str):
        guards = []
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_cli_path_exists"
                and node.args
                and isinstance(node.args[0], ast.List)
            ):
                try:
                    guards.append(ast.literal_eval(node.args[0]))
                except ValueError:
                    continue  # non-literal (loop variable) -- covered elsewhere
        return guards

    def test_every_literal_guard_resolves_against_its_parser(self):
        root = pathlib.Path(__file__).resolve().parents[2] / "src"
        checked = 0
        for path in sorted(root.glob("*/agentic.py")):
            domain = path.parent.name
            guards = self._literal_guards(path.read_text())
            if not guards:
                continue
            mod = importlib.import_module(f"{domain}.agentic")
            checker = getattr(mod, "_cli_path_exists", None)
            if checker is None:
                continue
            for guard in guards:
                if not all(isinstance(e, str) for e in guard):
                    continue  # nested list: a different defect, pinned below
                with self.subTest(domain=domain, guard=guard):
                    self.assertTrue(
                        checker(guard),
                        f"{domain}.agentic guards on {guard!r}, which its parser "
                        "does not expose. The guard is silently False, so the "
                        "capsule drops that entry with no error and no failing "
                        "output assertion. Use the real CLI path.",
                    )
                    checked += 1
        self.assertGreater(checked, 0, "no guards were checked -- audit is vacuous")


class CliPathExistsContractTests(unittest.TestCase):
    """Pins the argument shape that caused resume's second, stacked bug."""

    def test_flat_path_matches(self):
        import resume.agentic as mod

        self.assertTrue(mod._cli_path_exists(["extract"]))

    def test_nested_path_raises_rather_than_quietly_missing(self):
        # resume/agentic.py passed [cmd] where cmd was already ["extract"],
        # producing [["extract"]]. cli_path_exists does choices.get(name), and
        # a list is unhashable -- so this raises TypeError rather than
        # returning False.
        #
        # That matters: the defect looked harmless only because the parser was
        # ALSO None, so cli_path_exists short-circuited at its `parser is None`
        # guard and never reached the dict lookup. Fixing the parser alone
        # would have turned a silently-empty flow map into a crashing one,
        # which is why both bugs had to be fixed in the same change.
        import resume.agentic as mod

        with self.assertRaises(TypeError):
            mod._cli_path_exists([["extract"]])  # type: ignore[list-item]

    def test_unknown_subcommand_is_false(self):
        import resume.agentic as mod

        self.assertFalse(mod._cli_path_exists(["definitely-not-a-command"]))


if __name__ == "__main__":
    unittest.main()
