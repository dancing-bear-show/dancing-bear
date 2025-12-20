import unittest

try:
    from resume_assistant.resume_assistant import parsing
except ModuleNotFoundError:
    from resume_assistant import parsing


class TestParsing(unittest.TestCase):
    def test_parse_linkedin_text_sections(self):
        text = """Jane Doe
Contact
jane@example.com | (555) 123-4567 | Denver, CO

Summary
Cloud engineer focused on AWS.

Skills
Python, AWS; Docker

Experience
Senior Engineer at ExampleCorp (2020-2023) - Remote
- Built services

Education
BS Computer Science, Example University, 2015
"""
        out = parsing.parse_linkedin_text(text)
        self.assertEqual(out["name"], "Jane Doe")
        self.assertEqual(out["email"], "jane@example.com")
        self.assertEqual(out["location"], "Denver, CO")
        self.assertIn("Cloud engineer", out["summary"])
        self.assertEqual(out["skills"], ["Python", "AWS", "Docker"])
        self.assertEqual(out["experience"][0]["title"], "Senior Engineer")
        self.assertEqual(out["experience"][0]["company"], "ExampleCorp")
        self.assertEqual(out["experience"][0]["start"], "2020")
        self.assertEqual(out["experience"][0]["end"], "2023")
        self.assertIn("Built services", out["experience"][0]["bullets"][0])
        self.assertEqual(out["education"][0]["institution"], "Example University")

    def test_parse_resume_text_summary(self):
        text = """Alex Smith
alex@example.com | (555) 555-5555 | Austin, TX

Summary
Backend engineer building APIs.

Skills
Go, PostgreSQL

Experience
Staff Engineer at Acme (2019-2022) - Remote
- Built APIs
"""
        out = parsing.parse_resume_text(text)
        self.assertEqual(out["name"], "Alex Smith")
        self.assertEqual(out["email"], "alex@example.com")
        self.assertEqual(out["location"], "Austin, TX")
        self.assertIn("Backend engineer", out["summary"])
        self.assertEqual(out["skills"], ["Go", "PostgreSQL"])
        self.assertEqual(out["experience"][0]["company"], "Acme")

    def test_parse_linkedin_html_meta(self):
        html = """<html><head>
<meta property="profile:first_name" content="Jamie">
<meta property="profile:last_name" content="Doe">
<meta property="og:title" content="Jamie Doe - Platform Engineer | LinkedIn">
<meta name="description" content="Platform engineer - Location: Seattle, WA - Experience: Example">
</head></html>"""
        out = parsing.parse_linkedin_text(html)
        self.assertEqual(out["name"], "Jamie Doe")
        self.assertEqual(out["headline"], "Platform Engineer")
        self.assertEqual(out["summary"].split(" - ")[0], "Platform engineer")

    def test_merge_profiles_prefers_linkedin_identity(self):
        linkedin = {"name": "LinkedIn Name", "headline": "SRE", "skills": ["Python", "AWS"]}
        resume = {"name": "Resume Name", "skills": ["Go", "AWS"]}
        merged = parsing.merge_profiles(linkedin, resume)
        self.assertEqual(merged["name"], "LinkedIn Name")
        self.assertEqual(merged["headline"], "SRE")
        self.assertEqual(merged["skills"], ["Go", "AWS", "Python"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
