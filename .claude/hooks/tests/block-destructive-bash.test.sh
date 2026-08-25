#!/usr/bin/env bash
# Pipe-test block-destructive-bash.sh with the real PreToolUse stdin shape.
#
# WHY THIS FILE EXISTS AT ALL: the hook under test blocks its own test payloads.
# `echo "[mail.x]" > ~/.config/credentials.ini` cannot be typed into a Bash tool call
# by an agent, because the hook intercepts the call before it runs -- the agent
# testing the hook is subject to the hook. The cases have to live in a file that is
# read from disk and executed as a unit. Do not inline them back into a command; it
# will look like the hook is broken when it is in fact working.
#
# The hook is resolved as a sibling of this script's parent directory, so this works
# unchanged from the repo copy and from a copy installed at ~/.claude/hooks/tests/.
# Override with argument 1.
#
# Usage: bash block-destructive-bash.test.sh [path-to-hook]
# Exit:  0 = all pass, 1 = at least one failure. Requires jq.

HOOK="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/block-destructive-bash.sh}"
fail=0

if [ ! -f "$HOOK" ]; then
  echo "hook not found: $HOOK" >&2
  exit 1
fi
echo "testing: $HOOK"
echo

run() { # run <BLOCK|ALLOW> <command>
  local expect="$1" cmd="$2" rc got
  jq -n --arg c "$cmd" '{tool_name:"Bash",tool_input:{command:$c}}' | bash "$HOOK" >/dev/null 2>&1
  rc=$?
  got=ALLOW; [ "$rc" -eq 2 ] && got=BLOCK
  if [ "$got" = "$expect" ]; then
    printf 'ok    %-5s  %s\n' "$got" "$cmd"
  else
    printf 'FAIL  want=%s got=%s  %s\n' "$expect" "$got" "$cmd"; fail=1
  fi
}

echo "--- reads of this repo's credential files (want BLOCK) ---"
run BLOCK 'cat ~/.config/credentials.ini'
run BLOCK 'cat $XDG_CONFIG_HOME/credentials.ini'
run BLOCK 'head -20 /Users/me/.config/credentials.json'
run BLOCK 'jq . ~/.config/token.json'
run BLOCK 'cat ~/.config/outlook_token.json'
run BLOCK 'less ~/.config/msal_flow.json'
run BLOCK 'grep client_id ~/.config/credentials.ini'
run BLOCK 'rg outlook_client_id ~/.config/credentials.ini'
run BLOCK 'sed -n "1,5p" ~/.config/credentials.ini'
run BLOCK 'awk "/mail/" ~/.config/credentials.ini'
run BLOCK 'xxd ~/.config/token.json'
run BLOCK 'strings ~/.config/outlook_token.json'
run BLOCK 'cat ~/.ssh/id_rsa'
run BLOCK 'cat ~/.aws/credentials'
run BLOCK 'cat ~/.npmrc'
run BLOCK 'cat ~/.gnupg/secring.gpg'
run BLOCK 'cat .env'
run BLOCK 'cat backend/.env.local'

echo
echo "--- command substitution forms (want BLOCK) ---"
run BLOCK 'export $(cat .env | xargs)'
run BLOCK 'TOKEN=$(jq -r .access_token ~/.config/outlook_token.json)'
run BLOCK 'echo `cat ~/.config/credentials.ini`'
run BLOCK 'X=$(grep token ~/.config/credentials.ini)'

echo
echo "--- writes to credential files (want BLOCK) ---"
run BLOCK 'echo "[mail.gmail]" > ~/.config/credentials.ini'
run BLOCK 'printf x >~/.config/credentials.ini'
run BLOCK 'cat /tmp/x >| ~/.config/credentials.ini'
run BLOCK 'echo x 2> ~/.config/token.json'
run BLOCK 'tee ~/.config/credentials.ini <<< "[mail.x]"'
run BLOCK 'cp /tmp/x ~/.config/credentials.ini'
run BLOCK 'mv /tmp/x ~/.config/outlook_token.json'
run BLOCK 'dd if=/dev/zero of=/Users/me/.ssh/id_rsa'
run BLOCK 'ln -sf /tmp/fake ~/.config/credentials.ini'
run BLOCK 'truncate -s 0 ~/.config/credentials.ini'
run BLOCK 'install -m600 /tmp/x ~/.config/msal_flow.json'
run BLOCK 'echo registry=x > ~/.npmrc'
# Exfiltration: the credential file as the SOURCE, copied somewhere readable.
run BLOCK 'cp ~/.config/credentials.ini /tmp/leak'
run BLOCK 'cp ~/.config/token.json /tmp/'

echo
echo "--- append carve-out: adding a profile section must ALLOW ---"
run ALLOW 'echo "[mail.new]" >> ~/.config/credentials.ini'
run ALLOW 'tee -a ~/.config/credentials.ini <<< "[mail.new]"'
run ALLOW 'tee --append ~/.config/credentials.ini'

echo
echo "--- template carve-out (want ALLOW) ---"
run ALLOW 'cat .env.example'
run ALLOW 'cat backend/.env.template'
run ALLOW 'cat config/.env.sample'
run ALLOW 'cp .env.example .env.example.bak'

echo
echo "--- rm -rf true positives (want BLOCK) ---"
run BLOCK 'rm -rf /'
run BLOCK 'rm -rf ~'
run BLOCK 'rm -rf $HOME'
run BLOCK 'rm -rf /etc'
run BLOCK 'rm -rf /usr/local'
run BLOCK 'rm -rf /System/Library'
run BLOCK 'rm -rf /var/db'
run BLOCK 'rm -rf /Users/briansherwin'
# Spelling variants the reference missed entirely.
run BLOCK 'rm -fr /'
run BLOCK 'rm --recursive --force /'
run BLOCK 'rm -rf //'
run BLOCK 'rm -rf ///'
run BLOCK 'rm -r -f /etc'
run BLOCK 'rm -rvf /usr'
run BLOCK 'rm -Rf /'
run BLOCK 'rm -rf /etc/'
# Compound command where only the second half is dangerous.
run BLOCK 'cd /tmp && rm -rf /tmp/ok; rm -rf /'

echo
echo "--- rm -rf FALSE POSITIVES the reference blocked; must now ALLOW ---"
run ALLOW 'rm -rf /tmp/scratch'
run ALLOW 'rm -rf /private/tmp/claude-501/work'
run ALLOW 'rm -rf /var/tmp/build'
run ALLOW 'rm -rf out/'
run ALLOW 'rm -rf ./build'
run ALLOW 'rm -rf .venv'
run ALLOW 'rm -rf ~/.cache/dancing-bear'
run ALLOW 'rm -rf /Users/briansherwin/scratch/thing'
run ALLOW 'rm -f somefile.txt'
run ALLOW 'rm -rf node_modules'

echo
echo "--- other destructive patterns (want BLOCK) ---"
run BLOCK 'git push --force origin main'
run BLOCK 'git push -f origin main'
run BLOCK 'git reset --hard HEAD~3'
run BLOCK 'psql -c "DROP TABLE users"'
run BLOCK 'psql -c "DROP DATABASE prod"'
run BLOCK 'psql -c "TRUNCATE events"'

echo
echo "--- ordinary dancing-bear work (want ALLOW) ---"
run ALLOW 'make test'
run ALLOW 'make cov'
run ALLOW 'git commit -m "fix(mail): handle empty profile"'
run ALLOW 'git status'
run ALLOW './bin/mail labels sync --dry-run'
run ALLOW './bin/calendar outlook add --subject "standup"'
run ALLOW './bin/workflow list'
run ALLOW './bin/mail --agentic --agentic-format yaml'
run ALLOW 'echo hi > /tmp/out.txt'
run ALLOW 'make test > /tmp/test.log 2>&1'
run ALLOW 'cat src/mail/cli.py'
run ALLOW 'cat README.md'
run ALLOW 'grep -rn credential_ini_paths src/core/'
run ALLOW 'ls -la ~/.config'
run ALLOW 'cp README.md /tmp/README.md'
run ALLOW '~/.qlty/bin/qlty check src/mail/cli.py'
# "credentials" as a word in ordinary prose/paths must not trip the filename match.
run ALLOW 'git commit -m "docs: describe credentials setup"'
run ALLOW 'cat src/mail/config_resolver.py'

echo
[ "$fail" -eq 0 ] && echo "ALL PASS" || echo "FAILURES PRESENT"
exit "$fail"
