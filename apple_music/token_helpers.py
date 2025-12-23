"""Helpers for user-token acquisition via MusicKit JS data URL."""

from __future__ import annotations

import urllib.parse

HTML_TEMPLATE = """<!doctype html>
<html>
<body>
<h3>Apple Music: Get User Token</h3>
<p>Click Authorize and sign in; the Music User Token will appear below.</p>
<button id="auth">Authorize</button>
<pre id="out">Initializing…</pre>
<script src="https://js-cdn.music.apple.com/musickit/v3/musickit.js"></script>
<script>
(async() => {
  const dev = "__DEV_TOKEN__";
  const out = document.getElementById('out');
  try {
    await MusicKit.configure({developerToken: dev, app: {name: "UserToken", build: "1.0"}});
  } catch (err) {
    out.textContent = "Configure failed: " + err;
    return;
  }
  const music = MusicKit.getInstance();
  out.textContent = "Ready. Click Authorize.";
  document.getElementById('auth').onclick = async () => {
    out.textContent = "Authorizing…";
    try {
      const tok = await music.authorize();
      out.textContent = tok;
    } catch (e) {
      out.textContent = "Auth failed: " + e;
    }
  };
})();
</script>
</body>
</html>"""


def build_data_url(developer_token: str) -> str:
    """Return a data: URL that, when opened, prompts for user auth and prints the Music User Token."""
    html = HTML_TEMPLATE.replace("__DEV_TOKEN__", developer_token)
    return "data:text/html," + urllib.parse.quote(html)


def build_html(developer_token: str) -> str:
    """Return the raw HTML page for user-token acquisition."""
    return HTML_TEMPLATE.replace("__DEV_TOKEN__", developer_token)
