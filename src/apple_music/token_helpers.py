"""Helpers for user-token acquisition via MusicKit JS data URL."""

from __future__ import annotations

import urllib.parse

# Endpoint the auth page posts the captured token to. Shared with user_token_cli so
# the page and the server that accepts it cannot drift apart.
TOKEN_PATH = "/token"  # nosec B105 - URL path, not a credential

HTML_TEMPLATE = """<!doctype html>
<html>
<body>
<h3>Apple Music: Get User Token</h3>
<p>Click Authorize and sign in; the Music User Token will appear below.</p>
<button id="auth">Authorize</button>
<pre id="out">Initializing…</pre>
<script>
// Surface any error to the page; a silent failure here is indistinguishable
// from "still loading" and gives the user nothing to act on.
window.addEventListener('error', (e) => {
  const out = document.getElementById('out');
  if (out) out.textContent = "Script error: " + (e.message || e.type);
});
document.getElementById('out').textContent = "Scripts running; loading MusicKit…";
</script>
<script src="https://js-cdn.music.apple.com/musickit/v3/musickit.js" async
        onerror="document.getElementById('out').textContent='MusicKit JS blocked or unreachable (script failed to load). Check ad/content blockers for js-cdn.music.apple.com.'"></script>
<script>
// MusicKit v3 defines window.MusicKit asynchronously and announces itself with
// 'musickitloaded'. Configuring before that event throws a ReferenceError, so wait.
function whenMusicKitReady(timeoutMs) {
  if (window.MusicKit) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error("MusicKit JS did not load within " + (timeoutMs / 1000) + "s")),
      timeoutMs
    );
    document.addEventListener('musickitloaded', () => { clearTimeout(timer); resolve(); }, {once: true});
  });
}
(async() => {
  const dev = "__DEV_TOKEN__";
  const out = document.getElementById('out');
  try {
    await whenMusicKitReady(20000);
  } catch (err) {
    out.textContent = "MusicKit failed to load: " + err.message;
    return;
  }
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
      // Hand the token back to the local CLI when this page is served over http.
      if (location.protocol.startsWith("http")) {
        try {
          await fetch("__TOKEN_PATH__", {method: "POST", body: tok});
          out.textContent = tok + "\\n\\nToken captured by the CLI. You can close this tab.";
        } catch (postErr) {
          out.textContent = tok + "\\n\\nCopy this token manually (handoff failed: " + postErr + ")";
        }
      }
    } catch (e) {
      out.textContent = "Auth failed: " + e;
    }
  };
})();
</script>
</body>
</html>"""


def _render(developer_token: str) -> str:
    """Fill the page template's placeholders."""
    return HTML_TEMPLATE.replace("__DEV_TOKEN__", developer_token).replace(
        "__TOKEN_PATH__", TOKEN_PATH
    )


def build_data_url(developer_token: str) -> str:
    """Return a data: URL that, when opened, prompts for user auth and prints the Music User Token."""
    return "data:text/html," + urllib.parse.quote(_render(developer_token))


def build_html(developer_token: str) -> str:
    """Return the raw HTML page for user-token acquisition."""
    return _render(developer_token)
