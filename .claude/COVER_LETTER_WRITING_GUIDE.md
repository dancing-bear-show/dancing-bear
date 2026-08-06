# Cover Letter Writing Guide

Standards for cover letters and application notes that accompany a resume.

This is a companion to `.claude/RESUME_WRITING_GUIDE.md` and `.claude/WRITING_GUIDE.md`,
not a replacement. A cover letter is a third genre: it is prose, not fragments, and
its rules partly contradict the resume guide's. Where they conflict for a cover
letter, this guide wins.

**Where the three differ**:

| Rule | WRITING_GUIDE.md | RESUME_WRITING_GUIDE.md | This guide |
|------|------------------|-------------------------|------------|
| Voice | Explicit subject | Implied first person, never "I" | Explicit first person — "I built", "I've spent" |
| Form | Prose | Verb-first fragments, no periods | Full sentences and paragraphs |
| Numbers | Include units | Quantify half of all bullets | One or two anchor metrics, woven in — not a stat sheet |
| Openers | No constraint | Strong past-tense verb | Open on the reader's need, not "I am writing to apply" |
| Length | Soft | Hard character ceilings | 200–320 words, 3–4 paragraphs |

**What all three share**: no hollow enthusiasm, no thesaurus abuse, no hedging
stacks, no filler, and — above all — **never fabricate or inflate**. The resume
guide's banned phrases and the parent guide's "Don't Sound Like an LLM" rules apply
here too.

## The Job

A cover letter does one thing a resume cannot: it connects *this* candidate to
*this* role in a short argument. The resume is the evidence; the letter is the
claim the evidence supports. If a letter could be sent to any company with the name
swapped, it has failed — delete it and start from the role.

## Structure

Three or four paragraphs, in this order (the hook and proof may share a paragraph in a shorter letter):

1. **The hook** — open on what the role needs and the candidate's honest match for
   it. Mirror one specific line from the job description. Never open with "I am
   writing to apply for…" — the reader knows why the letter exists.
2. **The proof** — one concrete, verifiable story that demonstrates the hook.
   Prefer a system built or a problem owned end-to-end over a list of skills.
   Name it, give it one anchor metric, and connect its *shape* to the target role.
3. **The fit** — why this company specifically, in the candidate's real words.
   What about the team, product, or problem is a genuine draw. If nothing is, the
   candidate should not be applying, and no sentence will hide that.
4. **The close** — one line. "I'd welcome the chance to talk." No restating the
   resume, no thanking-in-advance paragraph.

## Voice and Confidence

- **Explicit first person, active voice.** "I built X", "I've spent my career on Y".
- **Calibrated, not salesy.** State what is true plainly; let the reader conclude
  it is impressive. "I built the remediation engine" lands harder than "I am an
  exceptional engineer who built…".
- **Dial confidence to the evidence.** A claim backed by a linked artifact can be
  stated flatly. A claim resting on a short tenure or a personal project should be
  worded to match — "a personal project", "exploring", "around 150 hours" — not
  puffed to sound like production scale.
- **Prefer measured verbs over superlatives.** "improve", "worked on", "explored"
  where they are accurate. Reserve "architected", "built", "owned" for work that
  genuinely was that.

## Honesty Checks (do these before sending)

The failure mode of a cover letter is a claim that reads well but collapses in the
interview. Run each check:

- **Timeline honesty.** Does any sentence imply a decade of experience with
  something the candidate has done for one year? Separate the durable skill (e.g.
  "a decade of distributed-systems reliability") from the recent one (e.g. "lately,
  with AI agents"). Never let an adjacent-clause juxtaposition fuse them.
- **Tenure proportionality.** A metric or scope claim attached to a short tenure
  invites "in three months?". Either surface earlier experience that supports it or
  word it so the tenure is not doing the load-bearing.
- **Artifact backs the claim.** Every named system should be verifiable — linked,
  published, or discussable in depth. If it cannot be defended in a deep-dive, soften
  or cut it.
- **Personal vs. professional.** Portfolio and side projects are legitimate proof,
  but label them as such ("a personal project"). Do not let them read as paid or
  production work, or as a team effort.
- **Lead with strengths, don't hide gaps dishonestly.** A letter need not enumerate
  every gap, but it must not imply a capability the candidate lacks. Genuine gaps
  belong in the interview or a single honest line, never in a fabricated claim.

## Tailoring

- **Reorder and reweight to the role — never fabricate.** Surfacing the true
  experience most relevant to *this* job is the entire task. Adding unearned claims
  is not tailoring, it is lying with better formatting.
- **Mirror the job description's language** only where it genuinely matches. If the
  posting says "build and operate", use "build and operate" — but only if both halves
  are true of the candidate.
- **One hook per letter.** Pick the single strongest honest angle (the mission, the
  reliability need, the build-pattern match) and commit. A letter hedging across
  three hooks argues none of them.

## Prose Hygiene

- **No keyword-stuffing in sentences.** A parenthetical tool list dropped into prose
  ("(beanstalkd for queuing, Couchbase for state)") reads as a resume smuggled into
  a paragraph. Let the architecture carry the meaning; let the resume and linked
  artifacts carry the stack.
- **No dated-tech name-drops** unless they serve the point. Naming decade-old tooling
  in prose can undercut a "current builder" impression; the resume can hold it.
- **Cut connective filler.** "It is worth noting that", "I would like to highlight",
  "As you can see from my resume" — delete. Every sentence should carry a claim.
- **One idea per sentence.** Long comma-spliced sentences with three subordinate
  clauses hide the point. Split them.

## Banned Openings

| Banned | Use instead |
|--------|-------------|
| I am writing to apply for the position of… | Open on the role's need and your match for it |
| I am the perfect candidate / a perfect fit | State the match; let the reader judge fit |
| I am passionate about… | Show the draw concretely, or cut it |
| As you can see from my resume… | The letter adds argument, not a resume recap |
| To whom it may concern | Address the team or hiring manager by the closest real name |
| With my extensive experience in a variety of… | Name the specific experience and count |

## Length

- **200–320 words is the usual target.** Long enough for one real story, short
  enough to read in under a minute. A fast-moving team reads the first two sentences
  and the close.
- **3–4 paragraphs.** More than four and the argument has diffused.
- **Shorter is fine when the evidence carries it.** If the resume and linked
  artifacts are strong, a 150–200 word letter that points to them can outperform a
  longer one. Length serves the argument, not the reverse — never pad to hit a count.

## Output

- Plain Markdown for pasting into an application form or email body is the default.
- Render a DOCX only when the application asks for an attached file; match the
  resume's formatting so the pair reads as one package.
- Keep the letter's claims consistent with the resume — a differing metric or title
  for the same accomplishment across the two documents is a credibility failure.
