import json
import os
import logging
from jinja2 import Environment, BaseLoader

logger = logging.getLogger(__name__)

try:
    import ai_engine
except ImportError:
    ai_engine = None
TEX_TEMPLATE = r"""
\documentclass[a4paper,12pt]{article}
\usepackage{geometry}
\geometry{a4paper, margin=1in}
\usepackage{fancyhdr}
\usepackage{booktabs}
\usepackage{graphicx}
\usepackage{titlesec}
\usepackage{longtable}

% Header and Footer
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\VAR{ Entity_Details['Company Name'] }}
\fancyfoot[C]{Page \thepage}

\title{\textbf{\Huge \VAR{ Entity_Details['Company Name'] }}}
\author{Liquidator's Report}
\date{\VAR{ Dates['Report Date'] }}

\begin{document}

% --- Cover Page ---
\begin{titlepage}
    \centering
    \vspace*{2cm}
    
    {\Huge \textbf{\VAR{ Entity_Details['Company Name'] }} \par}
    \vspace{1.5cm}
    {\Large \textbf{Liquidator's Report} \par}
    \vspace{1.5cm}
    {\Large \VAR{ Dates['Report Date'] } \par}
    
    \vfill
    
\end{titlepage}

% --- Table of Contents ---
\tableofcontents
\newpage

% --- Statement of Accounts ---
\section{Statement of Accounts}

\begin{table}[h]
    \centering
    \begin{tabular}{ll}
        \toprule
        \textbf{Details} & \textbf{Information} \\
        \midrule
        Company Name & \VAR{ Entity_Details['Company Name'] } \\
        License No & \VAR{ Entity_Details['License Number'] } \\
        Manager & \VAR{ Entity_Details['Manager Name'] } \\
        Liquidator & \VAR{ Signatories['Liquidator Name'] } \\
        \bottomrule
    \end{tabular}
\end{table}

\vspace{1cm}

% --- Liquidator's Report ---
\section{Liquidator's Report}

\VAR{ liquidator_statement_assets }

\VAR{ liquidator_statement_liabilities }

\newpage

% --- Statement of Financial Position ---
\section{Statement of Financial Position}

\begin{table}[h!]
    \centering
    \begin{tabular}{lrr}
        \toprule
        \textbf{Particulars} & \textbf{Current Year (AED)} & \textbf{Prior Year (AED)} \\
        \midrule
        \multicolumn{3}{l}{\textbf{ASSETS}} \\
        \BLOCK{ for name, amounts in Financial_Position.Assets.items() }
            \VAR{ name } & \VAR{ amounts['Amount-25'] | currency } & \VAR{ amounts['Amount-24'] | currency } \\
        \BLOCK{ endfor }
        \textbf{Total Assets} & \textbf{\VAR{ Totals['Total Assets'] | currency }} & \\
        
        \midrule
        \multicolumn{3}{l}{\textbf{LIABILITIES \& EQUITY}} \\
        \BLOCK{ for name, amounts in Financial_Position['Liabilities & Equity'].items() }
            \VAR{ name } & \VAR{ amounts['Amount-25'] | currency } & \VAR{ amounts['Amount-24'] | currency } \\
        \BLOCK{ endfor }
        
        \textbf{Net Profit/Loss} & \textbf{\VAR{ Totals['Net Profit/Loss'] | currency }} & \\
        
        \midrule
        \textbf{Total Liabilities \& Equity} & \textbf{\VAR{ Totals['Total Liabilities & Equity'] | currency }} & \\
        \bottomrule
    </tabular}
\end{table}

\newpage

% --- Notes ---
\section{Notes to the Financial Statements}

\subsection*{General and Administrative Expenses}

\begin{table}[h]
    \centering
    \begin{tabular}{lr}
        \toprule
        \textbf{Description} & \textbf{Amount (AED)} \\
        \midrule
        \BLOCK{ for name, amount in Notes['General and administrative expenses'].items() }
        \VAR{ name } & \VAR{ amount | currency } \\
        \BLOCK{ endfor }
        \bottomrule
    \end{tabular}
\end{table}

\end{document}
"""

def format_currency(value):
    """
    Formats a number as a string with commas and parentheses for negatives.
    Example: -1234.56 -> (1,234.56)
             1234.56 -> 1,234.56
    """
    try:
        val = float(value)
    except (ValueError, TypeError):
        return str(value)
    
    is_negative = val < 0
    abs_val = abs(val)
    formatted = "{:,.2f}".format(abs_val)
    
    if is_negative:
        return f"({formatted})"
    return formatted

def generate_tex(data_context, use_ai=False):
    """
    Generates the LaTeX report using the provided data context.
    Argument:
        data_context: Dictionary containing merged config and financial data.
    """
    import ai_engine
    
    # Extract Data for Logic
    financial_position = data_context.get('Financial Position', {})
    totals = data_context.get('Totals', {})
    
    total_assets = totals.get('Total Assets', 0.0)
    liab_equity = financial_position.get('Liabilities & Equity', {})
    
    total_liabilities = 0.0
    for mapping_name, entry in liab_equity.items():
        if not any(x in mapping_name.lower() for x in ['equity', 'capital', 'reserve', 'retained', 'profit', 'loss']):
            total_liabilities += entry.get('Amount-25', 0.0)
    
    # --- SOTA: AI Narrative Generation ---
    if use_ai and os.environ.get("OPENAI_API_KEY"):
        analysis = ai_engine.generate_dynamic_narrative(data_context)
        text_assets = analysis.liquidator_narrative
        text_liabilities = f"Key Observations: {', '.join(analysis.key_observations)}"
    else:
        # Heuristic Fallback
        has_assets = total_assets > 0
        has_liabilities = total_liabilities < 0
        if not has_assets and not has_liabilities:
            text_assets = "As on the date of liquidation, there were no assets."
            text_liabilities = "All creditors of the company have been settled and there are no claims."
        else:
            text_assets = "The assets of the company are disclosed in the Statement of Financial Position."
            text_liabilities = "Outstanding liabilities are to be settled by the shareholders as per the attached undertaking."

    # Prepare Context
    context = data_context.copy()
    context['liquidator_statement_assets'] = text_assets
    context['liquidator_statement_liabilities'] = text_liabilities

    # Create Jinja2 Environment with custom delimiters to avoid LaTeX conflict
    env = Environment(
        loader=BaseLoader(),
        block_start_string='\BLOCK{',
        block_end_string='}',
        variable_start_string='\VAR{',
        variable_end_string='}',
        comment_start_string='\#{',
        comment_end_string='}',
        line_statement_prefix='%%',
        line_comment_prefix='%#',
        trim_blocks=True,
        autoescape=False
    )
    
    # Register filter
    env.filters['currency'] = format_currency
    
    # Create template
    try:
        template = env.from_string(TEX_TEMPLATE)
        # Render
        tex_output = template.render(**context)
        
        # Save
        with open('liquidation_report.tex', 'w') as f:
            f.write(tex_output)
        
        print("Successfully generated liquidation_report.tex with dynamic narratives.")
        print(f"Narrative Selected: {'Scenario B' if has_assets or has_liabilities else 'Scenario A'}")
    except Exception as e:
        print(f"Error generating LaTeX: {e}")

if __name__ == "__main__":
    # For testing, we can load output.json if it exists and mock config
    # But usually main.py will handle this.
    pass
