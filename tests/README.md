Tests

Overview
- Lightweight `unittest` suite focused on CLI parsing and small helpers.

Run
- `make test`
- Or: `python3 -m unittest tests/test_cli.py -v`

Guidelines
- Add tests only for new surfaces or behaviors.
- Keep execution fast; avoid network calls in tests.

