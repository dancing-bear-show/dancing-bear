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
- **Claude Code** (optional but recommended) - see [Claude Code Setup](#claude-code-setup) below

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

## Claude Code Setup

This project was built entirely with Claude Code and is designed to be extended the same way. Claude Code is an AI coding assistant that runs in your terminal - it can read files, write code, run commands, and help you navigate the codebase.

### What is Claude Code?

Claude Code is Anthropic's command-line tool that brings Claude directly into your terminal. It can:
- Read and understand code in your project
- Write and edit files
- Run terminal commands
- Help you debug, refactor, and add features
- Automatically read project context from `CLAUDE.md`

### Installing Claude Code

**Option 1: npm (Recommended)**
```bash
# Install globally with npm
npm install -g @anthropic-ai/claude-code

# Verify installation
claude --version
```

**Option 2: Homebrew (macOS)**
```bash
brew install claude-code
```

**Option 3: Direct download**

Visit [claude.ai/claude-code](https://claude.ai/claude-code) and follow the installation instructions for your platform.

### First-Time Setup

1. **Get an API key** (if you don't have one):
   - Go to [console.anthropic.com](https://console.anthropic.com)
   - Sign up or log in
   - Navigate to API Keys and create a new key
   - Copy the key (starts with `sk-ant-`)

2. **Configure Claude Code**:
   ```bash
   # Set your API key (one-time setup)
   claude config set api_key sk-ant-your-key-here

   # Or set it as an environment variable
   export ANTHROPIC_API_KEY=sk-ant-your-key-here
   ```

3. **Verify it works**:
   ```bash
   claude --help
   ```

### Using Claude Code with This Project

```bash
# Navigate to the project
cd dancing-bear

# Start Claude Code
claude

# You're now in an interactive session. Try asking:
```

**Example prompts to get started:**

```
# Understanding the project
"What does this project do?"
"Show me the main CLI entry points"
"How is the codebase organized?"

# Getting help with tasks
"Help me set up Gmail authentication"
"Create a filter that archives newsletters from example.com"
"Export my current email filters to YAML"

# Working with resumes
"Extract data from my LinkedIn profile (saved as profile.html)"
"Help me align my resume with this job posting"
"Render a tailored resume for a Python developer role"

# Debugging
"Why am I getting an authentication error?"
"The calendar sync isn't working - help me debug"
```

### How It Works

When you run `claude` in this project directory, Claude Code automatically:

1. Reads `CLAUDE.md` for project-specific instructions
2. Understands the codebase structure
3. Can run commands like `./bin/mail --help`
4. Can read, create, and edit files
5. Remembers context throughout your session

### Tips for Best Results

- **Be specific**: "Add a filter for emails from @newsletter.com that archives them" works better than "help with filters"
- **Let it explore**: Say "look at how the existing filters work first" before asking for changes
- **Use dry-run**: Ask it to use `--dry-run` flags when testing changes
- **Review changes**: Claude will show you what it's about to do - review before confirming

### Alternative: Other LLMs

If you prefer ChatGPT, Gemini, or another LLM:

```bash
# Get context to paste into your LLM conversation
cat .llm/CONTEXT.md | pbcopy  # macOS - copies to clipboard

# Or get a compact summary
./bin/llm agentic --stdout
```

Paste the context at the start of your conversation, then ask your questions.

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
