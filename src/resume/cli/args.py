"""Shared constants for the Resume Assistant CLI."""

from __future__ import annotations

from core.paths import ENV_DATA_HOME

# Default profile used when --profile is not provided
DEFAULT_PROFILE = "sample"

# Domain subdirectory under the data root; also the --out-dir help text, which
# names the resolved default so `--help` does not claim a path that moved.
OUT_DIR_DOMAIN = "resume"
OUT_DIR_HELP = (
    "Output directory (default: <data-home>/resume, "
    f"overridable with ${ENV_DATA_HOME})"
)

# --profile means two different things depending on the command, so it gets two
# help strings rather than one blanket claim that is wrong half the time.
#
# On commands that read candidate data, it selects BOTH the input file (via
# _resolve_data) and the output subdirectory. On commands that only write, it
# is an output prefix only.
PROFILE_HELP_DATA = (
    "Profile name: selects <config-home>/resume/<profile>/data.* when --data "
    "is omitted, and the output subdirectory (e.g. 'brian')"
)
PROFILE_HELP_OUT = "Output prefix (e.g., 'briancorysherwin_general')"

# --data help text; names the profile fallback so --help does not imply the
# flag is mandatory when it is not.
DATA_HELP = (
    "Candidate data file (YAML/JSON). Defaults to "
    "<config-home>/resume/<profile>/data.{json,yaml,yml}"
)

# Common extension constants
EXT_JSON = ".json"
EXT_YAML = ".yaml"
