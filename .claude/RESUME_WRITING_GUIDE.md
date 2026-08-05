# Resume & Profile Writing Guide

Standards for resume and professional-profile copy: `src/resume/config/profiles/**`
YAML, rendered DOCX output, and LinkedIn profile surfaces.

This is a companion to `.claude/WRITING_GUIDE.md`, not a replacement. That guide
governs engineering artifacts — commits, PRs, READMEs, code comments, CLI output.
Resume copy is a different genre with partly contradictory rules, so it lives here.

**Where the two differ**:

| Rule | WRITING_GUIDE.md | This guide |
|------|------------------|------------|
| Sentence subject | Full sentences with explicit subject | Implied first person, never "I" |
| Bullet openers | No constraint | Strong past-tense verb, always |
| Trailing periods | Normal punctuation | No terminal period on bullets |
| Length limits | Soft (be concise) | Hard per-surface character ceilings |
| Numbers | Include units | Quantify at least half of all bullets |

**What both guides share**: no hollow enthusiasm, no thesaurus abuse, no hedging
stacks, no filler. Those anti-patterns from `WRITING_GUIDE.md` apply here too.

## Voice

- **Implied first person** — "Built X", never "I built X" and never "Brian built X"
- **Past tense for prior roles.** In the current role, both are correct: present
  tense for ongoing duties ("Operate Kafka clusters"), past tense for completed
  accomplishments ("Delivered $300K in savings"). Don't force one or the other.
- **Active voice throughout** — "Cut $1M in spend", not "Spend was reduced"
- **No articles at bullet start** — "Built the pipeline" not "A pipeline was built"
- Third person is acceptable in a LinkedIn About section only if used consistently;
  first person is preferred there (see LinkedIn Surfaces below)

## Bullets

- **Open with a strong verb.** Architected, built, delivered, drove, founded, cut,
  operated, established, reduced, shipped, led, automated, instrumented.
- **Never open with**: "Responsible for", "Helped with", "Worked on", "Assisted in",
  "Participated in", "Involved in", "Tasked with". These describe proximity to work
  rather than ownership of it.
- **One accomplishment per bullet.** If a bullet has two "and"-joined clauses that
  each carry their own metric, split it.
- **28 words maximum.** Longer bullets stop being scannable.
- **No terminal period.** Bullets are fragments, not sentences.
- **3–6 bullets per role**, weighted toward recent roles. A role from 15 years ago
  needs one or two, not five.

## Quantification

- **At least half the bullets in each role must carry a number.** Dollar amounts,
  percentages, counts, time saved, team size, scale.
- Prefer **outcome metrics over activity metrics** — "$300K in AWS savings" beats
  "reviewed 40 dashboards".
- Include the **unit and the baseline** where the number is meaningless without it:
  "grew team from 1 to 9" not "grew team by 8".
- Round sensibly: "$1M annually", "150+ hours weekly", "~$300K".
- **Never invent or inflate a number.** If a metric is not verifiable, write the
  bullet without one rather than estimating. Unverifiable numbers are the single
  highest-risk item in this genre.

## Banned Phrases

| Banned | Use instead |
|--------|-------------|
| Responsible for X | Verb the X directly: "Owned X", "Operated X" |
| Helped with / Assisted in | Name the specific contribution |
| Worked on / Involved in | State what was built or changed |
| Utilize / Leverage | Use |
| Facilitate | Ran, led, enabled |
| Spearheaded / Championed | Led, drove, founded |
| Team player, self-starter, go-getter | Delete — show it in a bullet instead |
| Results-driven, detail-oriented | Delete — unfalsifiable filler |
| Proven track record | Delete — the bullets are the record |
| Synergy, best-in-class, world-class | Delete |
| Passionate about | Delete |
| Various / several / multiple | Give the actual count |
| Cutting-edge, state-of-the-art | Name the technology |

## Skills & Technology Naming

- **Use canonical vendor spelling**: Kubernetes, Kafka, PostgreSQL, OpenTelemetry,
  Terraform, Grafana, JavaScript. Not k8s, kafka, postgres, OTEL, terraform.
- Exception: within a bullet, an abbreviation is fine after the full name has
  appeared once in the same document.
- **Don't pad skill lists.** A skill a recruiter will screen on belongs; a skill
  used once in 2011 does not.
- Keep skill names consistent between the resume YAML and the LinkedIn profile —
  search matching is literal.

## Dates & Consistency

- **One date format per document.** `Month YYYY – Month YYYY`, with `Present` for
  current roles.
- **No unexplained gaps** longer than six months between roles.
- Dates in the resume and on LinkedIn must match. Recruiters compare them.
- A project or publication date must fall within the tenure of the role it is
  attributed to.

## LinkedIn Surfaces

LinkedIn has hard platform limits. Copy that exceeds them is silently truncated
mid-word in the reader's feed.

| Surface | Limit | Notes |
|---------|-------|-------|
| Headline | 220 chars | Front-load the role and the differentiator; pipe-separated segments scan well |
| About | 2,600 chars | First person, prose not bullets, 3–5 short paragraphs |
| Experience bullet | 2,000 chars per role | Same bullet rules as the resume |
| Skills | 50 max | Top 3 are pinned and weighted most in search |

**Headline**: name the current role, the differentiator, and the top two or three
technologies. Avoid a bare job title — it wastes the most-indexed field on the
profile.

**About**: unlike the resume, write in explicit first person ("I build systems
that…"). Open with the thesis, not a job history. Close with what you're working
on now. Bullet lists read as a pasted resume and should be avoided.

**Resume/profile parity**: every role, title, and date on the resume should appear
on LinkedIn. Bullets may be shortened for LinkedIn but must not contradict the
resume — differing metrics for the same accomplishment is a credibility failure.

## Section Ordering

Lead with what the reader is screening for:

1. Contact and headline
2. Profile / summary (3–6 lines, skimmable)
3. Core abilities or skills, grouped by theme
4. Professional experience, reverse chronological
5. Education
6. Notable work, publications, speaking
7. Interests (optional, brief)

Publications and conference talks are strong differentiators and should never be
buried below interests.

## Tailoring

- When aligning to a job description, **reorder and reweight — never fabricate**.
  Surfacing relevant true bullets is tailoring; adding unearned ones is not.
- Mirror the job description's vocabulary where it genuinely matches your
  experience — literal keyword matching drives most applicant screening.
- Keep one canonical profile YAML as the source of truth; tailored variants derive
  from it rather than drifting independently.
