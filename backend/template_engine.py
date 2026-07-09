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

import copy
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import zipfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from docx.table import _Row as TableRow

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path("templates")

try:
    from ai_engine import _ai_identify_fields
except ImportError:

    def _ai_identify_fields(text_blocks: list[str]) -> dict[str, str]:
        return {}


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


# ── OOXML fidelity helpers ────────────────────────────────────────────────────


def _is_total_row(text: str) -> bool:
    return any(kw in text.lower() for kw in ["total", "net profit", "net loss"])


def _freeze_tbl_look(table) -> None:
    """Set all tblLook flags to 0 to prevent conditional format overrides on new rows."""
    from docx.oxml.ns import qn
    from lxml import etree

    tblPr = table._tbl.find(qn("w:tblPr"))
    if tblPr is None:
        return
    tblLook = tblPr.find(qn("w:tblLook"))
    if tblLook is None:
        tblLook = etree.SubElement(tblPr, qn("w:tblLook"))
    for attr in [
        "w:firstRow",
        "w:lastRow",
        "w:firstColumn",
        "w:lastColumn",
        "w:noHBand",
        "w:noVBand",
    ]:
        tblLook.set(qn(attr), "0")


def _enforce_fixed_layout(table) -> None:
    """Set tblLayout to fixed to prevent column width drift when rows are added/removed."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tblPr = table._tbl.find(qn("w:tblPr"))
    if tblPr is None:
        return
    tblLayout = tblPr.find(qn("w:tblLayout"))
    if tblLayout is None:
        tblLayout = OxmlElement("w:tblLayout")
        tblPr.append(tblLayout)
    tblLayout.set(qn("w:type"), "fixed")


def _xml_hash(element) -> str | None:
    if element is None:
        return None
    from lxml import etree

    return hashlib.md5(etree.tostring(element, canonical=True)).hexdigest()


def _extract_table_fingerprint(table) -> dict:
    from docx.oxml.ns import qn

    fp: dict = {"rows": []}
    for row in table.rows:
        row_fp: dict = {"trPr_hash": _xml_hash(row._tr.find(qn("w:trPr"))), "cells": []}
        for cell in row.cells:
            rPr_el = None
            if cell.paragraphs and cell.paragraphs[0].runs:
                rPr_el = cell.paragraphs[0].runs[0]._r.find(qn("w:rPr"))
            row_fp["cells"].append(
                {
                    "tcPr_hash": _xml_hash(cell._tc.find(qn("w:tcPr"))),
                    "rPr_hash": _xml_hash(rPr_el),
                }
            )
        fp["rows"].append(row_fp)
    return fp


def _extract_layout_fingerprint(docx_path: str) -> dict:
    from docx import Document

    doc = Document(docx_path)
    return {str(i): _extract_table_fingerprint(t) for i, t in enumerate(doc.tables)}


def _compare_fingerprints(template_fp: dict, filled_fp: dict) -> list[str]:
    issues = []
    for table_idx, tbl_fp in template_fp.items():
        if table_idx not in filled_fp:
            issues.append(f"table {table_idx}: missing in filled doc")
            continue
        for r_idx, (t_row, f_row) in enumerate(
            zip(tbl_fp.get("rows", []), filled_fp[table_idx].get("rows", []))
        ):
            if t_row.get("trPr_hash") != f_row.get("trPr_hash"):
                issues.append(f"table {table_idx} row {r_idx}: trPr changed")
            for c_idx, (t_cell, f_cell) in enumerate(
                zip(t_row.get("cells", []), f_row.get("cells", []))
            ):
                if t_cell.get("tcPr_hash") != f_cell.get("tcPr_hash"):
                    issues.append(f"table {table_idx} row {r_idx} cell {c_idx}: tcPr changed")
    return issues


def _clone_row_preserve_format(table, source_row_idx: int):
    """Deep-clone a row, clear all text, and append to the table."""
    from docx.oxml.ns import qn
    from lxml import etree

    source_tr = table.rows[source_row_idx]._tr
    new_tr = copy.deepcopy(source_tr)
    for tc in new_tr.findall(qn("w:tc")):
        for para in tc.findall(qn("w:p")):
            for run in para.findall(qn("w:r")):
                para.remove(run)
            r = etree.SubElement(para, qn("w:r"))
            t = etree.SubElement(r, qn("w:t"))
            t.text = ""
    table._tbl.append(new_tr)
    return table.rows[-1]


def _set_cell_text_preserve_rpr(cell, text: str) -> None:
    """Set cell text while preserving existing run formatting (rPr)."""
    from docx.oxml.ns import qn

    para = cell.paragraphs[0]
    existing_rPr = None
    if para.runs:
        existing_rPr = copy.deepcopy(para.runs[0]._r.find(qn("w:rPr")))
        para.clear()
    run = para.add_run(text)
    if existing_rPr is not None:
        existing = run._r.find(qn("w:rPr"))
        if existing is not None:
            run._r.remove(existing)
        run._r.insert(0, existing_rPr)


def _replace_floating_images(docx_path: str, image_replacements: dict[str, bytes]) -> None:
    """Replace floating image binary data without touching anchor XML."""
    docx_path = Path(docx_path)
    tmp_dir = docx_path.parent / (docx_path.stem + "_unzipped")
    with zipfile.ZipFile(docx_path, "r") as z:
        z.extractall(tmp_dir)
    media_dir = tmp_dir / "word" / "media"
    for img_name, img_bytes in image_replacements.items():
        target = media_dir / img_name
        if target.exists():
            target.write_bytes(img_bytes)
    output_path = docx_path.parent / (docx_path.stem + "_fixed.docx")
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for file in tmp_dir.rglob("*"):
            if file.is_file():
                zout.write(file, file.relative_to(tmp_dir))
    shutil.rmtree(tmp_dir)
    output_path.replace(docx_path)


def _format_accounting_number(value: float, pattern: dict) -> str:
    try:
        from babel.numbers import format_decimal

        currency = pattern.get("currency", "")
        decimals = pattern.get("decimals", 2)
        negative_parens = pattern.get("negative", "parens") == "parens"
        if currency == "AED":
            if value < 0 and negative_parens:
                return f"AED ({abs(value):,.{decimals}f})"
            return f"AED {value:,.{decimals}f}"
        return format_decimal(
            value,
            format=pattern.get("babel_format", "#,##0.00"),
            locale=pattern.get("locale", "en_AE"),
        )
    except Exception:
        return _fmt(value)


# ── GVR helpers — render & compare ───────────────────────────────────────────


def _render_docx_to_pngs(docx_path: str, dpi: int = 150) -> list[bytes]:
    """Convert a DOCX to a list of per-page PNG byte strings via LibreOffice + PyMuPDF.

    Fails open: returns [] on any error so the caller can skip vision verification
    rather than blocking document generation.
    """
    import tempfile

    try:
        import fitz  # PyMuPDF

        docx_path_obj = Path(docx_path)
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_dir_path = Path(tmp_dir)
            # LibreOffice writes <stem>.pdf into the outdir
            subprocess.run(
                [
                    "libreoffice",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(tmp_dir_path),
                    str(docx_path_obj),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
            pdf_file = tmp_dir_path / (docx_path_obj.stem + ".pdf")
            if not pdf_file.exists():
                logger.warning("_render_docx_to_pngs: PDF not found at %s", pdf_file)
                return []

            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pages: list[bytes] = []
            with fitz.open(str(pdf_file)) as pdf_doc:
                for page in pdf_doc:
                    pix = page.get_pixmap(matrix=mat)
                    pages.append(pix.tobytes("png"))
            return pages
    except FileNotFoundError:
        logger.warning("_render_docx_to_pngs: LibreOffice not found")
        return []
    except Exception as e:
        logger.warning("_render_docx_to_pngs failed: %s", e)
        return []


def _ssim_score(png_a: bytes, png_b: bytes) -> float:
    """Return the structural similarity score between two PNG byte strings.

    Resizes B to match A if dimensions differ. Returns 0.0 on any error.
    """
    try:
        import io

        import numpy as np
        from PIL import Image
        from skimage.metrics import structural_similarity

        img_a = Image.open(io.BytesIO(png_a)).convert("RGB")
        img_b = Image.open(io.BytesIO(png_b)).convert("RGB")

        if img_a.size != img_b.size:
            img_b = img_b.resize(img_a.size, Image.LANCZOS)

        arr_a = np.array(img_a)
        arr_b = np.array(img_b)

        score, _ = structural_similarity(arr_a, arr_b, channel_axis=-1, data_range=255, full=True)
        return float(score)
    except Exception as e:
        logger.warning("_ssim_score failed: %s", e)
        return 0.0


def _claude_vision_diff(png_a: bytes, png_b: bytes, issue_hint: str = "") -> list[str]:
    """Ask Claude to identify visual differences between two page renders.

    Returns a list of difference strings, or a sentinel error string on failure.
    The caller is responsible for filtering out 'IDENTICAL' entries.
    """
    try:
        import base64

        import ai_engine

        if ai_engine.client is None:
            return ["tier3_skipped: no Claude client"]

        b64_a = base64.b64encode(png_a).decode()
        b64_b = base64.b64encode(png_b).decode()

        tools = [
            {
                "name": "report_differences",
                "description": "Report visual differences between two document renders.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "differences": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "List of visual differences. Use the single string "
                                "'IDENTICAL' as the only element if there are no differences."
                            ),
                        }
                    },
                    "required": ["differences"],
                },
            }
        ]

        response = ai_engine.client.messages.create(
            model=ai_engine.SONNET,
            max_tokens=1024,
            system=(
                "You compare two renders of the same document page. "
                "Identify visual differences that would bother a reader of a professional "
                "accounting report: misaligned text, missing cells, wrong colors, missing logos, "
                "overflowing columns. Report only differences, not similarities. "
                "If no differences, output the single phrase 'IDENTICAL'."
            ),
            tools=tools,
            tool_choice={"type": "tool", "name": "report_differences"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Render A is the template, Render B is the filled output."
                                + (f" Hint: {issue_hint}" if issue_hint else "")
                            ),
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64_a,
                            },
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64_b,
                            },
                        },
                    ],
                }
            ],
        )

        for block in response.content:
            if block.type == "tool_use":
                return block.input.get("differences", [])
        return []
    except Exception as e:
        logger.warning("_claude_vision_diff failed: %s", e)
        return [f"tier3_error: {e}"]


# ── GVR (Generate-Verify-Repair) ─────────────────────────────────────────────


def _restore_cell_tcpr_from_template(doc, template_docx_path: str, issue: str) -> None:
    from docx import Document as _Doc
    from docx.oxml.ns import qn

    m = re.search(r"table (\d+) row (\d+) cell (\d+): tcPr changed", issue)
    if not m:
        return
    t_idx, r_idx, c_idx = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        tmpl_doc = _Doc(template_docx_path)
        if t_idx >= len(tmpl_doc.tables) or t_idx >= len(doc.tables):
            return
        tmpl_cells = tmpl_doc.tables[t_idx].rows[r_idx].cells
        fill_tc = doc.tables[t_idx].rows[r_idx].cells[c_idx]._tc
        tmpl_tcPr = tmpl_cells[c_idx]._tc.find(qn("w:tcPr"))
        existing = fill_tc.find(qn("w:tcPr"))
        if existing is not None:
            fill_tc.remove(existing)
        if tmpl_tcPr is not None:
            fill_tc.insert(0, copy.deepcopy(tmpl_tcPr))
    except Exception as e:
        logger.warning("_restore_cell_tcpr_from_template failed: %s", e)


class DocumentFormatVerifier:
    SSIM_THRESHOLD = 0.92
    MAX_ITERATIONS = 3

    def verify(self, template_docx: str, filled_docx: str, template_fingerprint: dict) -> dict:
        logger.info("GVR active at tier 1 (vision tiers gated by ENABLE_VISION_VERIFY env)")

        # ── Tier 1: XML fingerprint diff ──────────────────────────────────────
        if template_fingerprint:
            filled_fp = _extract_layout_fingerprint(filled_docx)
            issues = _compare_fingerprints(template_fingerprint, filled_fp)
            if issues:
                return {"pass": False, "tier": 1, "issues": issues}

        if not os.environ.get("ENABLE_VISION_VERIFY"):
            return {"pass": True, "tier": 1, "issues": []}

        # ── Tier 2: SSIM visual comparison ───────────────────────────────────
        template_pages = _render_docx_to_pngs(template_docx)
        filled_pages = _render_docx_to_pngs(filled_docx)

        if not template_pages or not filled_pages:
            logger.warning(
                "GVR Tier 2: render returned empty list — skipping vision verify (fail-open)"
            )
            return {"pass": True, "tier": 1, "issues": []}

        ssim_issues: list[tuple[int, float]] = []  # (page_idx, score)
        for idx, (tpng, fpng) in enumerate(zip(template_pages, filled_pages)):
            score = _ssim_score(tpng, fpng)
            if score < self.SSIM_THRESHOLD:
                ssim_issues.append((idx, score))
                if len(ssim_issues) >= 2:  # cap at 2 pages to bound Claude cost
                    break

        if not ssim_issues:
            return {"pass": True, "tier": 2, "issues": []}

        # ── Tier 3: Claude vision diff for SSIM-failing pages ─────────────────
        tier3_issues: list[str] = []
        for idx, score in ssim_issues:
            hint = f"page {idx}, ssim={score:.3f}"
            diffs = _claude_vision_diff(template_pages[idx], filled_pages[idx], issue_hint=hint)
            tier3_issues.extend(diffs)

        # Remove "IDENTICAL" entries — pages that looked different by SSIM
        # but the reviewer model agrees are fine
        tier3_issues = [d for d in tier3_issues if d != "IDENTICAL"]

        if tier3_issues:
            return {"pass": False, "tier": 3, "issues": tier3_issues}
        return {"pass": True, "tier": 3, "issues": []}

    def repair(
        self,
        filled_docx: str,
        template_docx: str,
        template_fp: dict,
        issues: list[str],
    ) -> str:
        from docx import Document

        doc = Document(filled_docx)
        repaired = False
        for issue in issues:
            if "tcPr changed" in issue:
                _restore_cell_tcpr_from_template(doc, template_docx, issue)
                repaired = True
            else:
                # Tier 2/3 issues (SSIM failures, Claude-reported differences) need human review.
                logger.warning("No automated repair handler for: %s", issue)
        if not repaired:
            return filled_docx
        repaired_path = filled_docx.replace(".docx", "_r.docx")
        doc.save(repaired_path)
        return repaired_path


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
        all_text = " ".join(cell.text for row in table.rows for cell in row.cells).lower()

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
            "company_name": known_values.get("Company_Name") or known_values.get("company_name"),
            "address": known_values.get("Address") or known_values.get("address"),
            "license_number": known_values.get("License_Number")
            or known_values.get("license_number"),
            "manager_name": known_values.get("Manager_Name") or known_values.get("manager_name"),
            "liquidator_name": known_values.get("Liquidator_Name")
            or known_values.get("liquidator_name"),
            "report_date": known_values.get("Report_Date") or known_values.get("report_date"),
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

    # Step 5: OOXML fidelity — freeze table formatting and capture fingerprints
    table_fingerprints: dict = {}
    number_format_patterns: dict = {}
    for t_info in financial_tables:
        t_idx = t_info["table_index"]
        if t_idx >= len(doc.tables):
            continue
        table = doc.tables[t_idx]
        _freeze_tbl_look(table)
        _enforce_fixed_layout(table)
        expected_order = [
            row.cells[0].text.strip()
            for row in table.rows
            if row.cells and not _is_total_row(row.cells[0].text)
        ]
        t_info["expected_account_order"] = expected_order
        table_fingerprints[str(t_idx)] = _extract_table_fingerprint(table)
        pattern: dict = {"decimals": 2, "negative": "parens"}
        for row in table.rows:
            for cell in row.cells:
                if "aed" in cell.text.lower():
                    pattern["currency"] = "AED"
                    break
        number_format_patterns[str(t_idx)] = pattern

    doc.save(str(template_docx))

    # Step 6: Catalog floating images by filename
    image_catalog: dict = {}
    try:
        with zipfile.ZipFile(str(template_docx), "r") as z:
            for name in z.namelist():
                if name.startswith("word/media/"):
                    img_name = name.split("/")[-1]
                    if img_name:
                        image_catalog[img_name] = "unknown"
    except Exception as e:
        logger.warning("Image catalog extraction failed: %s", e)

    metadata = {
        "template_id": template_id,
        "report_type": report_type,
        "original_filename": sample_path.name,
        "applied_replacements": applied,
        "financial_tables": financial_tables,
        "table_fingerprints": table_fingerprints,
        "image_catalog": image_catalog,
        "number_format_patterns": number_format_patterns,
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

    current_year = datetime.now().year
    cy_year = str(current_year)
    py_year = str(current_year - 1)

    try:
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


def _fill_financial_position_table(
    table,
    financial_position: dict,
    totals: dict,
    expected_order: list | None = None,
):
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

    # Collect and order new data
    assets = financial_position.get("Assets", {})
    liab_equity = financial_position.get("Liabilities & Equity", {})

    all_accounts: dict = {}
    all_accounts.update(assets)
    all_accounts.update(liab_equity)

    if expected_order:
        known_order = {name: i for i, name in enumerate(expected_order)}
        known = sorted([a for a in all_accounts if a in known_order], key=lambda x: known_order[x])
        new_accts = [a for a in all_accounts if a not in known_order]
        ordered_names = known + new_accts
    else:
        ordered_names = list(assets.keys()) + list(liab_equity.keys())

    new_rows: list[list[str]] = []
    for name in ordered_names:
        amounts = all_accounts.get(name, {})
        if isinstance(amounts, dict):
            new_rows.append([name, _fmt(amounts.get("current", 0)), _fmt(amounts.get("prior", 0))])
        else:
            new_rows.append([name, _fmt(amounts), ""])

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
    narrative=None,
    image_replacements: dict[str, bytes] | None = None,
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

    # Step 1: Build value map and inject narrative if provided
    value_map = _build_value_map(config)
    if narrative and "liquidator_narrative" in metadata.get("applied_replacements", {}).values():
        value_map["liquidator_narrative"] = narrative.liquidator_narrative
        value_map["key_observations"] = "\n".join(f"• {obs}" for obs in narrative.key_observations)
        value_map["risk_level"] = narrative.risk_level

    # Step 2: Use docxtpl for Jinja2-style {{field}} replacement
    try:
        from docxtpl import DocxTemplate

        tpl = DocxTemplate(str(working_docx))
        safe_context = {k: str(v) for k, v in value_map.items()}
        tpl.render(safe_context)
        tpl.save(str(working_docx))
    except Exception as e:
        logger.warning(f"docxtpl render failed ({e}), using manual replacement")
        from docx import Document as _Doc

        doc_fb = _Doc(str(working_docx))
        for field, value in value_map.items():
            _replace_in_doc(doc_fb, f"{{{{{field}}}}}", str(value))
        doc_fb.save(str(working_docx))

    # Step 3: Rebuild financial tables with actual data (preserves table styling)
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
                    doc.tables[t_idx],
                    financial_position,
                    totals,
                    expected_order=t_info.get("expected_account_order"),
                )
            elif ttype == "notes":
                _fill_notes_table(doc.tables[t_idx], notes)

    doc.save(str(working_docx))

    # Step 3b: Replace floating image binaries (logos, signatures) if provided.
    # Only swaps files matched by name in metadata["image_catalog"]; anchor XML untouched.
    if image_replacements:
        catalog = metadata.get("image_catalog", {})
        valid = {name: data for name, data in image_replacements.items() if name in catalog}
        if valid:
            try:
                _replace_floating_images(str(working_docx), valid)
            except Exception as e:
                logger.warning("Floating image replacement failed: %s", e)

    # Step 4: GVR Tier 1 — XML fingerprint verify-and-repair loop
    template_fingerprint = metadata.get("table_fingerprints", {})
    if template_fingerprint:
        verifier = DocumentFormatVerifier()
        working_str = str(working_docx)
        for iteration in range(verifier.MAX_ITERATIONS):
            result = verifier.verify(str(template_docx), working_str, template_fingerprint)
            if result["pass"]:
                break
            logger.info(
                "Format iteration %d: %d issues at tier %d",
                iteration + 1,
                len(result["issues"]),
                result["tier"],
            )
            repaired = verifier.repair(
                working_str, str(template_docx), template_fingerprint, result["issues"]
            )
            if repaired != working_str:
                working_docx = Path(repaired)
                working_str = repaired
            else:
                break

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
