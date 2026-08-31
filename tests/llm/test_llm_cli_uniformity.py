"""Structural guard: every domain llm_cli is built from the shared factory.

Each ``src/<app>/llm_cli.py`` used to hand-roll its own agentic / domain-map /
inventory / familiar / policies builders. That duplication drifted: one module
placed its ``from .agentic import ...`` outside the ``try``, so an ImportError
propagated instead of falling back to the static capsule, and another fell back
to the empty string where every sibling returned real content.

``core.llm_builders.make_domain_llm_module`` is the single source of those
builders. These tests fail if a new app reintroduces a hand-rolled module.
"""

from __future__ import annotations

import importlib
import pathlib
import unittest

# Modules that legitimately do not call make_domain_llm_module.
#   core - defines the factory and LlmConfig themselves.
#   mail - a deliberate re-export shim over core.llm_cli, kept because
#          `llm --app mail` dispatches to it by name.
EXEMPT = {"core", "mail"}

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"


def _domain_llm_packages() -> list[str]:
    return sorted(
        p.parent.name
        for p in SRC.glob("*/llm_cli.py")
        if p.parent.name not in EXEMPT
    )


class TestLlmCliUniformity(unittest.TestCase):
    def test_discovery_finds_the_expected_packages(self):
        # Guards the guard: if the glob silently matched nothing, every
        # subTest below would vacuously pass.
        packages = _domain_llm_packages()
        self.assertGreaterEqual(
            len(packages), 8, f"expected the full domain set, found {packages}"
        )
        self.assertIn("phone", packages)

    def test_every_domain_module_exposes_the_shared_contract(self):
        for pkg in _domain_llm_packages():
            with self.subTest(package=pkg):
                mod = importlib.import_module(f"{pkg}.llm_cli")
                self.assertTrue(
                    hasattr(mod, "CONFIG"),
                    f"{pkg}.llm_cli must expose CONFIG from make_domain_llm_module",
                )
                for entrypoint in ("build_parser", "main"):
                    self.assertTrue(
                        callable(getattr(mod, entrypoint, None)),
                        f"{pkg}.llm_cli must bind {entrypoint} via bind_entrypoints",
                    )

    def test_no_module_hand_rolls_the_shared_builders(self):
        # The factory supplies these; a module defining its own has forked it.
        forbidden = ("_agentic", "_domain_map", "_inventory", "_policies")
        for pkg in _domain_llm_packages():
            with self.subTest(package=pkg):
                mod = importlib.import_module(f"{pkg}.llm_cli")
                rolled = [name for name in forbidden if hasattr(mod, name)]
                self.assertEqual(
                    rolled,
                    [],
                    f"{pkg}.llm_cli hand-rolls {rolled}; use "
                    f"make_domain_llm_module instead",
                )

    def test_builders_return_content_not_empty_string(self):
        # maker previously fell back to "" for these when .llm/* was absent.
        for pkg in _domain_llm_packages():
            with self.subTest(package=pkg):
                config = importlib.import_module(f"{pkg}.llm_cli").CONFIG
                for field in (
                    "agentic",
                    "domain_map",
                    "inventory",
                    "familiar_compact",
                    "familiar_extended",
                    "policies",
                ):
                    value = getattr(config, field)()
                    self.assertIsInstance(value, str)
                    self.assertTrue(
                        value.strip(), f"{pkg}.CONFIG.{field}() returned blank"
                    )

    def test_agentic_falls_back_when_the_agentic_module_is_broken(self):
        # The regression that motivated this file: phone imported outside the
        # try, so a broken agentic module raised instead of falling back.
        from core.llm_builders import DomainLlmConfig, make_domain_llm_module

        config = make_domain_llm_module(
            DomainLlmConfig(
                app_id="probe",
                app_title="Probe",
                purpose="probe purpose",
                agentic_module="probe.does_not_exist",
            )
        )
        self.assertEqual(config.agentic(), "agentic: probe\npurpose: probe purpose")
        self.assertEqual(config.domain_map(), "Domain Map not available")


if __name__ == "__main__":
    unittest.main(verbosity=2)
