"""Turns the user guide (docs/README.md) into the page the app shows in Tutorial (source/webapp/static/tutorial/guide.html).

    python3 tools/video/build_guide.py docs/README.md source/webapp/static/tutorial/guide.html

The guide marks each part with <!-- section: name --> ... <!-- /section -->; the Tutorial page shows the part that matches the
video being watched, and the whole guide below it. Needs the "markdown" package (a build tool only, not part of the app)."""

import re
import sys

import markdown

src, out = sys.argv[1], sys.argv[2]
text = open(src, encoding="utf-8").read()
text = re.sub(r"(?m)^> \*\*Watch the videos\.\*\*.*(?:\n>.*)*\n", "", text)      # file names mean nothing inside the app
md = markdown.Markdown(extensions=["extra", "sane_lists"])


def convert(chunk: str) -> str:
    md.reset()
    body = md.convert(chunk)
    body = re.sub(r'src="screenshots/([^"]+?)\.(?:png|jpg)"', r'src="/tutorial/screenshots/\1.jpg" loading="lazy"', body)
    return body.replace("<h1>", "<h2>").replace("</h1>", "</h2>")


parts, pos = [], 0
for m in re.finditer(r"<!-- section: ([a-z]+) -->\n(.*?)<!-- /section -->", text, re.S):
    parts.append(convert(text[pos:m.start()]))
    parts.append(f'<div class="tut-sec" data-sec="{m.group(1)}">{convert(m.group(2))}</div><!--/tut-sec-->')
    pos = m.end()
parts.append(convert(text[pos:]))
open(out, "w", encoding="utf-8").write("\n".join(parts))
print("wrote", out, sum(len(p) for p in parts), "bytes,", text.count("<!-- section:"), "sections")
