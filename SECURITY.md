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

## Known Vulnerabilities

### pdfminer.six - Insecure Deserialization (GHSA-f83h-ghpp-7wcc)

**Status:** Partially Mitigated
**Severity:** HIGH (CVSS 7.8)
**Affected Component:** pdfminer.six CMap loader
**CVE:** None assigned yet
**GitHub Advisory:** [GHSA-f83h-ghpp-7wcc](https://github.com/advisories/GHSA-f83h-ghpp-7wcc)

#### Description

pdfminer.six uses Python's `pickle` module to deserialize CMap files, which can lead to arbitrary code execution if an attacker can write malicious pickle files to directories in the `CMAP_PATH`.

#### Our Usage

We use pdfminer.six **only** for text extraction (`extract_text` from `high_level` module) in:
- `calendars/importer/pdf_parser.py`
- `resume/parsing.py`
- `resume/io_utils.py`

#### Mitigation Steps Taken

1. ✅ **Upgraded to latest version** (20251230) - contains partial fixes
2. ✅ **Limited scope** - We only use high-level text extraction, not CMap loading directly
3. ✅ **Controlled inputs** - Only process user-provided PDFs, not arbitrary files from untrusted sources

#### Known Limitations

- **Complete fix not available:** The vulnerability persists in the latest version (20251230) as the underlying pickle deserialization issue has not been fully addressed upstream
- **Upstream tracking:** https://github.com/pdfminer/pdfminer.six/issues

#### Future Mitigation

- **Note:** pdfplumber is NOT a viable alternative as it depends on pdfminer.six==20251107 (older vulnerable version)
- Monitor upstream for complete fix at https://github.com/pdfminer/pdfminer.six
- Consider alternative PDF libraries that don't use pickle (e.g., pypdf, PyMuPDF)
- Restrict PDF processing to trusted sources only

#### Risk Assessment

**Risk Level:** LOW for our use case
- We don't process PDFs from untrusted sources
- We don't use CMap loading functionality directly
- Attack requires local file system access to write malicious pickle files to `CMAP_PATH`
- Attack requires control over `CMAP_PATH` environment variable or access to shared writable directories

## Security Features

- OAuth2 authentication (no password storage)
- Profile-based credential management
- Dry-run modes for destructive operations
- CI security scanning (qlty with ruff/bandit)
