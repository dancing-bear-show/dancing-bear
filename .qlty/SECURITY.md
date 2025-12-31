# Security Configuration

## Subprocess Usage Policy

This codebase requires subprocess for legitimate system integration purposes:

- **phone/device.py**: Apple Configurator CLI (`cfgutil`) for iOS device management
- **wifi/diagnostics.py**: Network diagnostic tools (`ping`, `traceroute`, etc.)
- **mail/config_cli/pipeline.py**: Package installation (`pip`) in virtual environments

### Security Controls

We skip Bandit's B404 check (subprocess import warning) because the import itself is not a security risk. We maintain security through:

1. **No shell=True** (B602 still active)
   - All subprocess calls use list-form arguments
   - No shell injection possible

2. **Path validation** (B607 still active)
   - Executables are validated with `shutil.which()` before use
   - Hardcoded paths to known system tools

3. **List-form arguments only** (B603 still active)
   - Never construct commands from strings
   - Arguments are always passed as lists

4. **Timeouts enforced**
   - All subprocess calls have reasonable timeouts
   - Prevents resource exhaustion

### Example of Safe Usage

```python
# SAFE - validated path, list args, timeout
cfgutil = find_cfgutil_path()  # Uses shutil.which() validation
result = subprocess.run(
    [cfgutil, "list"],  # List form, no shell
    capture_output=True,
    timeout=30,  # Timeout protection
    text=True,
)  # nosec B603 - cfgutil validated above
```

### What We Still Check

- **B602**: Detects `shell=True` usage (forbidden)
- **B603**: Detects subprocess without shell check
- **B607**: Detects partial executable paths
- All other Bandit security checks remain active

## Audit Trail

- **2025-01-31**: Configured Qlty to skip B404 (subprocess import warning)
  - Rationale: Import itself is not a security issue
  - Security maintained via B602/B603/B607 checks
  - All subprocess usage audited and validated
