Style Corpus

Purpose
- Place example prose and writing samples here to model writing style.
- Use public-safe examples in this folder; put personal/private samples under `_data/corpus/` (gitignored).

File types
- `.txt`, `.md` are preferred. `.docx` also supported if `python-docx` is installed.

Build a style profile
- `./bin/resume_assistant style build --corpus-dir corpus --profile yourprefix`
- Outputs `out/yourprefix.style.json` with simple lexical stats and top terms.

Use with render/summarize (optional)
- Pass `--style-profile out/yourprefix.style.json` to `summarize` or `render` to bias keyword selection/highlighting.

