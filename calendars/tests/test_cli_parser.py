import unittest

from calendars.__main__ import app


def _has_subcommand(parser, path):
    cur = parser
    for name in path:
        sub = None
        for act in getattr(cur, "_actions", []):
            if act.__class__.__name__.endswith("SubParsersAction"):
                sub = act
                break
        if not sub:
            return False
        cur = getattr(sub, 'choices', {}).get(name)
        if cur is None:
            return False
    return True


class TestCLIParser(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = app.build_parser()

    def test_outlook_add_exists(self):
        self.assertTrue(_has_subcommand(self.parser, ["outlook", "add"]))

    def test_outlook_add_recurring_exists(self):
        self.assertTrue(_has_subcommand(self.parser, ["outlook", "add-recurring"]))

    def test_outlook_reminders_off_exists(self):
        # Either reminders-off or reminders-set may exist depending on version
        exists = _has_subcommand(self.parser, ["outlook", "reminders-off"]) or _has_subcommand(self.parser, ["outlook", "reminders-set"]) 
        self.assertTrue(exists)

    def test_gmail_scan_classes_exists(self):
        self.assertTrue(_has_subcommand(self.parser, ["gmail", "scan-classes"]))


if __name__ == '__main__':  # pragma: no cover
    unittest.main()

