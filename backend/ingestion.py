import json
import logging
import os

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import ai_engine
except ImportError:
    ai_engine = None

# ── Column detection ──────────────────────────────────────────────────────────

# Common column name patterns for each field
_NAME_CANDIDATES = [
    "Main Mapping",
    "Account",
    "Account Name",
    "Description",
    "Line Item",
    "Particulars",
    "Mapping",
]
_CY_CANDIDATES = [
    "Amount-25",
    "Amount_25",
    "2025",
    "CY",
    "Current Year",
    "Current",
    "Amount (2025)",
    "FY2025",
    "Amount",
]
_PY_CANDIDATES = [
    "Amount-24",
    "Amount_24",
    "2024",
    "PY",
    "Prior Year",
    "Prior",
    "Amount (2024)",
    "FY2024",
]
_SUB_CANDIDATES = [
    "Sub Mapping",
    "Sub Category",
    "Sub Account",
    "Sub",
]
_CAT_CANDIDATES = [
    "Category",
    "Type",
    "Classification",
    "Group",
]


def _match_column(df_cols, candidates):
    """Return first column name that matches a candidate (case-insensitive)."""
    cols_lower = {c.lower(): c for c in df_cols}
    for cand in candidates:
        if cand in df_cols:
            return cand
        if cand.lower() in cols_lower:
            return cols_lower[cand.lower()]
    return None


def _ai_detect_columns(df: pd.DataFrame) -> dict:
    """Use Claude to detect column purposes from a preview of the DataFrame."""
    from ai_engine import SONNET, client

    if client is None:
        return {}

    preview_rows = df.head(4).fillna("").to_dict(orient="records")
    col_list = list(df.columns)

    tools = [
        {
            "name": "detect_columns",
            "description": "Identify which column serves each role in a trial balance spreadsheet",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name_col": {"type": "string", "description": "Account names column"},
                    "cy_col": {"type": "string", "description": "Current year amounts column"},
                    "py_col": {
                        "type": ["string", "null"],
                        "description": "Prior year amounts column",
                    },
                    "sub_col": {"type": ["string", "null"], "description": "Sub-category column"},
                    "category_col": {
                        "type": ["string", "null"],
                        "description": "Category/type column",
                    },
                },
                "required": ["name_col", "cy_col"],
            },
        }
    ]

    try:
        response = client.messages.create(
            model=SONNET,
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": (
                        "You are a data analyst identifying which columns in a trial-balance "
                        "spreadsheet serve which role (account name, current-year amount, "
                        "prior-year amount, sub-category, category). Always respond via the "
                        "detect_columns tool. Never invent column names — use only those provided."
                    ),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=tools,
            tool_choice={"type": "tool", "name": "detect_columns"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Column names: {col_list}\n"
                        f"First 4 rows sample:\n{json.dumps(preview_rows, default=str)}\n"
                        "Identify which column serves each role in this trial balance."
                    ),
                }
            ],
        )
        for block in response.content:
            if block.type == "tool_use":
                return block.input
    except Exception as e:
        logger.error("AI column detection failed (%s): %s", type(e).__name__, e)

    return {}


def detect_columns(df: pd.DataFrame) -> dict:
    """
    Auto-detect Excel column mapping.
    Returns dict with keys: name_col, cy_col, py_col, sub_col, category_col.
    """
    cols = list(df.columns)
    mapping = {
        "name_col": _match_column(cols, _NAME_CANDIDATES),
        "cy_col": _match_column(cols, _CY_CANDIDATES),
        "py_col": _match_column(cols, _PY_CANDIDATES),
        "sub_col": _match_column(cols, _SUB_CANDIDATES),
        "category_col": _match_column(cols, _CAT_CANDIDATES),
    }

    # If name or cy not found, try AI
    if not mapping["name_col"] or not mapping["cy_col"]:
        ai = _ai_detect_columns(df)
        for key in mapping:
            if not mapping[key] and ai.get(key):
                mapping[key] = ai[key]

    return mapping


# ── Core processing ───────────────────────────────────────────────────────────


def load_and_process_data(file_path: str, use_ai: bool = False) -> dict | None:
    try:
        xl = pd.ExcelFile(file_path)
    except Exception as e:
        logger.error("Error loading Excel: %s", e)
        return None

    if len(xl.sheet_names) == 1:
        try:
            df = xl.parse(xl.sheet_names[0])
        except Exception as e:
            logger.error("Error parsing Excel: %s", e)
            return None
    else:
        valid_dfs = []
        for sheet in xl.sheet_names:
            try:
                sheet_df = xl.parse(sheet)
                col_map = detect_columns(sheet_df)
                if col_map.get("name_col") and col_map.get("cy_col"):
                    sheet_df["_sheet_hint"] = sheet
                    valid_dfs.append(sheet_df)
            except Exception as e:
                logger.warning("Skipping sheet %r: %s", sheet, e)
        if not valid_dfs:
            logger.error("No valid sheets found with recognized columns")
            return None
        df = pd.concat(valid_dfs, ignore_index=True)

    if df.empty:
        logger.error("Excel file is empty")
        return None

    col_map = detect_columns(df)
    name_col = col_map.get("name_col")
    cy_col = col_map.get("cy_col")
    py_col = col_map.get("py_col")
    sub_col = col_map.get("sub_col")

    if not name_col or not cy_col:
        logger.error(
            f"Cannot identify required columns. Detected: {col_map}. Available: {list(df.columns)}"
        )
        return None

    # Filter rows with empty account names
    df = df[df[name_col].notna() & (df[name_col].astype(str).str.strip() != "")]

    # Coerce amounts to numeric
    df[cy_col] = pd.to_numeric(df[cy_col], errors="coerce").fillna(0)
    if py_col and py_col in df.columns:
        df[py_col] = pd.to_numeric(df[py_col], errors="coerce").fillna(0)

    # AI account classification
    if use_ai and ai_engine and os.environ.get("ANTHROPIC_API_KEY"):
        unique_mappings = df[name_col].unique().tolist()
        ai_mappings = ai_engine.ai_classify_accounts(unique_mappings)
        ai_map = {m.account_name: m.category for m in ai_mappings}
    else:
        ai_map = {}

    # Group by account name
    agg_cols = {cy_col: "sum"}
    if py_col and py_col in df.columns:
        agg_cols[py_col] = "sum"
    grouped = df.groupby(name_col).agg(agg_cols)

    financial_position = {"Assets": {}, "Liabilities & Equity": {}}

    for mapping, row in grouped.iterrows():
        cy_val = float(row[cy_col])
        py_val = float(row[py_col]) if py_col and py_col in row else 0.0

        entry = {"current": cy_val, "prior": py_val}

        mapping_lower = str(mapping).lower()
        # Exclude P&L items from Statement of Financial Position if they match keywords
        if any(kw in mapping_lower for kw in ["revenue", "expense", "income", "cost of"]):
            continue

        category = ai_map.get(mapping)
        if category == "Asset":
            financial_position["Assets"][mapping] = entry
        elif category in ("Liability", "Equity"):
            financial_position["Liabilities & Equity"][mapping] = entry
        else:
            # Heuristic: positive → Asset, negative → Liability/Equity
            if cy_val >= 0:
                financial_position["Assets"][mapping] = entry
            else:
                financial_position["Liabilities & Equity"][mapping] = entry

    # Notes: sub-mapping breakdown for expense accounts
    notes = {}
    if sub_col and sub_col in df.columns:
        expense_rows = df[df[name_col].astype(str).str.contains("expense", case=False, na=False)]
        if not expense_rows.empty:
            for main_name in expense_rows[name_col].unique():
                sub_df = expense_rows[expense_rows[name_col] == main_name]
                if sub_col in sub_df.columns:
                    sub_grouped = sub_df.groupby(sub_col)[cy_col].sum()
                    notes[main_name] = {str(k): float(v) for k, v in sub_grouped.items()}

    # Totals
    total_assets = sum(v["current"] for v in financial_position["Assets"].values())
    total_liab_equity = sum(
        v["current"] for v in financial_position["Liabilities & Equity"].values()
    )

    rev_mask = df[name_col].astype(str).str.contains("revenue", case=False, na=False)
    exp_mask = df[name_col].astype(str).str.contains("expense", case=False, na=False)
    revenue_sum = float(df[rev_mask][cy_col].sum())
    expense_sum = float(df[exp_mask][cy_col].sum())
    net_profit = -(revenue_sum + expense_sum)

    return {
        "Financial Position": financial_position,
        "Notes": notes,
        "Totals": {
            "Total Assets": total_assets,
            "Total Liabilities & Equity": total_liab_equity,
            "Net Profit/Loss": net_profit,
        },
        "_column_map": col_map,
    }


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "trial_balance.xlsx"
    data = load_and_process_data(path)
    if data:
        print(json.dumps(data, indent=2, default=str))
