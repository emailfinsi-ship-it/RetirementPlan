"""Plain value -> string formatting helpers with no HTML-building logic
of their own (money/percent/compact-money formatting, and the number-
input-value formatter that avoids scientific notation) -- used directly
by page modules and by the HTML-building helpers in cells.py/charts.py
alike.
"""

from __future__ import annotations

import html

# (stored value, label) pairs for any "Tax treatment" dropdown -- shared
# by the Asset tab's own per-row Tax treatment column and the Drawdown
# Planning tab's "split a linked account across tax buckets" feature, so
# the same three choices (and the same fixed order -- Tax-deferred
# first, since _editable_select_cell falls back to the first option
# when a stored value matches none of them) are offered everywhere a
# user picks one, rather than two lists that could drift apart.
_TAX_TREATMENT_OPTIONS = (
    ("tax_deferred", "Tax-deferred (401k/Traditional)"),
    ("roth", "Roth (tax-free)"),
    ("taxable", "Taxable (brokerage)"),
)


def _money(value, *, cents: bool = False) -> str:
    """Dollars with thousands commas, rounded to whole dollars ("$465,966")
    for easy reading; cents=True keeps two decimals (individual
    transactions, where $4.50 must not read as $5)."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "--"
    places = 2 if cents else 0
    rounded = round(value, places)
    if rounded == 0:
        rounded = 0.0   # never "-$0"
    body = f"{abs(rounded):,.{places}f}"
    return f"-${body}" if rounded < 0 else f"${body}"


def _format_money_input_value(value) -> str:
    """A stored dollar amount for an editable money cell: thousands commas,
    cents only when the stored value has them ("1,290,000", "1,234.56")."""
    number = float(value or 0)
    if round(number, 2) == round(number):
        return f"{round(number):,.0f}".replace("-0", "0") if round(number) == 0 else f"{round(number):,.0f}"
    return f"{number:,.2f}"


def _pct(assumptions: dict, key: str, default="") -> str:
    """Formats an assumptions value (stored as a decimal, e.g. 0.06) as a
    percent string for a form field's value= (e.g. "6.00"). Shared by the
    Summary page's "what if" card and the Will my money last? tab's full
    assumptions form -- both edit the same underlying row via
    /api/assumptions, so they always agree with each other."""
    try:
        return f'{float(assumptions.get(key, default)) * 100:.2f}'
    except (TypeError, ValueError):
        return html.escape(str(assumptions.get(key, default)))


def _account_number_display(mask: str, account_number: str | None, is_tokenized: bool = False, *, mask_prefix: str = "") -> str:
    """The full account number when we have one -- only ever present for
    a checking/savings/cash-management account whose Item requested
    Plaid's Auth product (source.collector.sync); investment, loan, and
    credit accounts never get one, Auth simply doesn't cover them. Falls
    back to the same masked "1234" (or "...1234" with mask_prefix set)
    this always showed otherwise. A tokenized number (a few OAuth banks
    substitute a TAN for the real one) is flagged so it doesn't read as
    the genuine account number."""
    if account_number:
        return account_number + (" (tokenized)" if is_tokenized else "")
    return f"{mask_prefix}{mask}" if mask else ""


def _format_number_input_value(value: float) -> str:
    """Renders a stored number for a number input's value= attribute
    without ever switching to scientific notation. The previous
    formatting (Python's `:g`) flips to exponential past 6 significant
    digits -- a real-estate Purchase Price/Current Value or a large
    manually-entered Asset balance hits that easily (e.g. 1,600,000
    became the literal text "1.6e+06" in the input box, which is what
    the browser then displayed -- not a column-width/truncation issue).
    Worse, `:g`'s default precision also loses digits outright once a
    number needs more than 6 significant figures, e.g. 3336607.99
    silently became "3.33661e+06" (rounded to the nearest $10). Python's
    str()/repr() on a float never uses scientific notation within any
    realistic dollar/percentage/year range this app deals with (only at
    roughly 1e16+ or 1e-5-) and always round-trips the exact value --
    this just trims a bare trailing ".0" so a whole number still reads
    as "365000", not "365000.0", matching the old :g output there."""
    text = repr(float(value))
    if text.endswith(".0"):
        text = text[:-2]
    return "0" if text == "-0" else text


def _money_short(value: float) -> str:
    sign = "-" if value < 0 else ""
    value = abs(value or 0)
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{sign}${value / 1_000:.0f}K"
    return f"{sign}${value:.0f}"
