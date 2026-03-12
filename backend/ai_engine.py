import os
import instructor
from openai import OpenAI
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from dotenv import load_dotenv

load_dotenv()

# SOTA: Using Instructor for guaranteed structured output from LLMs
# This replaces manual regex and heuristic mapping.
client = instructor.patch(OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "sk-dummy")))

class AccountMapping(BaseModel):
    account_name: str
    category: str = Field(description="One of: Asset, Liability, Equity, Revenue, Expense")
    sub_category: Optional[str] = Field(description="Detailed classification (e.g., Current Asset, Operating Expense)")
    confidence: float

class FinancialAnalysis(BaseModel):
    liquidator_narrative: str = Field(description="Professional narrative for the liquidator report based on the financial health.")
    key_observations: List[str] = Field(description="Top 3-5 critical financial observations for the liquidator.")
    risk_level: str = Field(description="Risk level for the liquidation process (Low, Medium, High).")

def ai_classify_accounts(accounts: List[str]) -> List[AccountMapping]:
    """
    SOTA: Multi-account classification using LLM agents.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        # Fallback for local dev if no key
        return [AccountMapping(account_name=a, category="Asset", confidence=0.5) for a in accounts]

    return client.chat.completions.create(
        model="gpt-4o", # 2026 SOTA choice
        response_model=List[AccountMapping],
        messages=[
            {"role": "system", "content": "You are a senior forensic accountant specializing in liquidations."},
            {"role": "user", "content": f"Classify the following accounting lines for a liquidation report: {', '.join(accounts)}"}
        ],
    )

def generate_dynamic_narrative(financial_summary: Dict) -> FinancialAnalysis:
    """
    SOTA: Dynamic narrative generation instead of static templates.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        return FinancialAnalysis(
            liquidator_narrative="Standard liquidation report narrative.",
            key_observations=["Verify assets", "Settle liabilities"],
            risk_level="Medium"
        )

    return client.chat.completions.create(
        model="gpt-4o",
        response_model=FinancialAnalysis,
        messages=[
            {"role": "system", "content": "You are an expert liquidator. Generate a professional report narrative."},
            {"role": "user", "content": f"Financial Data Summary: {financial_summary}"}
        ],
    )
