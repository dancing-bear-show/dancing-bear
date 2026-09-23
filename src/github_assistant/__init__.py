"""GitHub CLI — thin porcelain over ``core.github``.

Package is named ``github_assistant`` so it never shadows PyPI's ``github``
package on any sys.path.
"""

__all__ = [
    "main",
]

from .__main__ import main
