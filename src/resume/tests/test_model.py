"""Tests for resume/model.py."""
import unittest
from dataclasses import fields

from resume.model import Experience, Education, Resume


class TestExperience(unittest.TestCase):
    """Tests for Experience dataclass."""

    def test_default_values(self):
        exp = Experience()
        self.assertEqual(exp.title, "")
        self.assertEqual(exp.company, "")
        self.assertEqual(exp.start, "")
        self.assertEqual(exp.end, "")
        self.assertEqual(exp.location, "")
        self.assertEqual(exp.bullets, [])

    def test_custom_values(self):
        exp = Experience(
            title="Software Engineer",
            company="TechCorp",
            start="2020",
            end="Present",
            location="San Francisco, CA",
            bullets=["Built APIs", "Led team"],
        )
        self.assertEqual(exp.title, "Software Engineer")
        self.assertEqual(exp.company, "TechCorp")
        self.assertEqual(exp.start, "2020")
        self.assertEqual(exp.end, "Present")
        self.assertEqual(exp.location, "San Francisco, CA")
        self.assertEqual(exp.bullets, ["Built APIs", "Led team"])

    def test_bullets_is_mutable_default(self):
        # Each instance should have its own bullets list
        exp1 = Experience()
        exp2 = Experience()
        exp1.bullets.append("Bullet 1")
        self.assertEqual(exp1.bullets, ["Bullet 1"])
        self.assertEqual(exp2.bullets, [])

    def test_has_expected_fields(self):
        field_names = {f.name for f in fields(Experience)}
        expected = {"title", "company", "start", "end", "location", "bullets"}
        self.assertEqual(field_names, expected)


class TestEducation(unittest.TestCase):
    """Tests for Education dataclass."""

    def test_default_values(self):
        edu = Education()
        self.assertEqual(edu.degree, "")
        self.assertEqual(edu.institution, "")
        self.assertEqual(edu.year, "")

    def test_custom_values(self):
        edu = Education(
            degree="B.S. Computer Science",
            institution="MIT",
            year="2015",
        )
        self.assertEqual(edu.degree, "B.S. Computer Science")
        self.assertEqual(edu.institution, "MIT")
        self.assertEqual(edu.year, "2015")

    def test_has_expected_fields(self):
        field_names = {f.name for f in fields(Education)}
        expected = {"degree", "institution", "year"}
        self.assertEqual(field_names, expected)


class TestResume(unittest.TestCase):
    """Tests for Resume dataclass."""

    def test_default_values(self):
        resume = Resume()
        self.assertEqual(resume.name, "")
        self.assertEqual(resume.headline, "")
        self.assertEqual(resume.email, "")
        self.assertEqual(resume.phone, "")
        self.assertEqual(resume.location, "")
        self.assertEqual(resume.summary, "")
        self.assertEqual(resume.skills, [])
        self.assertEqual(resume.experience, [])
        self.assertEqual(resume.education, [])

    def test_custom_values(self):
        exp = Experience(title="Engineer", company="Corp")
        edu = Education(degree="B.S.", institution="Univ")
        resume = Resume(
            name="John Doe",
            headline="Senior Engineer",
            email="john@example.com",
            phone="555-1234",
            location="New York, NY",
            summary="Experienced developer",
            skills=["Python", "Go"],
            experience=[exp],
            education=[edu],
        )
        self.assertEqual(resume.name, "John Doe")
        self.assertEqual(resume.headline, "Senior Engineer")
        self.assertEqual(resume.email, "john@example.com")
        self.assertEqual(len(resume.skills), 2)
        self.assertEqual(len(resume.experience), 1)
        self.assertEqual(resume.experience[0].title, "Engineer")
        self.assertEqual(len(resume.education), 1)
        self.assertEqual(resume.education[0].degree, "B.S.")

    def test_lists_are_independent(self):
        resume1 = Resume()
        resume2 = Resume()
        resume1.skills.append("Python")
        resume1.experience.append(Experience(title="Dev"))
        resume1.education.append(Education(degree="BS"))

        self.assertEqual(resume1.skills, ["Python"])
        self.assertEqual(resume2.skills, [])
        self.assertEqual(len(resume1.experience), 1)
        self.assertEqual(len(resume2.experience), 0)

    def test_has_expected_fields(self):
        field_names = {f.name for f in fields(Resume)}
        expected = {
            "name", "headline", "email", "phone", "location",
            "summary", "skills", "experience", "education"
        }
        self.assertEqual(field_names, expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
