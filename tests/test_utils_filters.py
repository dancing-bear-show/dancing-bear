import unittest


class TestUtilsFilters(unittest.TestCase):
    def test_categories_to_system_labels(self):
        from mail_assistant.utils.filters import categories_to_system_labels

        self.assertEqual(categories_to_system_labels({}), [])
        self.assertEqual(categories_to_system_labels({"categorizeAs": "promotions"}), ["CATEGORY_PROMOTIONS"])
        self.assertEqual(
            sorted(categories_to_system_labels({"categories": ["updates", "forums", "x"]})),
            ["CATEGORY_FORUMS", "CATEGORY_UPDATES"],
        )
        self.assertEqual(categories_to_system_labels({"categorize": "social"}), ["CATEGORY_SOCIAL"])

