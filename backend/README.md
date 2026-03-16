# Accounting Reports Generator — Backend

FastAPI service for generating professional accounting and liquidation reports.

## Prerequisites
- Python 3.12+
- [uv](https://astral.sh/uv)
- LibreOffice (for PDF generation from DOCX)

## Setup
```bash
cd backend
uv sync
```

## Running
```bash
uv run uvicorn main:app --reload
```

## Configuration
Copy `.env.example` to `.env` and set `GEMINI_API_KEY`.
