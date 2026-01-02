# Getting Started with Dancing Bear

> *You don't need to outrun the bear. You just need to outrun everyone else.*

This guide gets you from zero to productive in 10 minutes.

## What Is This?

**Dancing Bear** is a collection of command-line tools that automate tedious personal tasks. It's also a demonstration of **LLM-first development** - the entire codebase was built using Claude Code as the primary coding interface.

**Core tools:**
- **Resume building** - Extract LinkedIn data, align with job postings, render tailored DOCX resumes
- **Email management** - Sync Gmail/Outlook filters and labels from a single YAML file
- **iOS phone layouts** - Export, plan, and apply home screen configurations

**Experimental:**
- Calendar scheduling, WhatsApp search, precious metals tracking, WiFi diagnostics

The key idea: **define your intent in YAML, preview changes safely, then apply.**

Every destructive action has a `--dry-run` or `plan` step first. You won't accidentally delete your inbox.

## Prerequisites

- **Python 3.11+** installed
- **Git** to clone the repo
- A terminal (macOS Terminal, iTerm2, Windows Terminal, etc.)

## Step 1: Clone and Set Up

```bash
# Clone the repository
git clone https://github.com/dancing-bear-show/dancing-bear.git
cd dancing-bear

# Create virtual environment and install dependencies
make venv

# Verify it works
./bin/assistant --help
```

You should see a list of available commands (mail, calendar, schedule, resume, etc.).

## Step 2: Pick Your First Task

### Option A: Resume Building (Most Useful)

Extract data from LinkedIn, align with job postings, and render tailored resumes:

```bash
# Extract from LinkedIn HTML export (save your profile page as HTML)
./bin/assistant resume extract --linkedin profile.html --out candidate.yaml

# Align with a job posting to find keyword matches
./bin/assistant resume align --data candidate.yaml --job job.yaml --out alignment.json

# Render to DOCX with a template
./bin/assistant resume render --data candidate.yaml --template template.yaml --out resume.docx

# Or render a tailored version filtered by alignment
./bin/assistant resume render --data candidate.yaml --template template.yaml \
  --filter-skills-alignment alignment.json --out tailored_resume.docx
```

### Option B: Email Filter Management (Gmail)

Manage Gmail filters/labels from YAML:

```bash
# Set up Gmail credentials (one-time)
./bin/mail-assistant-auth

# Export your current filters to YAML
./bin/mail filters export --out my_filters.yaml

# Edit my_filters.yaml to add/change filters, then preview changes
./bin/mail filters plan --config my_filters.yaml

# Apply when ready (always dry-run first!)
./bin/mail filters sync --config my_filters.yaml --dry-run
./bin/mail filters sync --config my_filters.yaml
```

### Option C: iOS Phone Layouts

Export your current home screen layout, plan changes, and apply:

```bash
# Export current device layout
./bin/phone export-device --out ios_layout.yaml

# Build a plan for reorganization
./bin/phone plan --layout ios_layout.yaml --out ios_plan.yaml

# Generate a checklist of manual steps
./bin/phone checklist --plan ios_plan.yaml --layout ios_layout.yaml --out checklist.txt

# Build a .mobileconfig profile to apply
./bin/phone profile build --plan ios_plan.yaml --out layout.mobileconfig
```

### Option D: Other Tools (Experimental/POC)

```bash
# Calendar: bulk-create events from spreadsheet
./bin/schedule plan --source classes.csv --out schedule.yaml
./bin/schedule apply --plan schedule.yaml --calendar "My Calendar" --apply

# WhatsApp: search local chat database (macOS only)
./bin/whatsapp search --contains "meeting" --limit 20

# Metals: track precious metals from email receipts (proof of concept)
./bin/metals extract gmail --out metals.yaml
```

## Using with an LLM (Recommended)

This project was built entirely with LLM assistance and is designed to be extended the same way. The codebase includes context files that help LLMs understand the project structure - you can add features, fix bugs, or explore the code by just asking.

### With Claude Code (Recommended)

[Claude Code](https://claude.com/claude-code) works best because this project was built with it:

```bash
# Navigate to the project
cd dancing-bear

# Start Claude Code
claude

# Ask it to help with tasks like:
# "Set up Gmail authentication for me"
# "Create a filter that archives newsletters"
# "Help me schedule my weekly classes from this CSV"
```

Claude Code automatically reads `CLAUDE.md` for project context.

### With Codex / ChatGPT

Copy the context from `.llm/CONTEXT.md` into your conversation:

```bash
# Get the context file
cat .llm/CONTEXT.md | pbcopy  # macOS
# or
cat .llm/CONTEXT.md | xclip   # Linux
```

Then paste it at the start of your ChatGPT/Codex session before asking questions.

### With Gemini

Same approach as Codex - provide the context file:

```bash
cat .llm/CONTEXT.md
```

Copy the output and include it in your Gemini prompt.

### Getting LLM Context Programmatically

The project includes utilities to generate context for LLMs:

```bash
# Compact context for any LLM
./bin/llm agentic --stdout

# Domain map (what's where in the codebase)
./bin/llm domain-map --stdout

# Familiarize yourself with the project
./bin/llm familiar --stdout
```

## Core Concepts

### 1. Plan Before Apply

Every command that modifies data has a safe preview mode:

```bash
# Preview what would happen
./bin/mail labels plan --config labels.yaml

# Dry-run (simulates but doesn't execute)
./bin/mail labels sync --config labels.yaml --dry-run

# Actually apply
./bin/mail labels sync --config labels.yaml
```

### 2. YAML as Source of Truth

Your configuration lives in YAML files. The tools read these and sync state:

```yaml
# Example: filters.yaml
filters:
  - name: Archive Newsletters
    match:
      from: newsletter@example.com
    actions:
      - archive
      - label: Newsletters
```

### 3. Profiles for Multiple Accounts

Store credentials in `~/.config/credentials.ini`:

```ini
[mail.personal]
credentials = ~/.config/google_creds_personal.json
token = ~/.config/token_personal.json

[mail.work]
credentials = ~/.config/google_creds_work.json
token = ~/.config/token_work.json
```

Then use `--profile`:

```bash
./bin/mail --profile personal labels list
./bin/mail --profile work labels list
```

## Common Commands Cheat Sheet

| Task | Command |
|------|---------|
| **Resume** | |
| Extract from LinkedIn | `./bin/assistant resume extract --linkedin profile.html --out candidate.yaml` |
| Align with job posting | `./bin/assistant resume align --data candidate.yaml --job job.yaml` |
| Render to DOCX | `./bin/assistant resume render --data candidate.yaml --out resume.docx` |
| **Email** | |
| List Gmail labels | `./bin/mail labels list` |
| Export Gmail filters | `./bin/mail filters export --out filters.yaml` |
| Sync filters | `./bin/mail filters sync --config filters.yaml --dry-run` |
| **iOS** | |
| Export device layout | `./bin/phone export-device --out layout.yaml` |
| Build layout profile | `./bin/phone profile build --plan plan.yaml --out layout.mobileconfig` |
| **Other** | |
| Search WhatsApp | `./bin/whatsapp search --contains "meeting"` |
| WiFi diagnostics | `./bin/wifi diagnose` |

## Troubleshooting

### "Command not found"

Make sure you activated the virtual environment:

```bash
source .venv/bin/activate
```

### Authentication errors

Re-run the auth helper:

```bash
./bin/mail-assistant-auth
```

### "No module named X"

Reinstall dependencies:

```bash
make venv
```

### Still stuck?

Check the full documentation in `README.md` or ask your LLM assistant with the context from `.llm/CONTEXT.md`.

## Next Steps

1. Read `README.md` for complete command reference
2. Explore `config/` for example YAML configurations
3. Check `.llm/FLOWS.yaml` for pre-built workflows
4. Run `./bin/llm flows --list` to see available automation flows

---

*Built for humans who'd rather configure once and automate forever.*
