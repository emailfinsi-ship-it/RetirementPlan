"""Plain / Technical wording.

The app can show its words two ways:

* **plain** (the default) -- everyday words for people with little financial
  knowledge: short sentences, no jargon, the technical term kept behind the
  small "i" pop-up.
* **technical** -- the full financial wording, as it has always been.

This is a display preference only. It never changes a calculated number: the
pages are built exactly as before, and in plain mode their text is rewritten
on the way out by the rules in :mod:`source.webapp.plain_rules`. Technical
mode applies no rules, so it is the original wording.

Two things apply in *both* modes: the typography fix (a spaced double hyphen
used as a dash becomes a proper dash) and nothing else.

How a rule is written (see ``plain_rules``):

* ``S(old, new)`` -- a sentence or phrase anywhere in the page. Spaces in
  ``old`` match any run of whitespace (the page source wraps lines), quotes and
  ampersands match their HTML-escaped forms, and a dash matches ``--`` too.
  ``{name}`` captures one changing word-like piece (a number, a year) and
  ``{m_name}`` captures a few words (a name, a phrase); ``{name}`` in ``new``
  puts it back.
* ``T(old, new)`` -- a whole piece of text between tags (a button, a column
  title). It never touches the same words inside a sentence.
* ``H(old, new)`` -- the text of a heading (h2 / h3); ``L(old, new)`` -- the text
  of a tile label. Both leave links and sentences that use the same words alone.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

MODES = ("plain", "technical")
DEFAULT_MODE = "plain"

# ---------------------------------------------------------------- typography
_STYLE_BLOCK = re.compile(r"(<style\b.*?</style>)", re.S | re.I)
_SPACED_DASH = re.compile(r"(?<=\S) -- (?=\S)")


def fix_typography(page: str) -> str:
    """A spaced double hyphen used as a dash becomes a proper dash. Style
    blocks are left alone (CSS custom properties start with two hyphens)."""
    parts = _STYLE_BLOCK.split(page)
    for i in range(0, len(parts), 2):
        parts[i] = _SPACED_DASH.sub(" — ", parts[i])
    return "".join(parts)


# -------------------------------------------------------------------- rules
_DASH = r"\s*(?:—|--|&mdash;)\s*"
_PLACEHOLDER = re.compile(r"(\{\w+\})")
_ENTITY_NAMES = {ord(c): name for name, c in (("rarr", "→"), ("larr", "←"), ("plusmn", "±"), ("times", "×"), ("frac12", "½"), ("middot", "·"), ("hellip", "…"), ("nbsp", "\u00a0"))}


@dataclass
class Rule:
    kind: str  # "s" phrase anywhere; "t" whole text node; "h" heading text; "l" tile label
    old: str
    new: str
    pattern: re.Pattern  # for page HTML
    text_pattern: re.Pattern  # for plain text (pop-up titles and sentences)
    probe: str
    groups: tuple[str, ...]
    hits: int = 0


def _literal_to_regex(text: str) -> str:
    text = text.replace(" -- ", " — ")
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            while i < len(text) and text[i].isspace():
                i += 1
            out.append(r"\s+")
            continue
        if ch == "—":
            # collapse the spaces around a dash into the dash pattern
            while out and out[-1] == r"\s+":
                out.pop()
            out.append(_DASH)
            i += 1
            while i < len(text) and text[i].isspace():
                i += 1
            continue
        if ch in "'’":
            out.append(r"(?:\\?'|&#x27;|&#39;|&rsquo;|’)")
        elif ch in '"“”':
            out.append(r'(?:\\?"|&quot;|&#34;|&ldquo;|&rdquo;|“|”)')
        elif ch == ">" and out and out[-1] == r"\-":
            out.append("(?:>|&gt;)")  # an arrow written -> may be -&gt; in the page
        elif ch == "&":
            out.append(r"(?:&amp;|&)")
        elif ord(ch) > 127:
            # a symbol such as an arrow or a fraction may be written as an HTML entity in the page
            forms = [re.escape(ch), f"&#{ord(ch)};", f"&#[xX]0*{ord(ch):x};"]
            if ord(ch) in _ENTITY_NAMES:
                forms.append(f"&{_ENTITY_NAMES[ord(ch)]};")
            out.append("(?:" + "|".join(forms) + ")")
        else:
            out.append(re.escape(ch))
        i += 1
    return "".join(out)


def compile_rule(kind: str, old: str, new: str) -> Rule:
    pieces = _PLACEHOLDER.split(old)
    regex = []
    groups: list[str] = []
    for piece in pieces:
        if _PLACEHOLDER.fullmatch(piece):
            name = piece[1:-1]
            groups.append(name)
            # {name} captures one word-like piece (a number, a year); {m_name}
            # captures a few words. A rule never starts with a multi-word piece.
            if name.startswith("m_"):
                regex.append(rf"(?P<{name}>[^<>]{{1,90}}?)")
            else:
                regex.append(rf"(?P<{name}>[^<>\s]{{1,60}}?)")
        else:
            regex.append(_literal_to_regex(piece))
    core = "".join(regex)
    if kind == "t":
        pattern = re.compile(rf"(?:(?<=>)|^)(?P<_pre>\s*){core}(?P<_post>\s*)(?=<|$)")
    elif kind == "h":
        pattern = re.compile(rf"(?P<_pre><h[23]\b[^>]*>\s*){core}(?P<_post>\s*)(?=<)")
    elif kind == "l":
        pattern = re.compile(rf'(?P<_pre><div class="label">\s*){core}(?P<_post>\s*)(?=<)')
    else:
        pattern = re.compile(core)
    # In plain text a "t"/"h"/"l" rule means the whole string.
    text_pattern = re.compile(rf"^(?P<_pre>\s*){core}(?P<_post>\s*)$") if kind != "s" else re.compile(core)
    words = re.findall(r"[A-Za-z0-9]{5,}", _PLACEHOLDER.sub(" ", old))
    probe = max(words, key=len) if words else ""
    return Rule(kind, old, new, pattern, text_pattern, probe, tuple(groups))


def _render(rule: Rule, match: re.Match, *, html_mode: bool) -> str:
    text = rule.new
    if html_mode:
        text = text.replace("&", "&amp;")
    for name in rule.groups:
        text = text.replace("{" + name + "}", match.group(name))
    if rule.kind != "s":
        text = (match.group("_pre") if html_mode else "") + text + (match.group("_post") if html_mode else "")
    return text


_COMPILED: list[Rule] | None = None


def rules() -> list[Rule]:
    global _COMPILED
    if _COMPILED is None:
        from source.webapp import plain_rules

        _COMPILED = [compile_rule(kind, old, new) for kind, old, new in plain_rules.RULES]
    return _COMPILED


def _apply_rules(text: str, *, html_mode: bool) -> str:
    for rule in rules():
        if rule.probe and rule.probe not in text:
            continue

        def sub(m: re.Match, rule: Rule = rule) -> str:
            rule.hits += 1
            return _render(rule, m, html_mode=html_mode)

        text = (rule.pattern if html_mode else rule.text_pattern).sub(sub, text)
    return text


# ------------------------------------------------------------------- public
def current_mode() -> str:
    """The saved wording mode; plain when nothing is saved or the database is
    not ready yet (login, first-run screens)."""
    try:
        from source.common import db

        return db.wording_mode()
    except Exception:  # noqa: BLE001 -- a display preference must never break a page
        return DEFAULT_MODE


def is_plain() -> bool:
    return current_mode() == "plain"


def plain_html(fragment: str) -> str:
    """Rewrite a piece of page HTML in plain mode (no-op in technical mode)."""
    if not is_plain():
        return fragment
    return _apply_rules(fragment, html_mode=True)


def plain_text(text: str) -> str:
    """Rewrite a piece of plain text (a pop-up title or sentence)."""
    if not is_plain():
        return text
    return _apply_rules(text, html_mode=False)


def plain_node_text(inner_html: str, kind: str = "") -> str:
    """The plain version of a heading's or label's inner HTML, as lower-case
    plain text -- the same normal form the "i" buttons are matched on. ``kind``
    is "h" for a heading and "l" for a tile label, so the heading and label
    rules see the tag they are written for."""
    if kind == "h":
        wrapped = "<h3>" + inner_html + "</h3>"
    elif kind == "l":
        wrapped = '<div class="label">' + inner_html + "</div>"
    else:
        wrapped = ">" + inner_html + "<"
    done = _apply_rules(wrapped, html_mode=True) if is_plain() else wrapped
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", done))).strip().lower()


def plain_entries(entries: dict) -> dict:
    """The pop-up entries with every string rewritten (plain mode only)."""
    if not is_plain():
        return entries
    out = {}
    for key, entry in entries.items():
        out[key] = {k: (plain_text(v) if isinstance(v, str) else v) for k, v in entry.items()}
    return out


def reset_hit_counts() -> None:
    for rule in rules():
        rule.hits = 0


def unused_rules() -> list[Rule]:
    return [r for r in rules() if r.hits == 0]


__all__ = [
    "DEFAULT_MODE", "MODES", "compile_rule", "current_mode", "fix_typography", "is_plain",
    "plain_entries", "plain_html", "plain_node_text", "plain_text", "reset_hit_counts", "rules", "unused_rules",
]
