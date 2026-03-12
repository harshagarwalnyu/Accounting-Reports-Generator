import pandas as pd
import json
import os
try:
    import ai_engine
except ImportError:
    ai_engine = None

def load_and_process_data(file_path, use_ai=False):
    # Load the data
    try:
        df = pd.read_excel(file_path)
    except Exception as e:
        print(f"Error loading Excel: {e}")
        return None

    # Validate columns
    required_cols = ['Main Mapping', 'Amount-25', 'Amount-24']
    if not all(col in df.columns for col in required_cols):
        missing = [c for c in required_cols if c not in df.columns]
        print(f"Missing required columns in Excel: {missing}")
        return None

    # Filter out rows where Main Mapping is empty
    df = df[df['Main Mapping'].notna() & (df['Main Mapping'].astype(str).str.strip() != '')]

    # Convert amounts to numeric, coercing errors to 0 just in case
    df['Amount-25'] = pd.to_numeric(df['Amount-25'], errors='coerce').fillna(0)
    df['Amount-24'] = pd.to_numeric(df['Amount-24'], errors='coerce').fillna(0)

    # --- SOTA: AI-Enhanced Mapping ---
    if use_ai and ai_engine and os.environ.get("OPENAI_API_KEY"):
        unique_mappings = df['Main Mapping'].unique().tolist()
        ai_mappings = ai_engine.ai_classify_accounts(unique_mappings)
        mapping_dict = {m.account_name: m.category for m in ai_mappings}
    else:
        mapping_dict = {}

    # 1. Financial Position Dictionary
    grouped = df.groupby('Main Mapping')[['Amount-25', 'Amount-24']].sum()
    
    financial_position = {
        "Assets": {},
        "Liabilities & Equity": {}
    }

    for mapping, row in grouped.iterrows():
        entry = {
            "Amount-25": float(row['Amount-25']),
            "Amount-24": float(row['Amount-24'])
        }
        
        # Use AI classification if available, otherwise fallback to sign heuristic
        category = mapping_dict.get(mapping)
        if category == "Asset":
             financial_position["Assets"][mapping] = entry
        elif category in ["Liability", "Equity"]:
             financial_position["Liabilities & Equity"][mapping] = entry
        else:
             # Heuristic fallback
             if row['Amount-25'] >= 0:
                  financial_position["Assets"][mapping] = entry
             else:
                  financial_position["Liabilities & Equity"][mapping] = entry

    # 2. Notes Dictionary
    # For "General and administrative expenses", group by Sub Mapping
    gaa_expenses = df[df['Main Mapping'] == "General and administrative expenses"]
    unique_subs = gaa_expenses['Sub Mapping'].unique()
    
    notes = {}
    if not gaa_expenses.empty:
        notes["General and administrative expenses"] = {}
        grouped_sub = gaa_expenses.groupby('Sub Mapping')[['Amount-25']].sum()
        for sub, row in grouped_sub.iterrows():
            notes["General and administrative expenses"][sub] = float(row['Amount-25'])
            
    # 3. Calculate Totals
    # Total Assets
    total_assets = sum(item['Amount-25'] for item in financial_position['Assets'].values())
    
    # Total Liabilities & Equity
    total_liab_equity = sum(item['Amount-25'] for item in financial_position['Liabilities & Equity'].values())
    
    # Net Profit/Loss (Revenue - Expenses)
    # In a TB, Revenue is usually Credit (Negative) and Expenses are Debit (Positive).
    # Profit = Revenue (abs) - Expenses
    # OR simpler: Net P/L = Sum of all P&L accounts.
    # In a balanced TB, Assets + Liab + Equity + Revenue + Expenses = 0
    # So: Assets + Liab + Equity + (Net Profit implied in Retained Earnings if closed, or separate if not) = 0
    # Let's assume standard P&L items are those NOT in Assets/Liab/Equity if those are explicitly defined?
    # Actually, simpler: Sum of everything usually = 0.
    # Net Profit from P/L items: Sum of Revenue (neg) + Expenses (pos). 
    # Result: If Negative -> Net Profit (Credit balance), If Positive -> Net Loss.
    # Visual check: Revenue (-50k) + Exp (40k) = -10k (Profit of 10k).
    # The user asks: "Verified logic: Revenue - Expenses".
    # Let's calculate purely based on what is NOT Asset/Liab/Equity? 
    # Or rely on specific "Revenue" and "Expense" keywords in Mapping?
    # Let's look for "Revenue" and "Expense" in Main Mapping.
    
    pnl_df = df[df['Main Mapping'].str.contains('Revenue|Expense', case=False, na=False)]
    # Revenue is credit (-), Exp is debit (+). 
    # Net Profit = Total Revenue (positive number) - Total Expenses (positive number).
    # So we need to flip signs for Revenue if it's stored as negative.
    
    # Let's do:
    # Revenue_Rows = Main Mapping contains 'Revenue'
    # Expense_Rows = Main Mapping contains 'Expense'
    
    rev_mask = df['Main Mapping'].str.contains('Revenue', case=False, na=False)
    exp_mask = df['Main Mapping'].str.contains('Expense', case=False, na=False)
    
    # Sum current year
    revenue_sum = float(df[rev_mask]['Amount-25'].sum()) # Likely negative
    expense_sum = float(df[exp_mask]['Amount-25'].sum()) # Likely positive
    
    # Net Profit = (Revenue * -1) - Expense (if revenue is neg)
    # Actually, standard formula: Net Profit = Revenue - Expenses.
    # If Revenue is -50k (Credit) and Expense is 40k (Debit). Sum is -10k. 
    # Usually -10k implies Profit to be moved to Retained Earnings (Credit).
    # Let's report the absolute value of Profit, or the signed value?
    # "Net Profit/Loss for the period (Revenue - Expenses)" suggests user wants the magnitude/direction.
    # Let's calculate: Abs(Revenue) - Abs(Expenses) ? 
    # Or just -(Revenue + Expenses) to get positive Profit?
    # Let's stick to: Profit = -(Sum of P&L items).
    
    net_profit = -(revenue_sum + expense_sum)

    # Construct Final Output
    output = {
        "Financial Position": financial_position,
        "Notes": notes,
        "Totals": {
            "Total Assets": total_assets,
            "Total Liabilities & Equity": total_liab_equity,
            "Net Profit/Loss": net_profit
        }
    }
    
    return output

if __name__ == "__main__":
    import json
    data = load_and_process_data("trial_balance.xlsx")
    if data:
        print(json.dumps(data, indent=4))
