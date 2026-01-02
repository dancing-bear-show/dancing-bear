# Tests

## Overview

Lightweight `unittest` suite focused on CLI parsing and small helpers.

## Running Tests

```bash
# All tests
make test

# With coverage
coverage run -m unittest discover && coverage report

# Specific module
python3 -m unittest discover tests/mail_tests

# Specific subdirectory
python3 -m unittest discover tests/phone_tests/layout
```

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

### Why Subdirectories?

1. **Discoverability** - Tests for `mail/filters/` live in `tests/mail_tests/filters/`
2. **Isolation** - Each subdirectory has its own fixtures without namespace pollution
3. **Selective testing** - Run just `python3 -m unittest discover tests/mail_tests/gmail`
4. **Parallel development** - Less merge conflicts than one giant test file
5. **LLM-friendly** - Focused context when asking an LLM to modify specific tests

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
