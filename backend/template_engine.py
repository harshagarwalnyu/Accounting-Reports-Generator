"""
Template Engine — Format-Fidelity Core

The key insight: don't ask the LLM to reproduce formatting.
Use the sample document AS the template — clone it, replace only the data values.
Format is preserved because we're working with the original DOCX structure.

Pipeline:
  Sample DOCX/PDF
    → convert to DOCX if needed (pdf2docx)
    → extract text blocks
    → AI identifies which blocks are dynamic (company name, dates, etc.)
    → replace those with {{field_name}} placeholders
    → store annotated DOCX as reusable template

Generation:
  Template DOCX + financial data
    → replace {{field_name}} placeholders with real values
    → rebuild financial tables with actual line items (preserving row styling)
    → LibreOffice headless → PDF
"""

import json
import logging
import os
import re
import shutil
import subprocess
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from docx.table import _Row as TableRow

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path("templates")


def _ensure_templates_dir():
    TEMPLATES_DIR.mkdir(exist_ok=True)


# ── Text replacement helpers ──────────────────────────────────────────────────


def _replace_in_paragraph(para, old_text: str, new_text: str) -> bool:
    """Replace text in a paragraph handling split runs. Returns True if replaced."""
    if old_text not in para.text:
        return False

    # Fast path: contained in a single run
    for run in para.runs:
        if old_text in run.text:
            run.text = run.text.replace(old_text, new_text)
            return True

    # Slow path: text is split across runs — merge into first run
    # NOTE: merging runs destroys individual run formatting (bold, italic, etc.) 
    # except for the first run's style. This is acceptable for template creation phase.
    full = "".join(r.text for r in para.runs)
    if old_text in full:
        if para.runs:
            para.runs[0].text = full.replace(old_text, new_text)
            for r in para.runs[1:]:
                r.text = ""
        return True

    return False


def _replace_in_doc(doc, old_text: str, new_text: str):
    """Replace text throughout an entire python-docx Document."""
    if not old_text:
        return

    for para in doc.paragraphs:
        _replace_in_paragraph(para, old_text, new_text)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    _replace_in_paragraph(para, old_text, new_text)

    for section in doc.sections:
        for part in [
            section.header,
            section.footer,
            section.even_page_header,
            section.even_page_footer,
            section.first_page_header,
            section.first_page_footer,
        ]:
            try:
                if part and not part.is_linked_to_previous:
                    for para in part.paragraphs:
                        _replace_in_paragraph(para, old_text, new_text)
            except Exception:
                pass


# ── Currency formatting ───────────────────────────────────────────────────────


def _fmt(value) -> str:
    try:
        val = float(value)
        s = f"{abs(val):,.2f}"
        return f"({s})" if val < 0 else s
    except (ValueError, TypeError):
        return str(value)


# ── DOCX table manipulation ───────────────────────────────────────────────────

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _insert_data_row(table, template_row, cell_values: list[str], anchor=None):
    """Insert a new row after anchor (or template_row), copying style from template_row."""
    from lxml import etree

    new_tr = deepcopy(template_row._tr)
    cells = new_tr.findall(f"{{{W}}}tc")

    for cell_el, value in zip(cells, cell_values):
        paragraphs = cell_el.findall(f".//{{{W}}}p")
        for para_el in paragraphs:
            # Remove existing runs
            for child in list(para_el):
                if child.tag != f"{{{W}}}pPr":
                    para_el.remove(child)
            
            # Find rPr from THIS cell's first run (not the whole row)
            cell_runs = cell_el.findall(f".//{{{W}}}r")
            rPr_copy = None
            if cell_runs:
                rPr = cell_runs[0].find(f"{{{W}}}rPr")
                if rPr is not None:
                    rPr_copy = deepcopy(rPr)
            
            # Add new run
            r_el = etree.SubElement(para_el, f"{{{W}}}r")
            if rPr_copy is not None:
                r_el.insert(0, rPr_copy)
            t_el = etree.SubElement(r_el, f"{{{W}}}t")
            t_el.text = str(value)
            if str(value).startswith(" ") or str(value).endswith(" "):
                t_el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            break  # only first paragraph per cell

    insert_point = anchor if anchor is not None else template_row
    insert_point._tr.addnext(new_tr)
    return TableRow(new_tr, table)


# ── AI helpers ────────────────────────────────────────────────────────────────


def _extract_text_blocks(doc) -> list[str]:
    blocks = []
    for para in doc.paragraphs:
        t = para.text.strip()
        if t and t not in blocks:
            blocks.append(t)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                t = cell.text.strip()
                if t and t not in blocks:
                    blocks.append(t)
    return blocks


def _ai_identify_fields(text_blocks: list[str]) -> dict[str, str]:
    """
    Ask Gemini to identify which text blocks are dynamic company-specific data.
    Returns {original_text: field_name}.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {}

    try:
        import google.generativeai as genai

        from ai_engine import GEMINI_MODEL

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(GEMINI_MODEL)

        field_schema = {
            "company_name": "company or entity name",
            "address": "company address or registered office",
            "license_number": "trade license, CR number, or registration number",
            "manager_name": "director, manager, or authorized officer name",
            "liquidator_name": "liquidator or appointed professional name",
            "report_date": "date of this report",
            "liquidation_start_date": "date liquidation commenced",
            "period_end_date": "period end or financial year end date",
        }

        blocks_str = "\n".join(f"- {b}" for b in text_blocks[:80])

        prompt = f"""You are analyzing text blocks from an accounting report document.
Identify which blocks contain company-specific data that changes per client.

Field types:
{json.dumps(field_schema, indent=2)}

Text blocks:
{blocks_str}

Return a JSON object mapping exact text → field_name.
Only include blocks that clearly match a field type.
Exclude financial amounts, table column headers, and standard boilerplate.
Output ONLY valid JSON."""

        response = model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0,
            },
        )
        return json.loads(response.text.strip())
    except Exception as e:
        logger.error(f"AI field identification failed: {e}")
        return {}


# ── Template creation ─────────────────────────────────────────────────────────


def _pdf_to_docx(pdf_path: Path, docx_path: Path) -> bool:
    """
    pdf2docx conversion is unreliable for structured accounting PDFs (tables break).
    Always falls back to the text-extraction path.
    """
    return False


def _pdf_text_to_docx(pdf_path: Path, docx_path: Path):
    """Last-resort fallback: extract text from PDF with pdfplumber and create DOCX."""
    try:
        from docx import Document

        doc = Document()
        # Try pdfplumber first (preserves table structure better)
        try:
            import pdfplumber

            with pdfplumber.open(str(pdf_path)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    for line in text.split("\n"):
                        if line.strip():
                            doc.add_paragraph(line.strip())
        except ImportError:
            import pypdf

            with open(pdf_path, "rb") as f:
                reader = pypdf.PdfReader(f)
                for page in reader.pages:
                    text = page.extract_text() or ""
                    for line in text.split("\n"):
                        if line.strip():
                            doc.add_paragraph(line.strip())
        doc.save(str(docx_path))
    except Exception as e:
        logger.error(f"Text fallback failed: {e}")


def _find_financial_tables(doc) -> list[dict]:
    """Find tables in a DOCX that contain financial data."""
    result = []
    for i, table in enumerate(doc.tables):
        if len(table.columns) < 2:
            continue
        all_text = " ".join(
            cell.text for row in table.rows for cell in row.cells
        ).lower()

        if not re.search(r"\d{3,}", all_text):
            continue

        if any(kw in all_text for kw in ["asset", "liabilit", "equity", "capital"]):
            ttype = "financial_position"
        elif any(kw in all_text for kw in ["expense", "revenue", "note"]):
            ttype = "notes"
        else:
            ttype = "financial"

        result.append(
            {
                "table_index": i,
                "table_type": ttype,
                "num_rows": len(table.rows),
                "num_cols": len(table.columns),
            }
        )
    return result


def create_template(
    sample_path: str,
    report_type: str,
    template_id: str,
    known_values: dict | None = None,
) -> dict | None:
    """
    Parse a sample document and create a reusable annotated template.

    known_values: dict with keys like Company_Name, Address, etc.
                  These are the values IN the sample (not the new client's values).
                  They're used to directly find+replace without needing AI.

    Returns template metadata dict or None on failure.
    """
    _ensure_templates_dir()
    sample_path = Path(sample_path)
    template_dir = TEMPLATES_DIR / template_id
    template_dir.mkdir(exist_ok=True)

    # Step 1: Get a DOCX
    docx_path = template_dir / f"{report_type}_source.docx"
    ext = sample_path.suffix.lower()

    if ext in (".docx", ".doc"):
        shutil.copy(sample_path, docx_path)
    elif ext == ".pdf":
        if not _pdf_to_docx(sample_path, docx_path):
            _pdf_text_to_docx(sample_path, docx_path)
    else:
        logger.error(f"Unsupported sample file type: {ext}")
        return None

    if not docx_path.exists():
        return None

    # Step 2: Work on a copy
    template_docx = template_dir / f"{report_type}_template.docx"
    shutil.copy(docx_path, template_docx)

    try:
        from docx import Document

        doc = Document(str(template_docx))
    except Exception as e:
        logger.error(f"Cannot open DOCX: {e}")
        return None

    applied = {}

    # Step 3a: Direct replacement using known values from config
    if known_values:
        field_map = {
            "company_name": known_values.get("Company_Name")
            or known_values.get("company_name"),
            "address": known_values.get("Address") or known_values.get("address"),
            "license_number": known_values.get("License_Number")
            or known_values.get("license_number"),
            "manager_name": known_values.get("Manager_Name")
            or known_values.get("manager_name"),
            "liquidator_name": known_values.get("Liquidator_Name")
            or known_values.get("liquidator_name"),
            "report_date": known_values.get("Report_Date")
            or known_values.get("report_date"),
            "liquidation_start_date": known_values.get("Liquidation_Start_Date"),
            "period_end_date": known_values.get("Period_End_Date"),
        }
        for field, value in field_map.items():
            if value and str(value).strip():
                v = str(value).strip()
                _replace_in_doc(doc, v, f"{{{{{field}}}}}")
                applied[v] = field

    # Step 3b: AI identification of remaining dynamic fields
    text_blocks = _extract_text_blocks(doc)
    ai_fields = _ai_identify_fields(text_blocks)
    for text, field in ai_fields.items():
        if text and text not in applied:
            _replace_in_doc(doc, text, f"{{{{{field}}}}}")
            applied[text] = field

    # Step 4: Identify financial tables
    financial_tables = _find_financial_tables(doc)

    doc.save(str(template_docx))

    metadata = {
        "template_id": template_id,
        "report_type": report_type,
        "original_filename": sample_path.name,
        "applied_replacements": applied,
        "financial_tables": financial_tables,
        "created_at": datetime.now().isoformat(),
    }
    with open(template_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    logger.info(f"Template '{template_id}' created with {len(applied)} dynamic fields")
    return metadata


# ── Report generation ─────────────────────────────────────────────────────────


def _build_value_map(config: dict) -> dict[str, str]:
    entity = config.get("Entity Details", {})
    dates = config.get("Dates", {})
    sigs = config.get("Signatories", {})
    report_date = dates.get("Report Date", "")
    
    from datetime import datetime
    current_year = datetime.now().year
    cy_year = str(current_year)
    py_year = str(current_year - 1)
    
    try:
        # Try to parse from various common formats
        dt = None
        for fmt in ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]:
            try:
                dt = datetime.strptime(report_date, fmt)
                break
            except ValueError:
                continue
        if dt:
            cy_year = str(dt.year)
            py_year = str(dt.year - 1)
        elif len(report_date) >= 4 and report_date[:4].isdigit():
            cy_year = report_date[:4]
            py_year = str(int(cy_year) - 1)
    except (ValueError, IndexError):
        pass

    return {
        "company_name": entity.get("Company Name", ""),
        "address": entity.get("Address", ""),
        "license_number": entity.get("License Number", ""),
        "manager_name": entity.get("Manager Name", ""),
        "liquidator_name": sigs.get("Liquidator Name", ""),
        "report_date": report_date,
        "liquidation_start_date": dates.get("Liquidation Start Date", ""),
        "period_end_date": dates.get("Period End Date", ""),
        "current_year_label": cy_year,
        "prior_year_label": py_year,
    }


def _fill_financial_position_table(table, financial_position: dict, totals: dict):
    """
    Rebuild a financial position table with actual line items.
    Identifies data rows (vs header/total rows), removes them, inserts new rows
    while copying the style from the removed template row.
    """
    rows = list(table.rows)
    if len(rows) < 2:
        return

    header_indices = []
    data_indices = []
    total_indices = []

    for i, row in enumerate(rows):
        row_text = " ".join(c.text.strip() for c in row.cells).lower()
        is_total = any(
            kw in row_text
            for kw in [
                "total assets",
                "total liabilit",
                "total equity",
                "net profit",
                "net loss",
                "total liabilities & equity",
            ]
        )
        is_section_header = any(
            kw in row_text for kw in ["assets", "liabilities", "equity"]
        ) and not re.search(r"\d{3,}", row_text)
        is_col_header = any(
            kw in row_text
            for kw in [
                "particulars",
                "description",
                "aed",
                "amount",
                "current year",
                "prior year",
            ]
        ) and not re.search(r"\d{3,}", row_text)

        if is_total:
            total_indices.append(i)
        elif is_col_header or is_section_header:
            header_indices.append(i)
        else:
            data_indices.append(i)

    if not data_indices:
        return

    # Capture style BEFORE deletion
    style_row = rows[data_indices[0]]

    # Determine insertion point (after last header)
    last_header_idx = max(header_indices) if header_indices else 0
    anchor_row = rows[last_header_idx]

    # Collect new data
    assets = financial_position.get("Assets", {})
    liab_equity = financial_position.get("Liabilities & Equity", {})

    new_rows: list[list[str]] = []
    for name, amounts in assets.items():
        new_rows.append(
            [name, _fmt(amounts.get("current", 0)), _fmt(amounts.get("prior", 0))]
        )
    for name, amounts in liab_equity.items():
        new_rows.append(
            [name, _fmt(amounts.get("current", 0)), _fmt(amounts.get("prior", 0))]
        )

    # Remove old data rows
    tbl = table._tbl
    for i in sorted(data_indices, reverse=True):
        if i < len(rows):
            tbl.remove(rows[i]._tr)

    # Find insertion anchor: last remaining header row
    current_rows = list(table.rows)
    last_header_idx = max(header_indices) if header_indices else 0
    anchor_row = current_rows[min(last_header_idx, len(current_rows) - 1)]

    # Insert new rows in reverse (each inserts right after anchor, reversing gives correct order)
    num_cols = len(table.columns)
    for row_data in reversed(new_rows):
        padded = (row_data + [""] * num_cols)[:num_cols]
        _insert_data_row(table, style_row, padded, anchor=anchor_row)


def _fill_notes_table(table, notes: dict):
    if not notes:
        return
    # Use the first expense category found, not a hardcoded name
    expenses = next(iter(notes.values()), {})
    if not expenses:
        return

    rows = list(table.rows)
    if len(rows) < 2:
        return

    # Capture style before deletion
    style_row = rows[1]
    tbl = table._tbl

    # Remove all rows except header
    for row in rows[1:]:
        tbl.remove(row._tr)

    # After deletion, anchor is the remaining header (row 0)
    current_rows = list(table.rows)
    anchor_row = current_rows[0]
    num_cols = len(table.columns)

    for name, amount in reversed(list(expenses.items())):
        padded = ([name, _fmt(amount)] + [""] * num_cols)[:num_cols]
        _insert_data_row(table, style_row, padded, anchor=anchor_row)


def _docx_to_pdf(docx_path: Path, pdf_path: Path) -> bool:
    """Convert DOCX to PDF via LibreOffice headless."""
    try:
        subprocess.run(
            [
                "libreoffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(pdf_path.parent),
                str(docx_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        generated = docx_path.with_suffix(".pdf")
        if generated.exists():
            if generated != pdf_path:
                shutil.move(str(generated), str(pdf_path))
            return True
        return False
    except FileNotFoundError:
        logger.warning("LibreOffice not found — PDF conversion unavailable")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(f"LibreOffice failed: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"DOCX→PDF failed: {e}")
        return False


def fill_and_generate(
    template_id: str,
    report_type: str,
    config: dict,
    financial_data: dict,
    output_pdf_path: str,
) -> bool:
    """
    Generate a filled PDF from a stored template.
    Returns True on success.
    """
    _ensure_templates_dir()
    template_dir = TEMPLATES_DIR / template_id
    template_docx = template_dir / f"{report_type}_template.docx"
    metadata_path = template_dir / "metadata.json"

    if not template_docx.exists():
        logger.error(f"Template not found: {template_docx}")
        return False

    metadata = {}
    if metadata_path.exists():
        with open(metadata_path) as f:
            metadata = json.load(f)

    # Copy template to working file
    working_docx = Path(output_pdf_path).with_suffix(".docx")
    shutil.copy(template_docx, working_docx)

    # Step 1: Use docxtpl for Jinja2-style {{field}} replacement
    # docxtpl handles split runs natively — no manual run merging needed
    value_map = _build_value_map(config)
    try:
        from docxtpl import DocxTemplate

        tpl = DocxTemplate(str(working_docx))
        # docxtpl context must not include keys that collide with Jinja2 builtins
        safe_context = {k: str(v) for k, v in value_map.items()}
        tpl.render(safe_context)
        tpl.save(str(working_docx))
    except Exception as e:
        # Fallback to manual replacement if docxtpl fails
        logger.warning(f"docxtpl render failed ({e}), using manual replacement")
        from docx import Document as _Doc

        doc_fb = _Doc(str(working_docx))
        for field, value in value_map.items():
            _replace_in_doc(doc_fb, f"{{{{{field}}}}}", str(value))
        doc_fb.save(str(working_docx))

    # Step 2: Rebuild financial tables with actual data (preserves table styling)
    financial_position = financial_data.get("Financial Position", {})
    totals = financial_data.get("Totals", {})
    notes = financial_data.get("Notes", {})

    from docx import Document

    doc = Document(str(working_docx))

    for t_info in metadata.get("financial_tables", []):
        t_idx = t_info["table_index"]
        if t_idx < len(doc.tables):
            ttype = t_info.get("table_type", "")
            if ttype == "financial_position":
                _fill_financial_position_table(
                    doc.tables[t_idx], financial_position, totals
                )
            elif ttype == "notes":
                _fill_notes_table(doc.tables[t_idx], notes)

    doc.save(str(working_docx))
    return _docx_to_pdf(working_docx, Path(output_pdf_path))


# ── Template library ──────────────────────────────────────────────────────────


def get_templates() -> list[dict]:
    _ensure_templates_dir()
    templates = []
    for d in TEMPLATES_DIR.iterdir():
        if not d.is_dir():
            continue
        meta_path = d / "metadata.json"
        if meta_path.exists():
            try:
                with open(meta_path) as f:
                    templates.append(json.load(f))
            except Exception as e:
                logger.error(f"Failed to load template metadata from {meta_path}: {e}")
                continue
    return templates


def delete_template(template_id: str) -> bool:
    template_dir = TEMPLATES_DIR / template_id
    if template_dir.exists():
        shutil.rmtree(template_dir)
        return True
    return False
