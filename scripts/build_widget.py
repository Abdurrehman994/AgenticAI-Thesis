"""Build the widget for hosting on a public HTTPS address (GitHub Pages), as 3DDashboard's "Run your App" needs.

    python scripts/build_widget.py      # widget/dist/: index.html (loader) + core.js, app.js, style.css
    python scripts/build_widget.py --base https://example.org/widget/

What the tenant showed (probe.html in the widget repo, 4 Nov 2026):
- "Run your App" cannot load a widget from localhost: no request reaches the laptop.
- It downloads the page through the platform and runs it in its own frame
  (https://pod...3dexperience.3ds.com/api/widget/frame?...), where `widget`, `require` and DS/WAFData exist.
  Relative file references would point at that frame host, so the files are loaded by absolute URL.
- A small page in the shape of Dassault's UWA samples loads; the same page with ~45 KB of inline code (scripts in
  <head>) did not, without a message. So index.html is a plain-ASCII loader that, on the widget's onLoad, adds
  style.css, core.js and app.js from `--base`.
The files hold no data, tenant URL or credentials: in 3DDashboard the widget gets the 3DSpace URL from the platform
and the SecurityContext from its Connection tab.
"""
import argparse
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIDGET = ROOT / "widget"
DIST = WIDGET / "dist"
BASE = "https://abdurrehman994.github.io/plm-agent-widget/"
ASSETS = ("core.js", "app.js", "style.css")

LOADER = """<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:widget="http://www.netvibes.com/ns/">
<head>
  <title>PLM Data Agent</title>
  <meta name="author" content="Muhammad Abdur Rehman" />
  <meta name="description" content="Review AI proposals, release readiness and duplicate parts of Engineering Items" />
  <meta name="autoRefresh" content="0" />
  <script type="text/javascript" src="//uwa.netvibes.com/lib/c/UWA/js/UWA_Standalone_Alone.js"></script>
  <script type="text/javascript">//<![CDATA[
    var PLMAgentLoader = {
      base: '{base}',
      version: '{version}',
      onLoad: function () {
        var head = document.getElementsByTagName('head')[0];
        var css = document.createElement('link');
        css.rel = 'stylesheet';
        css.href = PLMAgentLoader.base + 'style.css?v=' + PLMAgentLoader.version;
        head.appendChild(css);
        widget.body.innerHTML = '<p>Loading PLM Data Agent...</p>';
        PLMAgentLoader.load(['core.js', 'app.js'], 0);
      },
      load: function (files, n) {
        if (n === files.length) { return; }
        var script = document.createElement('script');
        script.charset = 'utf-8';
        script.src = PLMAgentLoader.base + files[n] + '?v=' + PLMAgentLoader.version;
        script.onload = function () { PLMAgentLoader.load(files, n + 1); };
        script.onerror = function () {
          widget.body.innerHTML = '<p>Could not load ' + files[n] + ' from ' + PLMAgentLoader.base + '</p>';
        };
        document.getElementsByTagName('head')[0].appendChild(script);
      }
    };
    widget.addEvent('onLoad', PLMAgentLoader.onLoad);
  //]]></script>
</head>
<body>
  <p>PLM Data Agent</p>
</body>
</html>
"""


def loader(base: str, version: str) -> str:
    page = LOADER.replace("{base}", base).replace("{version}", version)
    if not page.isascii():
        raise SystemExit("the loader page must be plain ASCII")
    try:
        ET.fromstring(page.split("\n", 1)[1])  # without the doctype line
    except ET.ParseError as e:
        raise SystemExit(f"the loader page is not well-formed XML: {e}")
    return page


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default=BASE, help="public HTTPS address the files are published at (ends with /)")
    args = parser.parse_args()
    base = args.base if args.base.endswith("/") else args.base + "/"

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    version = time.strftime("%Y%m%d%H%M%S")  # a new version makes the dashboard fetch the new files
    (DIST / "index.html").write_text(loader(base, version), encoding="utf-8")
    for name in ASSETS:
        shutil.copy2(WIDGET / name, DIST / name)
    print(f"Built {DIST}: index.html (loads {', '.join(ASSETS)} from {base}, version {version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
