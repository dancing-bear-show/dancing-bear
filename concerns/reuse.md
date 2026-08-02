# Reuse Review Guide

## When loaded

Load this guide when the diff contains `.py` files. All concerns apply to
non-test source files unless noted.

## Concerns

### intra-domain-duplicate
- **severity**: major
- **check**: Verify that a function or class added in one file of a domain does
  not duplicate an equivalent that already exists elsewhere in the same domain
  or in `core/`. Both cases mean any bug fix or behaviour change must be applied
  in multiple places and is easily missed. This concern covers: (1) intra-domain
  duplication — same function in two files of the same domain package, and (2)
  core-utility reimplementation — a domain module reimplements a helper already
  provided by `core/` (e.g. `read_yaml`, `write_yaml`, pipeline helpers).
- **triggers**: New `def ` or `class ` declarations in a domain file where a
  function with the same name or equivalent logic exists in a sibling file or
  in `core/`; utility functions (`_format_*`, `_parse_*`, `_build_*`) that
  operate on the same data type and appear in both CLI and module layers of the
  same domain.
- **example**: `_format_duration(seconds: int) -> str` defined independently in
  both a domain's CLI module and a helper module — fix by moving the shared
  helper to `core/` and importing it from both call sites. Also: a domain module
  that implements its own `read_yaml()` instead of importing from `core/`.

### bare-repeated-string
- **severity**: minor
- **scope**: Non-test source files only. Test files legitimately repeat fixture
  values and expected strings for readability — do not apply to `tests/`.
- **check**: Verify that string literals appearing 3+ times in a single file
  are extracted to a module-level constant. Repeated bare strings drift silently
  when one occurrence is updated without the others.
- **triggers**: The same non-trivial string value (`len > 4`, not an empty
  string or single punctuation character) appearing 3 or more times in a `.py`
  source file without a corresponding module-level constant; status strings,
  API field names, or log prefixes that are repeated inline.
- **example**: `"gmail_personal"` appears 4 times across a module with no
  `DEFAULT_PROFILE = "gmail_personal"` constant — updating the value requires
  4 edits. Fix: extract to a module-level constant and reference the symbol
  everywhere.
- **note**: This concern covers string repetition within a single file. For
  numeric literals that shadow a named constant, see `hardcoded-magic-constant`
  in `correctness.md`.

### promote-to-shared
- **severity**: minor
- **check**: Verify that constants, dataclasses, or small utility functions
  used by 2+ files within the same domain are placed in a shared module rather
  than defined in one file and imported by the other. The latter creates an
  implicit coupling between two non-shared files.
- **triggers**: `from mail.<module> import` or `from calendars.<module> import`
  in any sibling file of the same domain where the imported symbol is a
  constant, dataclass, or utility function (not a class that owns domain logic);
  dataclasses or enums whose definition file is not a shared module but that
  are imported by 2+ other files in the same domain.
- **example**: A plain dataclass defined in a domain's CLI module and then
  imported by a sibling helper module — because both CLI and helper use it,
  the dataclass belongs in a shared location within that domain or in `core/`.

### conftest-helper-duplication
- **severity**: minor
- **check**: Verify that test helper functions or fixtures defined in a top-level
  test file are not re-defined in a sub-test file within the same test tree.
  A top-level fixture is available to all tests under that directory — there is
  no need to redefine it lower down.
- **triggers**: A helper function with the same name appearing in both
  `tests/fixtures.py` and a domain-specific test helper; new test files added
  in a PR that define helpers already present in `tests/fixtures.py` or
  `tests/fakes/`.
- **example**: `make_label_payload()` defined in both `tests/fixtures.py` and
  `tests/test_mail_helpers.py` — tests using the local copy are silently
  unaffected by fixes to the shared fixture. Fix: remove the duplicate and
  import from the shared location.
- **note**: For missing factory usage in test bodies, see `test-data-builder-gap`
  in `tests.md`.

### decompose-shim-noqa-false-positive
- **severity**: minor
- **check**: Verify that `# noqa: F401` suppressions on re-exported symbols in decompose-sweep shim files are accompanied by a comment identifying the file as an intentional shim, so automated linters and future reviewers do not flag them as unused imports.
- **triggers**: Source files under any domain that import symbols solely to re-export them (created by the decompose-sweep refactor); `# noqa: F401` markers on multiple symbols in the same file without a module-level docstring or comment explaining the shim pattern; linter findings of 20+ unused-import warnings on a single file.
- **example**: A shim file carries 20+ `# noqa: F401` annotations with no module-level comment — reviewers cannot distinguish intentional re-exports from dead imports. Fix: add a module-level comment: `# Thin re-export shim created by decompose-sweep refactor. All imports are intentional backward-compat re-exports; # noqa: F401 markers are deliberate.` Only applies to files whose sole purpose is re-export; for genuinely unused imports suppressed by noqa, see `noqa-f401-on-used-import`.
