import pytest
import pandas as pd
import ingestion
from unittest.mock import MagicMock, patch

def test_load_and_process_data_basic():
    # Mock dataframe
    data = {
        'Main Mapping': ['Cash', 'Accounts Payable', 'Revenue', 'General and administrative expenses'],
        'Sub Mapping': [None, None, None, 'Rent'],
        'Amount-25': [1000, -500, -2000, 800],
        'Amount-24': [900, -400, -1800, 750]
    }
    df = pd.DataFrame(data)
    
    with patch('pandas.read_excel', return_value=df):
        result = ingestion.load_and_process_data("mock.xlsx", use_ai=False)
        
    assert result['Totals']['Total Assets'] == 1000.0
    assert result['Totals']['Total Liabilities & Equity'] == -500.0
    # Net Profit = -(Revenue + Expense) = -(-2000 + 800) = 1200
    assert result['Totals']['Net Profit/Loss'] == 1200.0
    assert "Cash" in result['Financial Position']['Assets']
    assert "Accounts Payable" in result['Financial Position']['Liabilities & Equity']
