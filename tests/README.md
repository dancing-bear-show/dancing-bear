# Tests

## Overview

Lightweight `unittest` suite focused on CLI parsing and small helpers.

## Running Tests

```bash
# All tests (always use this)
make test

# With coverage
make cov

# Verify imports resolve to the current checkout
make check-env
```

**WARNING: never run bare `python3 -m unittest` in a worktree.** An inherited `PYTHONPATH` (from direnv or an active venv in the parent shell) silently resolves `core`/`mail`/`worker` to the main checkout's source. Tests pass against unmodified code — a false green indistinguishable from a real pass, and only fails when a newly added module is imported by name.

Use `make test`, or set the path explicitly:

```bash
PYTHONPATH="$PWD/src" python3 -m unittest discover -s tests
```

`make check-env` verifies imports resolve to the current checkout and fails loudly if not. This applies to subagents too.

## Test Organization

Tests are organized into **feature-based subdirectories** that mirror the source code:

```
tests/
├── mail_tests/           # Mail (Gmail/Outlook)
│   ├── accounts/         # Account management
│   ├── filters/          # Filter sync/export
│   ├── forwarding/       # Forwarding rules
│   ├── gmail/            # Gmail API client
│   ├── labels/           # Label management
│   ├── messages/         # Message operations
│   ├── outlook/          # Outlook integration
│   ├── signatures/       # Signature sync
│   └── fixtures.py       # Shared test fixtures
│
├── phone_tests/          # iOS phone layouts
│   ├── backup/           # Backup operations
│   ├── classify/         # App classification
│   ├── device/           # Device interaction
│   ├── layout/           # Layout parsing
│   ├── pipeline/         # Pipeline processing
│   └── fixtures.py       # Shared test fixtures
│
├── calendars_tests/      # Calendar operations
├── resume_tests/         # Resume builder
├── schedule_tests/       # Schedule assistant
└── ...
```

Subdirectories mirror source layout: tests for `mail/filters/` live in `tests/mail_tests/filters/`, each with its own `fixtures.py` to avoid namespace pollution.

## Fixtures

Shared test helpers live in each module's `fixtures.py`:

```python
from tests.mail_tests.fixtures import (
    make_success_envelope,    # Mock ResultEnvelope with ok()=True
    make_error_envelope,      # Mock ResultEnvelope with ok()=False
    make_mock_mail_context,   # Mock MailContext with clients
    make_message_with_headers,# Gmail message dict with headers
    FakeGmailClient,          # Fake Gmail client for testing
    NESTED_LABELS,            # Test data: ["A", "A/B", "A/B/C"]
)
```

## Guidelines

- Add tests only for new surfaces or behaviors
- Keep execution fast; avoid network calls
- Use fixtures for common mock patterns
- Name test files `test_*.py`
