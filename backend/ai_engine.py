import json
import logging
import os

import docx
import pypdf
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

logger = logging.getLogger(__name__)

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")


def _gemini_client():
    import google.generativeai as genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(GEMINI_MODEL)


def _has_key() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


# ── Pydantic models ───────────────────────────────────────────────────────────


class AccountMapping(BaseModel):
    account_name: str
    category: str = Field(
        description="One of: Asset, Liability, Equity, Revenue, Expense"
    )
    sub_category: str | None = Field(
        default=None, description="Detailed classification"
    )
    confidence: float


class FinancialAnalysis(BaseModel):
    liquidator_narrative: str = Field(
        description="Professional narrative for the liquidation report"
    )
    key_observations: list[str] = Field(
        description="Top 3-5 critical financial observations"
    )
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
    if not _has_key():
        return [
            AccountMapping(account_name=a, category="Asset", confidence=0.5)
            for a in accounts
        ]

    try:
        model = _gemini_client()
        prompt = f"""You are a senior forensic accountant specializing in company liquidations.
Classify each of the following accounting line items into one category: Asset, Liability, Equity, Revenue, or Expense.

Accounts:
{json.dumps(accounts, indent=2)}

Return a JSON array. Each element must have:
  - account_name: exact string from input
  - category: one of Asset, Liability, Equity, Revenue, Expense
  - sub_category: detailed classification (e.g. "Current Asset", "Trade Payable")
  - confidence: float 0.0-1.0

Output ONLY a valid JSON array, nothing else."""

        response = model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0,
            },
        )
        raw = response.text.strip()
        data = json.loads(raw)
        return [AccountMapping(**item) for item in data]
    except Exception as e:
        logger.error(f"ai_classify_accounts failed: {e}")
        return [
            AccountMapping(account_name=a, category="Asset", confidence=0.5)
            for a in accounts
        ]


# ── Financial narrative ───────────────────────────────────────────────────────


def generate_dynamic_narrative(financial_summary: dict) -> FinancialAnalysis:
    if not _has_key():
        return FinancialAnalysis(
            liquidator_narrative="Standard liquidation report narrative.",
            key_observations=["Verify all assets", "Settle outstanding liabilities"],
            risk_level="Medium",
        )

    try:
        model = _gemini_client()
        prompt = f"""You are an expert liquidator preparing a professional report narrative.
Given the financial summary below, write a concise liquidator's narrative and list key observations.

Financial Data:
{json.dumps(financial_summary, indent=2, default=str)}

Return a JSON object with:
  - liquidator_narrative: professional 2-3 sentence narrative
  - key_observations: list of 3-5 critical observations
  - risk_level: "Low", "Medium", or "High"

Output ONLY valid JSON."""

        response = model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.3,
            },
        )
        data = json.loads(response.text.strip())
        return FinancialAnalysis(**data)
    except Exception as e:
        logger.error(f"generate_dynamic_narrative failed: {e}")
        return FinancialAnalysis(
            liquidator_narrative="The assets and liabilities of the company are as disclosed in the Statement of Financial Position.",
            key_observations=[
                "All assets have been verified",
                "Outstanding liabilities are to be settled",
            ],
            risk_level="Medium",
        )


# ── LaTeX template generation (legacy fallback) ───────────────────────────────


def generate_latex_template_from_sample(file_path: str, context_keys: list[str]) -> str:
    """
    Legacy: generate a Jinja-LaTeX template from a sample document's extracted text.
    Used only when the DOCX template engine is unavailable (no LibreOffice).
    """
    text = extract_text_from_file(file_path)
    if not text.strip():
        return ""

    if not _has_key():
        return (
            "\\documentclass{article}\\begin{document}"
            f"Mock Template for {os.path.basename(file_path)}"
            "\\end{document}"
        )

    try:
        model = _gemini_client()
        prompt = f"""You are an expert LaTeX developer. Convert the text below (extracted from an accounting report)
into a fully compiling Jinja-LaTeX template that preserves the document's sections, tables, and structure.

Use these custom Jinja2 delimiters to avoid LaTeX conflicts:
  Variables: \\VAR{{{{ Variable_Name }}}}
  Blocks:    \\BLOCK{{{{ for item in list }}}} ... \\BLOCK{{{{ endfor }}}}

Available data context keys: {", ".join(context_keys)}
Examples: \\VAR{{{{ Entity_Details['Company Name'] }}}}, \\VAR{{{{ Totals['Total Assets'] }}}}

Rules:
- Output ONLY raw LaTeX (no markdown fences, no explanations)
- Must include \\documentclass{{article}}, \\begin{{document}}, \\end{{document}}
- Preserve all section headings, table structures, and spacing from the source

Document text:
{text[:8000]}"""

        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.1},
        )
        latex = response.text.strip()
        # Strip any accidental markdown fences
        for fence in ("```latex", "```"):
            if latex.startswith(fence):
                latex = latex[len(fence) :]
        if latex.endswith("```"):
            latex = latex[:-3]
        return latex.strip()
    except Exception as e:
        logger.error(f"generate_latex_template_from_sample failed: {e}")
        return ""
