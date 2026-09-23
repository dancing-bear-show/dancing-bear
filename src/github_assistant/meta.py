from __future__ import annotations

from core.meta_base import AppMeta

# Package name is ``github_assistant``, not ``github``. A package named
# ``github`` would shadow PyPI's ``github`` package the moment either landed on
# sys.path, and the resulting import would depend on ordering, not intent.
META = AppMeta(
    app_id="github",
    purpose="GitHub porcelain over core.github: review threads, PR view/edit/checks",
    display_name="GitHub",
    bin_name="./bin/github",
    example_cmd="./bin/github pr view --pr 123 --fields number,title,state",
)
