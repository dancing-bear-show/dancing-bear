# Resume Copy Review Guide

## When loaded

Load this guide when the diff adds or modifies resume or profile copy:
`src/resume/config/profiles/**/*.yaml`, `src/resume/config/template.*.yaml`,
`src/resume/config/*.example.yaml`, or `src/resume/examples/*`.

Standards are defined in `.claude/RESUME_WRITING_GUIDE.md`. Load alongside
`docs.md` when the diff also touches `.md` files.

**Scope note**: these concerns apply to *content* fields — `bullets`, `summary`,
`headline`, `skills`. Do NOT flag structural/schema keys, rendering config
(fonts, margins, column widths), or test fixtures whose purpose is to exercise
a parser with deliberately malformed input.

## Concerns

### resume-bullet-weak-opener
- **severity**: major
- **check**: Verify every entry under an `experience[].bullets` list opens with a
  strong verb. Ownership-distancing openers understate the candidate's role and
  are the most common resume-copy defect.
- **triggers**: A bullet begins (case-insensitive) with any of: "Responsible for",
  "Helped", "Assisted", "Worked on", "Involved in", "Participated in", "Tasked with",
  "Duties included", "Contributed to". Also triggers on a bullet opening with an
  article ("A", "An", "The") or a gerund ("Building", "Managing") rather than a
  finite verb.
- **tense**: Do NOT flag tense on the current role (the entry with `end: Present`).
  Both readings are correct there — ongoing duties take present tense ("Operate
  Kafka clusters"), completed accomplishments take past tense ("Delivered $300K in
  savings"). Only flag a present-tense opener on a role that has *ended*.
- **shared-credit exception**: "Contributed to" is accurate, not evasive, when
  the candidate genuinely shared the work — an upstream open-source project, a
  cross-team program they did not lead. Flagging it there pushes the candidate
  toward a false claim of sole ownership, which is worse than a weak opener.
  Flag it when it distances the candidate from work they actually owned. This
  concern owns "Contributed to" outright; `resume-hedged-impact` deliberately
  does not list it, so the two lanes cannot reach opposite verdicts on one
  bullet.
- **example**: `- Responsible for maintaining the Kafka clusters` — describes
  proximity to the work, not ownership of it. Rewrite: `- Operated Kafka clusters
  serving 40K msg/sec across three regions`.

### resume-bullet-unquantified
- **severity**: minor
- **check**: Verify that at least half the bullets in each `experience[]` entry
  contain a number. Report per-role, not per-bullet — a single unquantified bullet
  is fine; a role where none are quantified is the finding.
- **triggers**: An `experience[]` entry where fewer than 50% of `bullets` contain a
  digit, a spelled-out quantity, or a magnitude token (`$`, `%`, `K`, `M`, `x`).
  Skip roles with fewer than 3 bullets and skip the most distant role in the list.
- **example**: A role with bullets "Built SLOs and alerts for core services",
  "Automated infrastructure provisioning", "Partnered with developers to improve
  reliability" — 0/3 quantified. At least two should carry a metric: "Cut alert
  volume 60% by replacing threshold alerts with SLO burn-rate alerts".

### resume-banned-phrase
- **severity**: minor
- **check**: Verify resume and profile copy avoids unfalsifiable filler and
  thesaurus abuse. Flag every instance, not just the first.
- **triggers**: Any of the following in a `bullets`, `summary`, or `headline`
  value: "utilize", "leverage" (as a verb), "facilitate", "spearheaded",
  "championed", "team player", "self-starter", "results-driven", "detail-oriented",
  "proven track record", "passionate about", "synergy", "best-in-class",
  "world-class", "cutting-edge", "state-of-the-art", "various", "several",
  "multiple" (where a count is knowable).
- **scope exception**: Do NOT flag occurrences inside `.claude/RESUME_WRITING_GUIDE.md`
  or this file, which necessarily quote these phrases as examples. Exclude fenced
  code blocks and inline code spans.
- **example**: `- Leveraged various cutting-edge tools to facilitate deployments`
  — flags three banned phrases and hides the actual work. Rewrite: `- Cut deploy
  time from 40min to 6min with Terraform and ArgoCD`.

### resume-bullet-too-long
- **severity**: minor
- **check**: Verify no `bullets` entry exceeds 28 words. Long bullets stop being
  scannable and usually contain two accomplishments that should be split.
- **triggers**: A bullet whose whitespace-delimited word count exceeds 28; or a
  bullet containing two independent clauses that each carry their own metric.
- **example**: A 40-word bullet joining an EKS migration and a GC tuning project
  with "and" — split into two bullets, each with its own metric.

### resume-bullet-terminal-period
- **severity**: minor
- **check**: Verify bullets are punctuated consistently. Resume bullets are
  fragments and take no terminal period; mixing styles within one document reads
  as careless.
- **triggers**: Within a single profile directory, some `bullets` entries end with
  `.` and others do not. Flag the inconsistency, or flag terminal periods
  uniformly if the profile has no established convention.
- **example**: `- Built SLOs for core services.` alongside `- Operated Kubernetes
  clusters` — pick one. Preferred: no terminal period.

### resume-first-person-pronoun
- **severity**: major
- **check**: Verify resume `bullets` and `summary` use implied first person. An
  explicit "I" or a self-referential proper name in resume copy is a genre error.
- **triggers**: A `bullets` or `summary` value containing a standalone "I", "my",
  "me", or the candidate's own `name` value from `profile.yaml`.
- **scope exception**: LinkedIn About copy (a `linkedin.about` field or equivalent)
  SHOULD use first person — do not flag "I" there. This concern targets resume
  surfaces only.
- **example**: `- I architected the auto-remediation engine` — rewrite as
  `- Architected the auto-remediation engine`.

### resume-inconsistent-tech-naming
- **severity**: minor
- **check**: Verify technology names use canonical vendor spelling and stay
  consistent across the profile. Recruiter and ATS keyword matching is literal, so
  a non-canonical spelling can drop the candidate from a search.
- **triggers**: Miscased or misspelled vendor names anywhere — "terraform"
  (Terraform), "kafka" (Kafka), "javascript" (JavaScript), "github" (GitHub),
  "postgres" (PostgreSQL). Also: an abbreviation such as "k8s" or "OTEL" used in a
  skills list or section heading, where the canonical name is what a recruiter
  search matches.
- **abbreviation exception**: Per `.claude/RESUME_WRITING_GUIDE.md`, an
  abbreviation is acceptable *inside a bullet* once the canonical name has appeared
  earlier in the same document. Do NOT flag "k8s" in a bullet if "Kubernetes"
  appears in the skills list or an earlier bullet. Flag it only when no canonical
  mention exists anywhere in the profile.
- **example**: `experience.yaml` bullets say "k8s" and no file in the profile
  directory ever says "Kubernetes" — the profile will miss a literal recruiter
  search for Kubernetes. Add the canonical name to the skills list, or use it on
  first mention.

### resume-date-inconsistency
- **severity**: major
- **check**: Verify date fields are internally consistent and use one format.
  Recruiters compare resume dates against LinkedIn, and mismatches read as
  fabrication rather than sloppiness.
- **triggers**: Mixed date formats within one profile (`2021` vs `Jan 2021` vs
  `01/2021`); an `end` date earlier than its `start`; overlapping tenure at two
  full-time roles with no explanation; a gap longer than six months between
  consecutive roles; more than one entry with `end: Present`; or a
  publication/presentation date falling outside the tenure of the role it is
  attributed to.
- **example**: `presentations.yaml` dates a talk to 2015 while `experience.yaml`
  shows the attributed employer ending in 2013 — one of the two is wrong.

### resume-unverifiable-metric
- **severity**: critical
- **check**: Verify that quantified claims added or modified in a diff are
  plausible and internally consistent. Inflated or invented metrics are the
  highest-consequence defect in this genre — they survive review and fail in a
  reference check.
- **triggers**: A metric changed in the diff without a corresponding source change
  (e.g. `$300K` becomes `$3M`); a metric that contradicts another bullet in the
  same profile; a percentage above 100 for a reduction; team-size or scale figures
  inconsistent between the summary and the role bullets.
- **note**: Flag for author confirmation rather than asserting the number is false —
  the reviewer cannot verify external facts. Phrase findings as "confirm this
  figure" and cite the conflicting value.
- **example**: `profile.yaml` summary says "grew team to 9 engineers" while
  `experience.yaml` says "grew team from 1 to 12" — one figure is stale.

### linkedin-surface-over-limit
- **severity**: major
- **check**: Verify LinkedIn-destined copy fits platform character limits. Copy
  over the limit is silently truncated mid-word on the live profile.
- **triggers**: A headline value over 220 characters; an About/summary value over
  2,600 characters; a per-role LinkedIn bullet block over 2,000 characters; a
  skills list over 50 entries.
- **applies to**: `profile.yaml` `headline`, and any LinkedIn profile YAML
  following `src/resume/config/linkedin.example.yaml` — including real profiles
  under `src/resume/_data/profiles/**`, which a local review will see even though a
  PR diff will not (that tree is ignored via `src/resume/.gitignore` line 2,
  `_data/`).
- **note**: Where a `chars:` field accompanies `headline`, verify it matches the
  actual character count of `text:` — a stale count hides an over-limit headline.
- **example**: A 340-character headline renders as roughly 220 characters plus an
  ellipsis in search results, cutting off the differentiator.

### linkedin-resume-drift
- **severity**: major
- **check**: Verify LinkedIn copy does not contradict the resume. Differing metrics
  or titles for the same accomplishment are a credibility failure, unlike mere
  differences in length or emphasis.
- **triggers**: The same role carrying different titles, dates, or metrics between
  a resume profile and a LinkedIn profile YAML; a role present in one source and
  absent from the other.
- **applies to**: any LinkedIn profile YAML following
  `src/resume/config/linkedin.example.yaml`, compared against the resume profile in
  the same tree. Real profiles live under `src/resume/_data/profiles/**`, ignored
  via `src/resume/.gitignore` line 2 (`_data/`), so this concern fires during local
  review but usually not from a PR diff alone.
- **provenance rule**: Do NOT report drift against a field tagged `unverified`,
  `unverified-possibly-empty`, or `dates_source: resume-not-linkedin` — those record
  what could not be read, not what the profile says. Flagging them produces findings
  about the capture rather than the profile. A field tagged `presence_on_linkedin:
  absent-in-preview` IS reportable: a resume role missing from the profile is the
  defect this concern exists to catch.
- **example**: Resume says "Senior Staff Site Reliability Engineer, Nov 2020 – May
  2025"; LinkedIn says "Staff SRE, 2021 – 2025" — title and both dates disagree.

### resume-verb-repetition
- **severity**: minor
- **check**: Verify the resume does not lean on the same opener across bullets.
  A reader scanning the left edge of a bullet list sees the verbs first, and a
  column reading "Led / Led / Led / Led" flattens four different accomplishments
  into one texture.
- **triggers**: The same opening verb (or its lemma — "Build"/"Built"/"Building")
  opening 3+ bullets anywhere in the document, or 3+ bullets within a single
  `experience[]` entry. Report the verb, the count, and every role it appears in.
- **threshold note**: 3+, matching `resume-bullet-template-repetition`. Two
  bullets sharing an opener is the same coincidence two bullets sharing a shape
  is, and this concern previously said 2+ within a role while its sibling said
  two is parallelism — one document could satisfy both rules and contradict
  itself. The two concerns do measure different things (verb identity versus
  sentence shape, so one bullet can trip both), but they now agree on how much
  repetition constitutes a pattern.
- **scope exception**: Do NOT flag a verb repeated across roles when it is the
  literal name of the work and no honest synonym exists ("Migrated" across three
  migration roles). Flag only when substitution would not change the claim.
- **note**: Rank by span. The same verb twice in one role reads as a lapse; the
  same verb six times across a document reads as a template.
- **example**: A resume whose bullets open "Led the migration...", "Led a team
  of 6...", "Led incident response...", "Led the SLO rollout..." — four distinct
  accomplishments rendered indistinguishable. Vary to "Migrated", "Grew",
  "Ran", "Drove".

### resume-bullet-template-repetition
- **severity**: minor
- **check**: Verify bullets do not all share one syntactic template. Identical
  structure across a list is the strongest single tell that copy was generated
  rather than written, and it survives every word-level check because no
  individual bullet is wrong.
- **triggers**: 3+ bullets in the same `experience[]` entry sharing a template,
  most commonly `<Verb> <object> by <gerund> <method>, resulting in <metric>` or
  `<Verb> <object>, <gerund> <outcome>`. Also triggers when every bullet in a
  role terminates in a metric clause in the same grammatical position.
- **scope exception**: Two bullets sharing a shape is normal parallelism and is
  not a finding. The concern is a whole list marching in lockstep.
- **note**: The fix is structural, not lexical — swapping synonyms leaves the
  template intact. Lead one bullet with the outcome, one with the constraint,
  one with the scope. When reporting this as a finding, `suggested_rewrite` is a
  single string: rewrite the one quoted bullet and name the pattern in `why`.
  The schema cannot carry a multi-bullet rewrite.
- **example**: "Reduced latency by implementing caching, resulting in 40% faster
  loads" / "Cut costs by consolidating instances, resulting in $200K savings" /
  "Improved uptime by adding health checks, resulting in 99.9% availability" —
  three bullets, one sentence, three times.

### resume-llm-cadence
- **severity**: minor
- **check**: Verify the copy does not carry the characteristic rhythms of
  generated prose. These are individually defensible and collectively damning:
  a recruiter cannot always name why a resume reads as machine-written, but
  they register it.
- **triggers**: Any of — a tricolon ("scalable, reliable, and maintainable")
  where two adjectives would carry the claim; the "not just X, but Y"
  construction; "seamlessly", "robust", "comprehensive", "holistic",
  "streamlined" as intensifiers rather than technical terms; an em dash used
  for dramatic pause in a bullet; a bullet opening with a participial scene-set
  ("Recognizing the need for...", "Understanding that...").
- **scope exception**: A term is not a tell when it is the actual technical
  word — "robust" in "robust statistics", "comprehensive" in "comprehensive
  test coverage" where coverage is genuinely exhaustive. Judge by whether
  deleting the word loses information.
- **punctuation exception**: The em dash is ordinary English punctuation and is
  used throughout this repo's own guides. Flag it ONLY where it sets up a
  rhetorical reveal in a resume bullet ("delivered the platform — and then
  scaled it"). Never flag an em dash joining two clauses of ordinary prose, and
  never flag the EN dash in a date range (`2021 – 2025`), which
  `.claude/RESUME_WRITING_GUIDE.md` mandates and which
  `ats-date-format-unparseable` separately governs. Flagging the mandated date
  format would put two lanes in direct conflict over the same characters.
- **note**: Do not flag the same span under both this concern and
  `resume-banned-phrase`; that concern owns the fixed vocabulary list, this one
  owns rhythm and construction.
- **example**: "Architected a scalable, reliable, and maintainable platform —
  not just meeting requirements, but seamlessly exceeding them" — every clause
  defensible in isolation, unmistakable in aggregate.

### resume-hedged-impact
- **severity**: major
- **check**: Verify accomplishments are stated as fact rather than softened into
  unfalsifiability. Generated copy hedges by default, and a hedged metric is
  worse than no metric: it signals the writer did not trust the number.
- **triggers**: A bullet containing "helped to", "played a key role in", "was
  instrumental in", "supported efforts to", "approximately" before a figure the
  candidate should know exactly, or "up to" attached to a best case presented as
  typical.
- **boundary**: "Contributed to" is NOT listed here. It is an opener word by
  definition and belongs to `resume-bullet-weak-opener`, which owns it together
  with its shared-credit exception. Listing it in both places made the same
  bullet a mandatory finding for one lane and a mandatory non-finding for the
  other.
- **scope exception**: Genuine shared credit is honest and must not be flagged
  into a false claim of sole ownership. The defect is hedging work the candidate
  actually owned, not accurately describing work they shared.
- **note**: Overlaps `resume-bullet-weak-opener` when the hedge is the opener.
  Report under that concern when it opens the bullet, here when it appears
  mid-bullet.
- **example**: "Helped to reduce infrastructure costs by approximately 30%" —
  either the candidate cut costs 30% or they did not, and either they know the
  figure or should not cite it. Rewrite: "Cut infrastructure costs 31% ($240K
  annualized)".
