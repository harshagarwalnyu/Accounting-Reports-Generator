from unittest.mock import MagicMock, patch

import pandas as pd

import ai_engine
import ingestion


def _make_mock_xl(df):
    mock_xl = MagicMock()
    mock_xl.sheet_names = ["Sheet1"]
    mock_xl.parse.return_value = df
    return mock_xl


def test_load_and_process_data_basic():
    data = {
        "Main Mapping": [
            "Cash",
            "Accounts Payable",
            "Revenue",
            "General and administrative expenses",
        ],
        "Sub Mapping": [None, None, None, "Rent"],
        "Amount-25": [1000, -500, -2000, 800],
        "Amount-24": [900, -400, -1800, 750],
    }
    df = pd.DataFrame(data)

    with patch("pandas.ExcelFile", return_value=_make_mock_xl(df)):
        result = ingestion.load_and_process_data("mock.xlsx", use_ai=False)

    assert result["Totals"]["Total Assets"] == 1000.0
    assert result["Totals"]["Total Liabilities & Equity"] == -500.0
    # Net Profit = -(Revenue + Expense) = -(-2000 + 800) = 1200
    assert result["Totals"]["Net Profit/Loss"] == 1200.0
    assert result["Financial Position"]["Assets"]["Cash"]["current"] == 1000.0
    assert result["Financial Position"]["Assets"]["Cash"]["prior"] == 900.0
    assert "Accounts Payable" in result["Financial Position"]["Liabilities & Equity"]


def test_load_and_process_data_empty():
    df = pd.DataFrame()
    with patch("pandas.ExcelFile", return_value=_make_mock_xl(df)):
        result = ingestion.load_and_process_data("empty.xlsx")
    assert result is None


def test_load_and_process_data_unrecognized_columns():
    data = {"Col A": [1, 2], "Col B": [3, 4]}
    df = pd.DataFrame(data)
    with patch("pandas.ExcelFile", return_value=_make_mock_xl(df)):
        result = ingestion.load_and_process_data("bad_cols.xlsx")
    assert result is None


def test_load_and_process_data_pl_only():
    data = {
        "Account": ["Revenue", "Expense"],
        "Amount": [-1000, 800],
    }
    df = pd.DataFrame(data)
    with patch("pandas.ExcelFile", return_value=_make_mock_xl(df)):
        result = ingestion.load_and_process_data("pl_only.xlsx")

    assert result["Financial Position"]["Assets"] == {}
    assert result["Financial Position"]["Liabilities & Equity"] == {}
    assert result["Totals"]["Net Profit/Loss"] == 200.0


def test_load_and_process_data_string_coercion():
    data = {
        "Account": ["Cash", "Payables"],
        "Amount": ["1000.50", "-500"],
        "Prior": ["900", "invalid"],
    }
    df = pd.DataFrame(data)
    with patch("pandas.ExcelFile", return_value=_make_mock_xl(df)):
        result = ingestion.load_and_process_data("coercion.xlsx")

    assert result["Financial Position"]["Assets"]["Cash"]["current"] == 1000.50
    assert result["Financial Position"]["Assets"]["Cash"]["prior"] == 900.0
    assert result["Financial Position"]["Liabilities & Equity"]["Payables"]["prior"] == 0.0


def test_load_and_process_data_multisheet():
    df1 = pd.DataFrame(
        {
            "Main Mapping": ["Cash", "Revenue"],
            "Amount-25": [500, -1000],
            "Amount-24": [400, -900],
        }
    )
    df2 = pd.DataFrame(
        {
            "Main Mapping": ["Equipment", "Loan expense"],
            "Amount-25": [2000, 300],
            "Amount-24": [1800, 250],
        }
    )

    mock_xl = MagicMock()
    mock_xl.sheet_names = ["Sheet1", "Sheet2"]
    # parse is called once per sheet in the multi-sheet detection loop
    mock_xl.parse.side_effect = [df1, df2]

    with patch("pandas.ExcelFile", return_value=mock_xl):
        result = ingestion.load_and_process_data("multi.xlsx", use_ai=False)

    assert result is not None
    assert "Cash" in result["Financial Position"]["Assets"]
    assert "Equipment" in result["Financial Position"]["Assets"]


def test_ai_classify_accounts_no_key(monkeypatch):
    monkeypatch.setattr(ai_engine, "client", None)
    results = ai_engine.ai_classify_accounts(["Cash", "Revenue"])
    assert len(results) == 2
    assert all(r.category == "Asset" for r in results)
    assert all(r.confidence == 0.5 for r in results)


def test_generate_dynamic_narrative_no_key(monkeypatch):
    monkeypatch.setattr(ai_engine, "client", None)
    result = ai_engine.generate_dynamic_narrative({"Totals": {"Total Assets": 1000}})
    assert result.liquidator_narrative
    assert result.risk_level in ("Low", "Medium", "High")
    assert len(result.key_observations) >= 1
