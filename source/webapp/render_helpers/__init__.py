"""Page chrome, formatting helpers, and chart rendering shared across two
or more dashboard pages (or used directly by the Handler class).

Split out of dashboard.py so each individual page module only pulls in
the pieces it actually needs, while everything genuinely cross-page --
the CSS/nav/page shell, money/percent formatting, the donut and bar
chart renderers, and the editable-cell HTML builders used by more than
one page's tables -- lives in exactly one place.

This used to be a single ~1100-line render_helpers.py file; it's now a
package of small, single-purpose modules (styles/shell/formatting/cells/
tables/charts/drawdown_rows) so each piece of chrome can be found and
changed on its own. Nothing outside this package should need to change:
every name any page module or test previously imported with
`from source.webapp.render_helpers import X` is re-exported here
unchanged, from the same place.
"""

from __future__ import annotations

from source.webapp.render_helpers.styles import PAGE_CSS
from source.webapp.render_helpers.shell import (
    NAV_ITEMS,
    PAGE_SHELL,
    _nav_html,
    _shell,
    _sync_now_button_html,
)
from source.webapp.render_helpers.formatting import (
    _account_number_display,
    _format_number_input_value,
    _money,
    _money_short,
    _pct,
    _TAX_TREATMENT_OPTIONS,
)
from source.webapp.render_helpers.cells import (
    _editable_checkbox_cell,
    _editable_number_cell,
    _editable_select_cell,
    _editable_text_cell,
    _effective_balance_html,
    _link_select_html,
    _loan_cell_html,
)
from source.webapp.render_helpers.tables import (
    _asset_category_summary_html,
    _asset_rollup_summary_html,
)
from source.webapp.render_helpers.drawdown_rows import (
    _visible_rows_by_year,
    _withdrawal_parts,
    _withdrawn_ending_cells_html,
    _withdrawn_ending_header_html,
)
from source.webapp.render_helpers.charts import (
    _DONUT_COLORS,
    _DONUT_OTHER_COLOR,
    _bar_chart_html,
    _donut_chart_html,
    _grouped_slices,
    _line_chart_html,
    _multi_line_chart_html,
)

__all__ = [
    "PAGE_CSS",
    "NAV_ITEMS",
    "PAGE_SHELL",
    "_nav_html",
    "_shell",
    "_sync_now_button_html",
    "_account_number_display",
    "_format_number_input_value",
    "_money",
    "_money_short",
    "_pct",
    "_TAX_TREATMENT_OPTIONS",
    "_editable_checkbox_cell",
    "_editable_number_cell",
    "_editable_select_cell",
    "_editable_text_cell",
    "_effective_balance_html",
    "_link_select_html",
    "_loan_cell_html",
    "_asset_category_summary_html",
    "_asset_rollup_summary_html",
    "_visible_rows_by_year",
    "_withdrawal_parts",
    "_withdrawn_ending_cells_html",
    "_withdrawn_ending_header_html",
    "_DONUT_COLORS",
    "_DONUT_OTHER_COLOR",
    "_bar_chart_html",
    "_donut_chart_html",
    "_grouped_slices",
    "_line_chart_html",
    "_multi_line_chart_html",
]
