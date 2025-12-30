# Security Policy

## Supported Versions

Currently supporting the latest version on the `main` branch.

| Version | Supported          |
| ------- | ------------------ |
| main    | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly:

### For Sensitive Security Issues

**Do not open a public issue.** Instead, please report security vulnerabilities by:

1. Opening a [Security Advisory](https://github.com/dancing-bear-show/dancing-bear/security/advisories/new)
2. Or emailing the maintainer directly (see GitHub profile for contact)

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if available)

### Response Timeline

- **Initial Response**: Within 48 hours
- **Status Update**: Within 7 days
- **Fix Timeline**: Varies by severity (critical issues prioritized)

## Security Best Practices

When using this project:

1. **Never commit credentials** - Use `~/.config/credentials.ini` for tokens/secrets
2. **Protect your token files** - Ensure proper file permissions (600)
3. **Review OAuth scopes** - Only grant minimum required permissions
4. **Keep dependencies updated** - Run `pip install --upgrade` regularly
5. **Use virtual environments** - Isolate dependencies with `make venv`

## Known Security Considerations

- **Credentials Storage**: This tool stores OAuth tokens locally. Ensure proper file permissions.
- **API Access**: Gmail/Outlook APIs require OAuth2 authentication. Never share tokens.
- **Private Data**: Resume profiles in `resume/_data/profiles_private/` are gitignored by default.

## Security Features

- OAuth2 authentication (no password storage)
- Profile-based credential management
- Dry-run modes for destructive operations
- CI security scanning (qlty with ruff/bandit)
