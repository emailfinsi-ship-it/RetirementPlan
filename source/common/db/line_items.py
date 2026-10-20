"""Generic line-item CRUD shared by every editable table with the same
shape (assets / real_estate / expenses / income / account_tax_splits:
add, list, update, delete by id) -- one implementation parameterized by
`section` instead of five near-identical copies, backing the Asset/Real
Estate/Expense/Income tabs' add/edit/delete actions, plus the Drawdown
Planning tab's "split a linked account across tax buckets" feature,
alike.
"""

from __future__ import annotations

from source.common.db.connection import _now, connect


_TABLE_COLUMNS = {
    "assets": ("kind", "category", "name", "institution", "last4", "balance", "notes", "source", "linked_account_id", "tax_treatment", "include_in_monte_carlo", "owner"),
    "real_estate": ("name", "purchase_price", "current_value", "ownership_pct", "loan_balance", "annual_income", "notes", "source", "linked_account_id", "include_in_monte_carlo", "loan_end_year", "address", "value_updated_at"),
    "expenses": ("name", "category", "annual_amount", "start_year", "end_year", "base_year", "inflates", "notes", "source", "linked_category"),
    "income": ("name", "category", "annual_amount", "start_year", "end_year", "base_year", "inflates", "notes", "source", "include_in_monte_carlo", "linked_category"),
    "account_tax_splits": ("account_id", "name", "tax_treatment", "amount"),
}



def _table(section: str) -> str:
    if section not in _TABLE_COLUMNS:
        raise ValueError(f"Unknown section: {section!r}. Expected one of {sorted(_TABLE_COLUMNS)}.")
    return section



# Every line-item table's editable inputs post their value as a JSON
# string (dashboard.py's updateField()/updateCategoryField() JS always
# sends this.value, whatever the <input> looks like) -- add_line_item/
# update_line_item coerce those strings to the right SQLite type so a
# blank Start Year/End Year/Base Year clears to NULL instead of storing
# the literal text "" into an INTEGER column (which would then blow up
# any later `year < row["start_year"]` comparison with a str/int
# TypeError), and a blank/malformed money field falls back to 0.0
# instead of storing unparseable text. A value that's already a Python
# number/None (every internal db.py caller, e.g. the xlsx importer)
# passes through untouched.
_NULLABLE_INT_FIELDS = {"start_year", "end_year", "base_year", "loan_end_year"}

_NUMERIC_FIELDS = {
    "balance", "purchase_price", "current_value", "ownership_pct",
    "loan_balance", "annual_income", "annual_amount", "amount",
}

_INT_FLAG_FIELDS = {"inflates", "include_in_monte_carlo"}

# assets.owner -- see source.common.db.owners.owner_options(). Duplicated
# as a literal rather than imported to keep this module's import graph
# unchanged; owners.normalize_owner is the one place that logic lives
# for callers outside this file.
_OWNER_VALUES = {"", "self", "spouse"}



def clean_number_text(value: str) -> str:
    """"$42,000" / "42,000" / " 42 000 " -> "42000". Anything else is returned trimmed."""
    text = str(value).strip()
    cleaned = text.replace("$", "").replace(",", "").replace(" ", "")
    try:
        float(cleaned)
    except ValueError:
        return text
    return cleaned


def _coerce_line_item_value(field: str, value):
    if not isinstance(value, str):
        return value
    value = value.strip()
    if field in _NULLABLE_INT_FIELDS or field in _NUMERIC_FIELDS or field in _INT_FLAG_FIELDS:
        value = clean_number_text(value)
    if field in _NULLABLE_INT_FIELDS:
        if value == "":
            return None
        try:
            return int(float(value))
        except ValueError:
            return None
    if field in _NUMERIC_FIELDS:
        try:
            return float(value)
        except ValueError:
            return 0.0
    if field in _INT_FLAG_FIELDS:
        try:
            return int(float(value))
        except ValueError:
            return 0
    if field == "owner":
        return value.lower() if value.lower() in _OWNER_VALUES else ""
    return value



def add_line_item(section: str, fields: dict) -> int:
    table = _table(section)
    columns = _TABLE_COLUMNS[table]
    row = {c: _coerce_line_item_value(c, fields.get(c)) for c in columns if c in fields}
    name = row.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("A line item needs a name.")
    row["name"] = name.strip()
    now = _now()
    col_names = list(row.keys()) + ["created_at", "updated_at"]
    placeholders = ", ".join("?" for _ in col_names)
    values = list(row.values()) + [now, now]
    with connect() as conn:
        cur = conn.execute(
            f"INSERT INTO {table} ({', '.join(col_names)}) VALUES ({placeholders})",
            values,
        )
        return cur.lastrowid



def list_line_items(section: str) -> list[dict]:
    table = _table(section)
    with connect() as conn:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        return [dict(r) for r in rows]



def get_line_item(section: str, item_id: int) -> dict | None:
    table = _table(section)
    with connect() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else None



def update_line_item(section: str, item_id: int, fields: dict) -> bool:
    table = _table(section)
    columns = _TABLE_COLUMNS[table]
    row = {c: _coerce_line_item_value(c, fields[c]) for c in columns if c in fields}
    if not row:
        return False
    if "name" in row:
        name = row["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("A line item needs a name.")
        row["name"] = name.strip()
    row["updated_at"] = _now()
    set_clause = ", ".join(f"{c} = ?" for c in row)
    with connect() as conn:
        cur = conn.execute(f"UPDATE {table} SET {set_clause} WHERE id = ?", list(row.values()) + [item_id])
        return cur.rowcount > 0



def delete_line_item(section: str, item_id: int) -> bool:
    table = _table(section)
    with connect() as conn:
        cur = conn.execute(f"DELETE FROM {table} WHERE id = ?", (item_id,))
        return cur.rowcount > 0



def clear_section(section: str, *, source: str | None = None) -> int:
    """Delete every row in a section (optionally only rows with a given
    `source`, e.g. wiping only previously-imported rows before a
    re-import without touching anything the user typed in by hand)."""
    table = _table(section)
    with connect() as conn:
        if source:
            cur = conn.execute(f"DELETE FROM {table} WHERE source = ?", (source,))
        else:
            cur = conn.execute(f"DELETE FROM {table}")
        return cur.rowcount
