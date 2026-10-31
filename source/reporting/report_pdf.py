"""Turns the plan report page (/report.html) into a PDF file you can download, without a browser's print dialog.

The report page is plain HTML that this program writes itself, so a small reader that knows its handful of tags (headings, paragraphs,
tables, lists, boxes, the summary card and its dial) is enough. It is made with reportlab (pure Python, so it also works inside the Mac
app). The charts on the page are small SVG drawings; a minimal drawing reader (lines, boxes, circles, lines of points, text) redraws them
in the PDF in their own colors. If reportlab is missing the caller gets ReportPdfUnavailable and the page keeps its Print button."""

from __future__ import annotations

import html as _html
import io
import math
import re
import unicodedata
import xml.etree.ElementTree as ET
from html.parser import HTMLParser


class ReportPdfUnavailable(RuntimeError):
    pass


NAVY, INK, MUTED, RULE = "#1d3557", "#1d1d1f", "#6e6e73", "#d2d2d7"
TONES = {"ok": ("#1f8a3f", "#eaf6ee"), "warn": ("#b36200", "#fdf3e3"), "bad": ("#d70015", "#fbeaea")}
STATUS = {"on track": "#1f8a3f", "reached": "#1f8a3f", "yes": "#1f8a3f", "planned": "#0071e3", "behind": "#b36200",
          "needs attention": "#b36200", "no": "#d70015", "off track": "#d70015", "not yet": "#b36200"}
HEAD_BORDER = {"sc-bad": "#b45309", "sc-mid": "#1d3557", "sc-good": "#15803d"}

_SKIP = {"script", "style", "button", "title", "noscript"}      # tags whose whole contents are left out (not void tags like img)
_BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "section", "summary", "tr", "ul", "ol", "table", "details"}
_CHARS = {"●": "•", "→": "->", "←": "<-", "≥": ">=", "≤": "<=", "≈": "~", "−": "-", "×": "x",
          "✓": "ok", "✔": "ok", "‘": "'", "’": "'", "“": '"', "”": '"', "…": "...", " ": " ",
          " ": " ", " ": " "}


def _clean(text: str) -> str:
    """The standard PDF fonts only cover Western characters: swap the odd symbol for a plain one, drop what has no match."""
    out = []
    for ch in text:
        ch = _CHARS.get(ch, ch)
        try:
            ch.encode("cp1252")
            out.append(ch)
        except UnicodeEncodeError:
            out.append(unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode("ascii"))
    return "".join(out)


def _hex(value: str) -> str | None:
    """"#rgb" / "#rrggbb" from a CSS color, or None. var(--x, #fallback) uses its fallback."""
    value = (value or "").strip()
    m = re.search(r"var\(\s*--[\w-]+\s*,\s*([^)]+)\)", value)
    if m:
        value = m.group(1).strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", value)
    if not m:
        return None
    h = m.group(1)
    return "#" + ("".join(c * 2 for c in h) if len(h) == 3 else h)


class _Reader(HTMLParser):
    """Collects the report body as items: (kind, markup) for text, ("table", rows), ("tiles", [(label, value)]), ("hero", dict),
    ("svg", n) and ("break", None) before every report page after the first."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list = []
        self.buf: list[str] = []
        self.skip = 0
        self.in_body = False
        self.stack: list[tuple[str, str, object]] = []      # (tag, class, forced-block flag or "hero")
        self.table: list | None = None
        self.row: list | None = None
        self.cell: list[str] | None = None
        self.cell_head = False
        self.cell_cls = ""
        self.first_page = True
        self.hero: dict | None = None
        self.tiles: list = []
        self.label = ""
        self.span_close: list[str] = []

    # ---- helpers
    def _emit(self, item) -> None:
        if self.tiles and item[0] not in ("label", "value"):
            self.items.append(("tiles", self.tiles))
            self.tiles = []
        self.items.append(item)

    def _in_cls(self, name: str) -> bool:
        return any(name in c.split() for _t, c, _f in self.stack)

    def _flush(self, kind: str | None = None) -> None:
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        text = re.sub(r"<b>\s*</b>", "", text)
        if not text or self.cell is not None:
            return
        kind = kind or self._kind()
        if kind == "label":
            self.label = text
        elif kind == "value":
            (self.hero["tiles"] if self.hero is not None else self.tiles).append((self.label, text))
            self.label = ""
        elif kind.startswith("hero:"):
            if self.hero is not None:
                self.hero[kind[5:]] = text
        else:
            self._emit((kind, text))

    def _kind(self) -> str:
        for pos in range(len(self.stack) - 1, -1, -1):
            tag, cls, _forced = self.stack[pos]
            c = f" {cls} "
            if self.hero is not None:
                for needle, key in ((" badge ", "hero:badge"), (" hero-title ", "hero:title"), (" hero-verdict ", "hero:verdict"),
                                    (" hero-note ", "hero:note")):
                    if needle in c:
                        return key
                if " hero-top " in c:
                    return "hero:meta"
                if " g-num " in c:
                    return "hero:num" if any(t == "strong" for t, _c, _f in self.stack[pos:]) else "hero:numlabel"
            if tag in ("h1", "h2", "h3", "h4"):
                return "title" if " rep-title " in c else ("h3" if tag == "h4" else tag)
            if " label " in c or " nw-tip-name " in c:
                return "label"
            if " value " in c:
                return "value"
            if " muted " in c or tag == "small":
                return "small"
            if tag == "li":
                return "li"
        return "p"

    # ---- parser callbacks
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "") or ""
        if tag == "body":
            self.in_body = True
        if not self.in_body:
            return
        if tag in _SKIP:
            self.skip += 1
            return
        if self.skip or tag in ("img", "input", "hr", "meta", "link"):
            return
        if tag == "div" and "data-svg" in a:
            self._flush()
            n = int(a["data-svg"])
            if self.hero is not None and self._in_cls("gauge"):
                self.hero["svg"] = n
            else:
                self._emit(("svg", n))
            return
        if tag == "section" and "rep-page" in cls:
            self._flush()
            if not self.first_page:
                self._emit(("break", None))
            self.first_page = False
        forced: object = False
        if tag == "div" and "hero" in cls.split() and self.hero is None:
            self._flush()
            m = re.search(r"tone-(\w+)", cls)
            self.hero, forced = {"tone": m.group(1) if m else "ok", "tiles": []}, "hero"
        elif self.hero is not None and tag in ("span", "strong") and ("badge" in cls or "muted" in cls or self._in_cls("g-num")):
            self._flush()
            forced = True
        if tag == "table":
            self._flush()
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell, self.cell_head, self.cell_cls = [], tag == "th", cls
            self.row.append(None)
        elif tag == "br":
            self._put("<br/>")
        elif tag == "span" and not forced:
            style, close = a.get("style", ""), ""
            dot = re.search(r"background:\s*(#[0-9a-fA-F]{3,6})", style)
            if "why" in cls.split() and self.table is None:
                self._put('<br/><font color="%s" size="9">' % MUTED)
                close = "</font>"
            elif dot and "dot" in cls.split():
                self._put('<font name="ZapfDingbats" color="%s">l</font> ' % dot.group(1))
            self.span_close.append(close)
        elif (tag in _BLOCK or forced) and self.table is None:
            self._flush()
        if tag in ("strong", "b", "h1", "h2", "h3", "th") and not forced:
            self._put("<b>")
        elif tag in ("em", "i"):
            self._put("<i>")
        elif tag == "small" and self.cell is not None:
            self._put('<br/><font size="8">')          # a note under a column heading goes on its own line
        if tag in _BLOCK or tag == "small" or forced:
            self.stack.append((tag, cls, forced))

    def handle_endtag(self, tag):
        if not self.in_body:
            return
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        top = self.stack[-1] if self.stack else None
        forced_end = bool(top and top[0] == tag and top[2])
        if tag in ("strong", "b", "h1", "h2", "h3", "th") and not forced_end:
            self._put("</b>")
        elif tag in ("em", "i"):
            self._put("</i>")
        elif tag == "small" and self.cell is not None:
            self._put("</font>")
        if tag == "span" and not forced_end and self.span_close:
            self._put(self.span_close.pop())
        if tag in ("span", "small", "strong", "b", "em", "i", "a"):
            self._put(" ")                       # pieces written side by side in the page (a name and its amount) need a gap
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            text = re.sub(r"\s+", " ", "".join(self.cell)).strip()
            self.row[-1] = (text, self.cell_head, "num" in self.cell_cls.split(), self.cell_cls)
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            self.table.append([c for c in self.row if c is not None])
            self.row = None
        elif tag == "table" and self.table is not None:
            if self.table:
                self._emit(("table", self.table))
            self.table = None
        elif (tag in _BLOCK or forced_end) and self.table is None:
            self._flush()
        if (tag in _BLOCK or tag == "small" or forced_end) and self.stack:
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    if any(f == "hero" for _t, _c, f in self.stack[i:]) and self.hero is not None:
                        self._emit(("hero", self.hero))
                        self.hero = None
                    del self.stack[i:]
                    break

    def _put(self, markup: str) -> None:
        (self.cell if self.cell is not None else self.buf).append(markup)

    def handle_data(self, data):
        if not self.in_body or self.skip:
            return
        text = _html.escape(_clean(data), quote=False)
        if self.cell is not None:
            self.cell.append(text)
        elif self.table is None:
            self.buf.append(text)

    def close(self):
        super().close()
        self._flush()
        if self.tiles:
            self.items.append(("tiles", self.tiles))
            self.tiles = []


def _tidy(markup: str) -> str:
    """Empty bold pairs and doubled spaces left by the reader."""
    markup = re.sub(r"<b>\s*</b>", "", markup)
    markup = re.sub(r"\s+", " ", markup)
    markup = re.sub(r"\s+((?:</[bi]>)*)([.,;:!?%)/])", r"\1\2", markup)      # no gap before punctuation that belongs to the word before
    return markup.strip()


# ---- the charts: a small reader for the SVG drawings the report page uses ----

def _style_of(el) -> dict:
    out = {}
    for part in (el.attrib.get("style") or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _svg_drawing(svg: str, width: float, tone: str = "ok"):
    """The chart as a reportlab Drawing scaled to `width`, or None when it cannot be read (the report then simply has no picture there)."""
    from reportlab.graphics.shapes import Circle, Drawing, Ellipse, Group, Line, PolyLine, Polygon, Rect, String
    from reportlab.lib import colors

    try:
        root = ET.fromstring(svg)
        _x0, _y0, vw, vh = (float(v) for v in re.split(r"[ ,]+", root.attrib["viewBox"].strip()))
    except (ET.ParseError, KeyError, ValueError):
        return None
    d = Drawing(vw, vh)

    def Y(y: float) -> float:
        return vh - y

    def num(el, key, default=0.0) -> float:
        try:
            return float(el.attrib.get(key, default))
        except ValueError:
            return default

    def paint(el, shape, *, fill_default=None, stroke_default=None):
        st = _style_of(el)
        fill = st.get("fill", el.attrib.get("fill", fill_default))
        stroke = st.get("stroke", el.attrib.get("stroke", stroke_default))
        fh, sh = _hex(fill or ""), _hex(stroke or "")
        def put(name, value):
            try:
                setattr(shape, name, value)
            except AttributeError:
                pass  # this shape type does not support the attribute

        if not isinstance(shape, (Line, PolyLine)):
            put("fillColor", colors.HexColor(fh) if fh else None)
            if "fill-opacity" in el.attrib and fh:
                put("fillOpacity", float(el.attrib["fill-opacity"]))
        put("strokeColor", colors.HexColor(sh) if sh else None)
        if "stroke-width" in el.attrib or sh:
            put("strokeWidth", num(el, "stroke-width", 1.0))
        dash = el.attrib.get("stroke-dasharray")
        if dash and sh:
            put("strokeDashArray", [float(v) for v in re.split(r"[ ,]+", dash.strip()) if v])
        return shape

    def points(raw: str) -> list[float]:
        nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", raw or "")]
        out: list[float] = []
        for i in range(0, len(nums) - 1, 2):
            out += [nums[i], Y(nums[i + 1])]
        return out

    def draw(el, into) -> None:
        st = _style_of(el)
        if "none" in st.get("display", "") or el.tag in ("title",):
            return
        tag = el.tag
        if tag == "line":
            into.add(paint(el, Line(num(el, "x1"), Y(num(el, "y1")), num(el, "x2"), Y(num(el, "y2"))), stroke_default="#d2d2d7"))
        elif tag == "rect":
            h = num(el, "height")
            into.add(paint(el, Rect(num(el, "x"), Y(num(el, "y")) - h, num(el, "width"), h)))
        elif tag == "circle":
            into.add(paint(el, Circle(num(el, "cx"), Y(num(el, "cy")), num(el, "r"))))
        elif tag == "ellipse":
            into.add(paint(el, Ellipse(num(el, "cx"), Y(num(el, "cy")), num(el, "rx"), num(el, "ry"))))
        elif tag == "polyline":
            pts = points(el.attrib.get("points", ""))
            if len(pts) >= 4:
                into.add(paint(el, PolyLine(pts), fill_default="none"))
        elif tag == "path":
            pts = points(el.attrib.get("d", ""))
            if len(pts) >= 6:
                into.add(paint(el, Polygon(pts)))
        elif tag == "text":
            anchor = {"middle": "middle", "end": "end"}.get(el.attrib.get("text-anchor", ""), "start")
            size = num(el, "font-size", 11.0)
            fill = _hex(st.get("fill", el.attrib.get("fill", "")) or "") or MUTED
            font = "Helvetica-Bold" if el.attrib.get("font-weight") in ("bold", "600", "700") else "Helvetica"
            x, y = num(el, "x"), num(el, "y")
            parts, cur = [], y
            if (el.text or "").strip():
                parts.append((cur, el.text.strip()))
            for span in el:
                if span.tag == "tspan":
                    cur += float(span.attrib.get("dy", 0) or 0)
                    if (span.text or "").strip():
                        parts.append((cur, span.text.strip()))
            g = Group()
            for py, txt in parts:
                g.add(String(x, Y(py), _clean(txt), fontName=font, fontSize=size, fillColor=colors.HexColor(fill), textAnchor=anchor))
            m = re.match(r"translate\(\s*([-\d.]+)[ ,]+([-\d.]+)\s*\)\s*rotate\(\s*(-?[\d.]+)\s*\)", el.attrib.get("transform", ""))
            if m:                                           # the y-axis title: moved to its spot and turned
                g = Group(*[String(0, 0, _clean(t), fontName=font, fontSize=size, fillColor=colors.HexColor(fill), textAnchor=anchor)
                            for _y, t in parts[:1]])
                g.translate(float(m.group(1)), Y(float(m.group(2))))
                g.rotate(-float(m.group(3)))
            into.add(g)
        elif tag == "g":
            for child in el:
                draw(child, into)

    if vw <= 140 and any(c.attrib.get("class") == "g-ring" for c in root.iter()):      # the dial: a grey track and a colored arc
        ring = next(c for c in root.iter() if c.attrib.get("class") == "g-ring")
        dash, off = num(ring, "stroke-dasharray", 1.0), num(ring, "stroke-dashoffset", 0.0)
        frac = max(0.0, min(1.0, 1.0 - off / dash)) if dash else 0.0
        cx, cy, r = num(ring, "cx", 66), num(ring, "cy", 66), num(ring, "r", 54)
        d.add(Circle(cx, Y(cy), r, fillColor=None, strokeColor=colors.HexColor("#e5e5e7"), strokeWidth=11))
        steps = max(2, int(frac * 90))
        pts: list[float] = []
        for i in range(steps + 1):
            ang = -math.pi / 2 + 2 * math.pi * frac * i / steps          # from the top, clockwise
            pts += [cx + r * math.cos(ang), Y(cy + r * math.sin(ang))]
        if frac > 0:
            d.add(PolyLine(pts, strokeColor=colors.HexColor(TONES.get(tone, TONES["ok"])[0]), strokeWidth=11, strokeLineCap=1))
    else:
        for child in root:
            draw(child, d)
    scale = width / vw if vw > width else 1.0
    d.width, d.height = vw * scale, vh * scale
    d.scale(scale, scale)
    return d


def report_pdf(page_html: str, *, brand: str | None = None, title: str = "Plan report") -> bytes:
    from source.common import branding

    brand = brand or branding.PRODUCT_NAME
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:                          # the Mac app is built with reportlab; a bare install may not have it
        raise ReportPdfUnavailable("PDF download needs the reportlab package.") from exc

    svgs: list[str] = []

    def grab(m):
        svgs.append(m.group(0))
        return f'<div data-svg="{len(svgs) - 1}"></div>'

    reader = _Reader()
    reader.feed(re.sub(r"<svg\b.*?</svg>", grab, page_html, flags=re.S))
    reader.close()

    C = colors.HexColor
    ink, muted, navy, rule = C(INK), C(MUTED), C(NAVY), C(RULE)
    page_w = letter[0] - 32 * mm
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=10, leading=13.5, textColor=ink)
    st = {
        "h1": ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=20, leading=24, spaceAfter=4, textColor=navy),
        "title": ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=17, leading=21, spaceBefore=2, spaceAfter=2, textColor=navy),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=13.5, leading=17, spaceBefore=12, spaceAfter=5, textColor=navy,
                             keepWithNext=1),
        "h3": ParagraphStyle("h3", parent=base, fontName="Helvetica-Bold", fontSize=11, leading=14, spaceBefore=10, spaceAfter=3, textColor=navy,
                             keepWithNext=1),
        "p": ParagraphStyle("p", parent=base, spaceAfter=4),
        "li": ParagraphStyle("li", parent=base, leftIndent=14, bulletIndent=3, spaceAfter=4),
        "small": ParagraphStyle("small", parent=base, fontSize=8.5, leading=11.5, textColor=muted, spaceAfter=3),
    }
    cell = ParagraphStyle("cell", parent=base, fontSize=8.8, leading=11)
    cell_r = ParagraphStyle("cell_r", parent=cell, alignment=TA_RIGHT)
    head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold", textColor=muted)
    head_r = ParagraphStyle("head_r", parent=head, alignment=TA_RIGHT)
    tile_label = ParagraphStyle("tl", parent=base, fontSize=7.5, leading=9.5, textColor=muted)
    tile_value = ParagraphStyle("tv", parent=base, fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=navy)

    def tiles_flowable(tiles, width):
        per = min(4, len(tiles)) or 1
        cells = [[[Paragraph(_tidy(l), tile_label), Paragraph(_tidy(v), tile_value)] for l, v in tiles[i:i + per]]
                 for i in range(0, len(tiles), per)]
        cells = [r + [""] * (per - len(r)) for r in cells]
        t = Table(cells, colWidths=[width / per] * per, hAlign="LEFT")
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), C("#f5f5f7")), ("BOX", (0, 0), (-1, -1), 0.4, rule),
                               ("INNERGRID", (0, 0), (-1, -1), 0.8, colors.white), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                               ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
        return t

    def hero_flowable(h):
        edge, tint = TONES.get(h.get("tone"), TONES["ok"])
        badge = ParagraphStyle("badge", parent=base, fontName="Helvetica-Bold", fontSize=9.5, textColor=C(edge))
        meta = ParagraphStyle("meta", parent=base, fontSize=8.5, textColor=muted, alignment=TA_RIGHT)
        htitle = ParagraphStyle("ht", parent=base, fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=navy)
        inner = page_w - 12
        ring = _svg_drawing(svgs[h["svg"]], 72, h.get("tone", "ok")) if "svg" in h else None
        right = []
        if h.get("numlabel"):
            right.append(Paragraph(_tidy(h["numlabel"]), ParagraphStyle("nl", parent=base, fontSize=8.5, textColor=muted)))
        if h.get("title"):
            right.append(Paragraph(_tidy(h["title"]), htitle))
        if h.get("verdict"):
            right.append(Paragraph(_tidy(h["verdict"]), ParagraphStyle("hv", parent=base, spaceBefore=3)))
        left = []
        if ring is not None:
            left.append(ring)
        if h.get("num"):
            left.append(Paragraph(_tidy(h["num"]), ParagraphStyle("hn", parent=base, fontName="Helvetica-Bold", fontSize=15, alignment=TA_CENTER,
                                                                   textColor=C(edge), leading=18)))
        rows = [[Paragraph(_tidy(h.get("badge", "")), badge) if h.get("badge") else "", Paragraph(_tidy(h.get("meta", "")), meta), ""],
                [left or "", right or "", ""]]
        spans = [("SPAN", (1, 1), (2, 1))]
        if h["tiles"]:
            rows.append([tiles_flowable(h["tiles"], inner), "", ""])
            spans.append(("SPAN", (0, 2), (2, 2)))
        if h.get("note"):
            rows.append([Paragraph(_tidy(h["note"]), ParagraphStyle("hnote", parent=base, fontSize=8.5, leading=11.5, textColor=muted)), "", ""])
            spans.append(("SPAN", (0, len(rows) - 1), (2, len(rows) - 1)))
        t = Table(rows, colWidths=[inner * 0.17, inner * 0.43, inner * 0.40], hAlign="LEFT")
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), C(tint)), ("LINEBEFORE", (0, 0), (0, -1), 4, C(edge)),
                               ("BOX", (0, 0), (-1, -1), 0.4, C(edge)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                               ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("SPAN", (1, 0), (2, 0)), *spans]))
        return t

    def table_flowable(payload):
        rows, cmds = [], []
        for ri, r in enumerate(payload):
            line = []
            for ci, (t, hd, right, cls) in enumerate(r):
                plain = re.sub(r"<[^>]+>", "", t).strip().lower()
                if hd:
                    sty = head_r if right else head
                    key = next((k for k in HEAD_BORDER if k in cls.split()), None)
                    if key:
                        sty = ParagraphStyle("hc", parent=sty, textColor=C(HEAD_BORDER[key]))
                        cmds.append(("LINEBELOW", (ci, ri), (ci, ri), 2.2, C(HEAD_BORDER[key])))
                else:
                    sty = cell_r if right else cell
                    if plain in STATUS:
                        sty = ParagraphStyle("sc", parent=sty, textColor=C(STATUS[plain]), fontName="Helvetica-Bold")
                line.append(Paragraph(_tidy(t) or "&nbsp;", sty))
            rows.append(line)
        width = max(len(r) for r in rows)
        rows = [r + [Paragraph("", cell)] * (width - len(r)) for r in rows]
        t = Table(rows, repeatRows=1 if payload and payload[0] and payload[0][0][1] else 0, hAlign="LEFT")
        first_head = bool(payload and payload[0] and payload[0][0][1])
        t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, rule), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                               ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                               *([("BACKGROUND", (0, 0), (-1, 0), C("#f5f5f7"))] if first_head else []), *cmds]))
        return t

    story: list = []
    for kind, payload in reader.items:
        if kind == "break":
            story.append(PageBreak())
        elif kind == "table":
            story += [table_flowable(payload), Spacer(1, 6)]
        elif kind == "tiles":
            story += [tiles_flowable(payload, page_w), Spacer(1, 6)]
        elif kind == "hero":
            story += [hero_flowable(payload), Spacer(1, 8)]
        elif kind == "svg":
            drawing = _svg_drawing(svgs[payload], page_w)
            if drawing is not None:
                story += [drawing, Spacer(1, 6)]
        elif kind == "title":
            story += [Paragraph(_tidy(payload), st["title"]), HRFlowable(width="100%", thickness=1, color=navy, spaceBefore=1, spaceAfter=8)]
        else:
            text = _tidy(payload)
            if text:
                story.append(Paragraph(text, st.get(kind, st["p"]), bulletText="•" if kind == "li" else None))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(muted)
        canvas.drawCentredString(letter[0] / 2, 10 * mm, f"{_clean(brand)} plan report  |  Page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=20 * mm,
                            title=_clean(title), author=_clean(brand))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
