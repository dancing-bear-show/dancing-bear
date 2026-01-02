"""Tests for resume/model.py dataclass models."""

from __future__ import annotations

import unittest

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

    def test_with_values(self):
        exp = Experience(
            title="Senior Developer",
            company="TechCorp",
            start="2020",
            end="2023",
            location="San Francisco",
            bullets=["Built APIs", "Led team"],
        )
        self.assertEqual(exp.title, "Senior Developer")
        self.assertEqual(exp.company, "TechCorp")
        self.assertEqual(exp.start, "2020")
        self.assertEqual(exp.end, "2023")
        self.assertEqual(exp.location, "San Francisco")
        self.assertEqual(exp.bullets, ["Built APIs", "Led team"])

    def test_bullets_default_factory(self):
        exp1 = Experience()
        exp2 = Experience()
        exp1.bullets.append("Task 1")
        # Should not affect exp2's bullets (separate instances)
        self.assertEqual(exp2.bullets, [])

    def test_partial_values(self):
        exp = Experience(title="Developer", company="Startup")
        self.assertEqual(exp.title, "Developer")
        self.assertEqual(exp.company, "Startup")
        self.assertEqual(exp.start, "")
        self.assertEqual(exp.bullets, [])


class TestEducation(unittest.TestCase):
    """Tests for Education dataclass."""

    def test_default_values(self):
        edu = Education()
        self.assertEqual(edu.degree, "")
        self.assertEqual(edu.institution, "")
        self.assertEqual(edu.year, "")

    def test_with_values(self):
        edu = Education(
            degree="B.S. Computer Science",
            institution="MIT",
            year="2018",
        )
        self.assertEqual(edu.degree, "B.S. Computer Science")
        self.assertEqual(edu.institution, "MIT")
        self.assertEqual(edu.year, "2018")

    def test_partial_values(self):
        edu = Education(degree="MBA")
        self.assertEqual(edu.degree, "MBA")
        self.assertEqual(edu.institution, "")
        self.assertEqual(edu.year, "")


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

    def test_with_values(self):
        exp = Experience(title="Developer", company="TechCorp")
        edu = Education(degree="B.S.", institution="MIT")
        resume = Resume(
            name="John Doe",
            headline="Senior Software Engineer",
            email="john@example.com",
            phone="555-1234",
            location="San Francisco, CA",
            summary="10 years of experience...",
            skills=["Python", "Java"],
            experience=[exp],
            education=[edu],
        )
        self.assertEqual(resume.name, "John Doe")
        self.assertEqual(resume.headline, "Senior Software Engineer")
        self.assertEqual(resume.email, "john@example.com")
        self.assertEqual(resume.skills, ["Python", "Java"])
        self.assertEqual(len(resume.experience), 1)
        self.assertEqual(len(resume.education), 1)

    def test_skills_default_factory(self):
        r1 = Resume()
        r2 = Resume()
        r1.skills.append("Python")
        self.assertEqual(r2.skills, [])

    def test_experience_default_factory(self):
        r1 = Resume()
        r2 = Resume()
        r1.experience.append(Experience(title="Dev"))
        self.assertEqual(r2.experience, [])

    def test_education_default_factory(self):
        r1 = Resume()
        r2 = Resume()
        r1.education.append(Education(degree="BS"))
        self.assertEqual(r2.education, [])

    def test_full_resume_structure(self):
        resume = Resume(
            name="Jane Smith",
            headline="Full Stack Developer",
            email="jane@example.com",
            phone="555-5678",
            location="New York, NY",
            summary="Experienced full stack developer",
            skills=["Python", "React", "Docker"],
            experience=[
                Experience(
                    title="Senior Developer",
                    company="BigCo",
                    start="2020",
                    end="Present",
                    bullets=["Led team of 5", "Built microservices"],
                ),
                Experience(
                    title="Junior Developer",
                    company="Startup",
                    start="2018",
                    end="2020",
                    bullets=["Developed APIs"],
                ),
            ],
            education=[
                Education(degree="M.S. CS", institution="Stanford", year="2018"),
                Education(degree="B.S. CS", institution="Berkeley", year="2016"),
            ],
        )
        self.assertEqual(resume.name, "Jane Smith")
        self.assertEqual(len(resume.skills), 3)
        self.assertEqual(len(resume.experience), 2)
        self.assertEqual(len(resume.education), 2)
        self.assertEqual(resume.experience[0].title, "Senior Developer")
        self.assertEqual(resume.education[0].institution, "Stanford")


if __name__ == "__main__":
    unittest.main()
