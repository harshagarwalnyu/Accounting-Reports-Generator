import json
import logging
import os

import anthropic
import docx
import pypdf
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()
logger = logging.getLogger(__name__)

SONNET = "claude-sonnet-4-6"
OPUS = "claude-opus-4-7"

client = (
    anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    if os.getenv("ANTHROPIC_API_KEY")
    else None
)


# ── Pydantic models ───────────────────────────────────────────────────────────


class AccountMapping(BaseModel):
    account_name: str
    category: str = Field(description="One of: Asset, Liability, Equity, Revenue, Expense")
    sub_category: str | None = Field(default=None, description="Detailed classification")
    confidence: float


class FinancialAnalysis(BaseModel):
    liquidator_narrative: str = Field(
        description="Professional narrative for the liquidation report"
    )
    key_observations: list[str] = Field(description="Top 3-5 critical financial observations")
    risk_level: str = Field(description="Low, Medium, or High")


# ── File extraction ───────────────────────────────────────────────────────────


def extract_text_from_file(file_path: str) -> str:
    ext = file_path.lower().rsplit(".", 1)[-1]
    text = ""
    try:
        if ext == "pdf":
            with open(file_path, "rb") as f:
                reader = pypdf.PdfReader(f)
                for page in reader.pages:
                    text += (page.extract_text() or "") + "\n"
        elif ext in ("docx", "doc"):
            doc = docx.Document(file_path)
            for para in doc.paragraphs:
                text += para.text + "\n"
        else:
            with open(file_path, encoding="utf-8") as f:
                text = f.read()
    except Exception as e:
        logger.error(f"Failed to read {file_path}: {e}")
    return text


# ── Account classification ────────────────────────────────────────────────────


def ai_classify_accounts(accounts: list[str]) -> list[AccountMapping]:
    if client is None:
        return [AccountMapping(account_name=a, category="Asset", confidence=0.5) for a in accounts]

    system_prompt = """You are a senior forensic accountant specializing in company liquidations.
Classify each accounting line item into exactly one category:
Asset, Liability, Equity, Revenue, or Expense.
Sub-categories examples: Current Asset, Fixed Asset, Current Liability, Long-term Liability,
Shareholders Equity, Operating Revenue, Direct Expense, Administrative Expense."""

    tools = [
        {
            "name": "classify_accounts",
            "description": "Return classification for every account provided",
            "input_schema": {
                "type": "object",
                "properties": {
                    "classifications": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "account_name": {"type": "string"},
                                "category": {
                                    "type": "string",
                                    "enum": [
                                        "Asset",
                                        "Liability",
                                        "Equity",
                                        "Revenue",
                                        "Expense",
                                    ],
                                },
                                "sub_category": {"type": "string"},
                                "confidence": {"type": "number"},
                            },
                            "required": ["account_name", "category", "confidence"],
                        },
                    }
                },
                "required": ["classifications"],
            },
        }
    ]

    try:
        response = client.messages.create(
            model=SONNET,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=tools,
            tool_choice={"type": "tool", "name": "classify_accounts"},
            messages=[
                {
                    "role": "user",
                    "content": f"Classify these accounts:\n{json.dumps(accounts)}",
                }
            ],
        )
        for block in response.content:
            if block.type == "tool_use":
                items = block.input.get("classifications", [])
                return [AccountMapping(**item) for item in items]
    except Exception as e:
        logger.warning("ai_classify_accounts failed (%s): %s", type(e).__name__, e)

    return [AccountMapping(account_name=a, category="Asset", confidence=0.5) for a in accounts]


# ── Field identification (moved from template_engine.py) ─────────────────────

FIELD_SCHEMA = {
    "company_name": "company or entity name",
    "address": "company address or registered office",
    "license_number": "trade license, CR number, or registration number",
    "manager_name": "director, manager, or authorized officer name",
    "liquidator_name": "liquidator or appointed professional name",
    "report_date": "date of this report",
    "liquidation_start_date": "date liquidation commenced",
    "period_end_date": "period end or financial year end date",
    "liquidator_narrative": "professional narrative paragraph >50 words about the company's "
    "financial position, written in accounting/legal language — mark entire paragraph as "
    "liquidator_narrative",
}


def _ai_identify_fields(text_blocks: list[str]) -> dict[str, str]:
    if client is None:
        return {}

    tools = [
        {
            "name": "identify_fields",
            "description": "Map exact text blocks to field names",
            "input_schema": {
                "type": "object",
                "properties": {
                    "mappings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "field_name": {"type": "string"},
                            },
                            "required": ["text", "field_name"],
                        },
                    }
                },
                "required": ["mappings"],
            },
        }
    ]

    field_descriptions = json.dumps(FIELD_SCHEMA, indent=2)
    blocks_sample = json.dumps(text_blocks[:80])

    try:
        response = client.messages.create(
            model=SONNET,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": (
                        "You are an expert document analyst for accounting and legal reports. "
                        "Given a list of text blocks extracted from a document, "
                        "identify which blocks "
                        "contain dynamic per-client data matching the provided field schema. "
                        "Any block longer than 50 words written in professional "
                        "accounting or legal language "
                        "about the company's financial status should be mapped to "
                        "field_name 'liquidator_narrative'. "
                        f"Field schema:\n{field_descriptions}"
                    ),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=tools,
            tool_choice={"type": "tool", "name": "identify_fields"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Identify which of these text blocks are dynamic per-client data "
                        f"matching the field schema above:\n{blocks_sample}"
                    ),
                }
            ],
        )
        for block in response.content:
            if block.type == "tool_use":
                items = block.input.get("mappings", [])
                return {
                    mapping["text"]: mapping["field_name"]
                    for mapping in items
                    if mapping.get("text") and mapping.get("field_name")
                }
    except Exception as e:
        logger.warning("_ai_identify_fields failed (%s): %s", type(e).__name__, e)

    return {}


# ── Financial narrative ───────────────────────────────────────────────────────


def generate_dynamic_narrative(financial_summary: dict) -> FinancialAnalysis:
    if client is None:
        return FinancialAnalysis(
            liquidator_narrative="The assets and liabilities of the company are as disclosed "
            "in the Statement of Financial Position.",
            key_observations=[
                "All assets have been verified",
                "Outstanding liabilities are to be settled",
            ],
            risk_level="Medium",
        )

    system_prompt = """You are an expert liquidator preparing a professional report narrative.
Follow this chain-of-thought:
Step 1: Quote the exact Revenue figure from the provided data.
Step 2: Quote the exact Total Assets figure from the data.
Step 3: Calculate solvency ratio = Total Assets / Total Liabilities (use the data, not assumptions).
Step 4: Assess risk (Low if ratio >1.5x, Medium if 1.0-1.5x, High if <1.0x).
Step 5: Write a 2-3 sentence professional narrative using ONLY the quoted figures from steps 1-2.
Never invent or assume any numbers not present in the data."""

    tools = [
        {
            "name": "write_narrative",
            "description": "Write the liquidation report narrative based on financial data",
            "input_schema": {
                "type": "object",
                "properties": {
                    "liquidator_narrative": {
                        "type": "string",
                        "description": "Professional 2-3 sentence narrative "
                        "for the liquidation report",
                    },
                    "key_observations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Top 3-5 critical financial observations",
                    },
                    "risk_level": {
                        "type": "string",
                        "enum": ["Low", "Medium", "High"],
                        "description": "Overall risk assessment",
                    },
                },
                "required": ["liquidator_narrative", "key_observations", "risk_level"],
            },
        }
    ]

    try:
        response = client.messages.create(
            model=OPUS,
            max_tokens=2048,
            system=system_prompt,
            tools=tools,
            tool_choice={"type": "tool", "name": "write_narrative"},
            messages=[
                {
                    "role": "user",
                    "content": "Financial data:\n"
                    + json.dumps(financial_summary, indent=2, default=str),
                }
            ],
        )
        for block in response.content:
            if block.type == "tool_use":
                return FinancialAnalysis(**block.input)
    except Exception as e:
        logger.warning("generate_dynamic_narrative failed (%s): %s", type(e).__name__, e)

    return FinancialAnalysis(
        liquidator_narrative="The assets and liabilities of the company are as disclosed "
        "in the Statement of Financial Position.",
        key_observations=[
            "All assets have been verified",
            "Outstanding liabilities are to be settled",
        ],
        risk_level="Medium",
    )
