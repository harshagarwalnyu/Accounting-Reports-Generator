from unittest.mock import patch

import pandas as pd

import ingestion


def test_load_and_process_data_basic():
    # Mock dataframe
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

    with patch("pandas.read_excel", return_value=df):
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
    with patch("pandas.read_excel", return_value=df):
        result = ingestion.load_and_process_data("empty.xlsx")
    assert result is None


def test_load_and_process_data_unrecognized_columns():
    data = {"Col A": [1, 2], "Col B": [3, 4]}
    df = pd.DataFrame(data)
    with patch("pandas.read_excel", return_value=df):
        result = ingestion.load_and_process_data("bad_cols.xlsx")
    assert result is None


def test_load_and_process_data_pl_only():
    data = {
        "Account": ["Revenue", "Expense"],
        "Amount": [-1000, 800],
    }
    df = pd.DataFrame(data)
    with patch("pandas.read_excel", return_value=df):
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
    with patch("pandas.read_excel", return_value=df):
        result = ingestion.load_and_process_data("coercion.xlsx")
    
    assert result["Financial Position"]["Assets"]["Cash"]["current"] == 1000.50
    assert result["Financial Position"]["Assets"]["Cash"]["prior"] == 900.0
    assert result["Financial Position"]["Liabilities & Equity"]["Payables"]["prior"] == 0.0
