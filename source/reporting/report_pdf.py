"""Turns the plan report page (/report.html) into a PDF file you can download, without a browser's print dialog.

The report page is plain HTML that this program writes itself, so a small reader that knows its handful of tags (headings, paragraphs,
tables, lists, boxes) is enough. It is made with reportlab (pure Python, so it also works inside the Mac app). Charts are pictures
drawn in the browser and are left out; every number and table in the report is kept. If reportlab is missing the caller gets
ReportPdfUnavailable and the page keeps its Print button."""

from __future__ import annotations

import html as _html
import io
import re
import unicodedata
from html.parser import HTMLParser


class ReportPdfUnavailable(RuntimeError):
    pass


_SKIP = {"script", "style", "svg", "button", "title", "noscript"}      # tags whose whole contents are left out (not void tags like img)
_BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "section", "summary", "tr", "ul", "ol", "table", "details"}
_CHARS = {"●": "•", "→": "->", "←": "<-", "≥": ">=", "≤": "<=", "≈": "~", "−": "-", "×": "x",
          "✓": "ok", "✔": "ok", "•": "•", "—": "—", "–": "–", "·": "·",
          "‘": "'", "’": "'", "“": '"', "”": '"', "…": "...", " ": " ", " ": " ", " ": " "}


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


class _Reader(HTMLParser):
    """Collects the report body as a list of items: ("h1"|"h2"|"h3"|"p"|"li"|"small"|"label"|"value", markup), ("table", rows) and
    ("break", None) before every report page after the first."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list = []
        self.buf: list[str] = []
        self.skip = 0
        self.in_body = False
        self.stack: list[tuple[str, str]] = []          # (tag, class) of the open block elements
        self.table: list | None = None
        self.row: list | None = None
        self.cell: list[str] | None = None
        self.cell_head = False
        self.first_page = True
        self.bold = 0
        self.ital = 0

    # ---- helpers
    def _flush(self, kind: str | None = None) -> None:
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        if not text or text in ("<b></b>",):
            return
        if self.cell is not None:
            return
        self.items.append((kind or self._kind(), text))

    def _kind(self) -> str:
        for tag, cls in reversed(self.stack):
            c = f" {cls} "
            if tag in ("h1", "h2", "h3", "h4"):
                return "h3" if tag == "h4" else tag
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
        if tag == "section" and "rep-page" in cls:
            self._flush()
            if not self.first_page:
                self.items.append(("break", None))
            self.first_page = False
        if tag == "table":
            self._flush()
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell, self.cell_head = [], tag == "th"
            self.row.append(None)
        elif tag == "br":
            if self.cell is not None:
                self.cell.append("<br/>")
            else:
                self.buf.append("<br/>")
        elif tag in _BLOCK and self.table is None:
            self._flush()
        if tag in ("strong", "b", "h1", "h2", "h3", "th"):
            self._put("<b>")
        elif tag in ("em", "i"):
            self._put("<i>")
        if tag in _BLOCK or tag == "small":
            self.stack.append((tag, cls))
        if tag in ("td", "th") and "num" in cls.split():
            self.row[-1] = "num"

    def handle_endtag(self, tag):
        if not self.in_body:
            return
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in ("strong", "b", "h1", "h2", "h3", "th"):
            self._put("</b>")
        elif tag in ("em", "i"):
            self._put("</i>")
        if tag in ("span", "small", "strong", "b", "em", "i", "a"):
            self._put(" ")                       # pieces written side by side in the page (a name and its amount) need a gap
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            right = self.row[-1] == "num"
            text = re.sub(r"\s+", " ", "".join(self.cell)).strip()
            self.row[-1] = (text, self.cell_head, right)
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            self.table.append([c for c in self.row if c is not None])
            self.row = None
        elif tag == "table" and self.table is not None:
            if self.table:
                self.items.append(("table", self.table))
            self.table = None
        elif tag in _BLOCK and self.table is None:
            self._flush()
        if (tag in _BLOCK or tag == "small") and self.stack:
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
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


def _tidy(markup: str) -> str:
    """Empty bold pairs and doubled spaces left by the reader."""
    markup = re.sub(r"<b>\s*</b>", "", markup)
    markup = re.sub(r"\s+", " ", markup)
    markup = re.sub(r"\s+((?:</[bi]>)*)([.,;:!?%)/])", r"\1\2", markup)      # no gap before punctuation that belongs to the word before
    return markup.strip()


def report_pdf(page_html: str, *, brand: str | None = None, title: str = "Plan report") -> bytes:
    from source.common import branding

    brand = brand or branding.PRODUCT_NAME
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_RIGHT
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:                          # the Mac app is built with reportlab; a bare install may not have it
        raise ReportPdfUnavailable("PDF download needs the reportlab package.") from exc

    reader = _Reader()
    reader.feed(page_html)
    reader.close()

    ink, muted, navy = colors.HexColor("#1d1d1f"), colors.HexColor("#6e6e73"), colors.HexColor("#1d3557")
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=10, leading=13.5, textColor=ink)
    st = {
        "h1": ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=20, leading=24, spaceAfter=4, textColor=navy),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=15, leading=19, spaceBefore=10, spaceAfter=6, textColor=navy),
        "h3": ParagraphStyle("h3", parent=base, fontName="Helvetica-Bold", fontSize=11.5, leading=15, spaceBefore=10, spaceAfter=3, keepWithNext=1),
        "p": ParagraphStyle("p", parent=base, spaceAfter=4),
        "li": ParagraphStyle("li", parent=base, leftIndent=14, bulletIndent=3, spaceAfter=3),
        "small": ParagraphStyle("small", parent=base, fontSize=8.5, leading=11.5, textColor=muted, spaceAfter=3),
        "label": ParagraphStyle("label", parent=base, fontSize=8, leading=10, textColor=muted, spaceBefore=4),
        "value": ParagraphStyle("value", parent=base, fontName="Helvetica-Bold", fontSize=12.5, leading=15, spaceAfter=2),
    }
    cell = ParagraphStyle("cell", parent=base, fontSize=8.8, leading=11)
    cell_r = ParagraphStyle("cell_r", parent=cell, alignment=TA_RIGHT)
    head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold", textColor=muted)
    head_r = ParagraphStyle("head_r", parent=head, alignment=TA_RIGHT)

    story: list = []
    for kind, payload in reader.items:
        if kind == "break":
            story.append(PageBreak())
        elif kind == "table":
            rows = []
            for r in payload:
                rows.append([Paragraph(_tidy(t) or "&nbsp;", (head_r if right else head) if hd else (cell_r if right else cell)) for t, hd, right in r])
            width = max(len(r) for r in rows)
            rows = [r + [Paragraph("", cell)] * (width - len(r)) for r in rows]
            t = Table(rows, repeatRows=1 if payload and payload[0] and payload[0][0][1] else 0, hAlign="LEFT")
            t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#d2d2d7")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
            story += [t, Spacer(1, 6)]
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
