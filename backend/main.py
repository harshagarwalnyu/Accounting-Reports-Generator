import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pypdf import PdfWriter
from sse_starlette.sse import EventSourceResponse

import ai_engine
import ingestion
import template_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TMP_DIR = Path("temp_data")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: clean up any leftover temp files from previous runs
    if TMP_DIR.exists():
        for f in TMP_DIR.iterdir():
            if f.is_file():
                try:
                    f.unlink()
                except Exception:
                    pass
    else:
        TMP_DIR.mkdir(exist_ok=True)
    yield
    # Shutdown: no-op


app = FastAPI(title="Accounting Reports Generator API", lifespan=lifespan)

ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

jobs: dict[str, dict[str, Any]] = {}


# ── Template endpoints ────────────────────────────────────────────────────────


@app.get("/api/templates")
async def list_templates():
    return template_engine.get_templates()


@app.post("/api/templates")
async def create_template(
    report_type: str = Form(...),
    template_id: str = Form(...),
    sample_file: UploadFile = File(...),
    known_values: str = Form("{}"),
):
    """
    Create a reusable template from a sample document.
    report_type: "audit" or "liquidation"
    template_id: unique identifier (e.g. "standard_liquidation_v1")
    known_values: JSON with Company_Name, Address, etc. from the SAMPLE document
                  (used to find+replace those values with placeholders)
    """
    safe_name = "".join(c for c in sample_file.filename if c.isalnum() or c in "._-")
    save_path = TMP_DIR / f"tmpl_{template_id}_{safe_name}"
    with open(save_path, "wb") as f:
        f.write(await sample_file.read())

    try:
        kv = json.loads(known_values)
    except json.JSONDecodeError:
        raise HTTPException(400, "known_values must be valid JSON")

    meta = template_engine.create_template(
        sample_path=str(save_path),
        report_type=report_type,
        template_id=template_id,
        known_values=kv,
    )
    save_path.unlink(missing_ok=True)

    if not meta:
        raise HTTPException(500, "Template creation failed")
    return meta


@app.delete("/api/templates/{template_id}")
async def delete_template(template_id: str):
    ok = template_engine.delete_template(template_id)
    if not ok:
        raise HTTPException(404, "Template not found")
    return {"deleted": template_id}


# ── Report generation ─────────────────────────────────────────────────────────


async def cleanup_job_files(job_id: str, delay: int = 3600):
    await asyncio.sleep(delay)
    for pattern in [f"tmp_{job_id}_*", f"*_{job_id}.*"]:
        for p in TMP_DIR.glob(pattern):
            try:
                if p.is_file():
                    p.unlink()
            except Exception as e:
                logger.error(f"Cleanup failed for {p}: {e}")

    jobs.pop(job_id, None)

    # Guard: if jobs dict exceeds 100 entries (shouldn't happen), purge oldest
    if len(jobs) > 100:
        oldest_keys = list(jobs.keys())[: len(jobs) - 100]
        for k in oldest_keys:
            jobs.pop(k, None)


def _build_structured_config(config_dict: dict) -> dict:
    return {
        "Entity Details": {
            "Company Name": config_dict.get("Company_Name", "N/A"),
            "Address": config_dict.get("Address", "N/A"),
            "License Number": config_dict.get("License_Number", "N/A"),
            "Manager Name": config_dict.get("Manager_Name", "N/A"),
        },
        "Dates": {
            "Report Date": config_dict.get("Report_Date", "N/A"),
            "Liquidation Start Date": config_dict.get("Liquidation_Start_Date", "N/A"),
            "Period End Date": config_dict.get("Period_End_Date", "N/A"),
        },
        "Signatories": {"Liquidator Name": config_dict.get("Liquidator_Name", "N/A")},
    }


async def process_report(
    job_id: str,
    file_path: Path,
    config_data: dict,
    sample_audit_path: Path | None = None,
    sample_liquidation_path: Path | None = None,
    audit_template_id: str | None = None,
    liquidation_template_id: str | None = None,
):
    try:
        use_ai = bool(os.environ.get("ANTHROPIC_API_KEY"))
        jobs[job_id]["progress"].put_nowait(
            {
                "step": "uploading",
                "progress": 10,
                "message": "Processing financial data...",
            }
        )

        financial_data = await asyncio.to_thread(
            ingestion.load_and_process_data, str(file_path), use_ai=use_ai
        )
        if not financial_data:
            raise ValueError(
                "Failed to parse Excel. Check column names — need account names and at least one amount column."
            )

        jobs[job_id]["data"] = financial_data

        narrative = None
        if ai_engine.client is not None:
            try:
                narrative = await asyncio.to_thread(
                    ai_engine.generate_dynamic_narrative, financial_data
                )
            except Exception as e:
                logger.warning("Narrative generation failed: %s", e)

        pdfs_to_merge = []

        # ── Audit report ──────────────────────────────────────────────────────
        audit_pdf = TMP_DIR / f"audit_report_{job_id}.pdf"

        if audit_template_id:
            jobs[job_id]["progress"].put_nowait(
                {
                    "step": "generating",
                    "progress": 35,
                    "message": "Filling audit template...",
                }
            )
            ok = await asyncio.to_thread(
                template_engine.fill_and_generate,
                audit_template_id,
                "audit",
                config_data,
                financial_data,
                str(audit_pdf),
                narrative=narrative,
            )
            if ok and audit_pdf.exists():
                pdfs_to_merge.append(str(audit_pdf))

        elif sample_audit_path and sample_audit_path.exists():
            jobs[job_id]["progress"].put_nowait(
                {
                    "step": "generating",
                    "progress": 30,
                    "message": "Analyzing audit sample format...",
                }
            )
            temp_tmpl_id = f"_tmp_audit_{job_id}"
            meta = await asyncio.to_thread(
                template_engine.create_template,
                sample_path=str(sample_audit_path),
                report_type="audit",
                template_id=temp_tmpl_id,
                known_values=_extract_known_values(config_data),
            )
            if not meta:
                raise Exception(
                    "Failed to parse audit sample. Please check the file is a valid DOCX or PDF."
                )
            jobs[job_id]["progress"].put_nowait(
                {
                    "step": "generating",
                    "progress": 50,
                    "message": "Generating audit report...",
                }
            )
            ok = await asyncio.to_thread(
                template_engine.fill_and_generate,
                temp_tmpl_id,
                "audit",
                config_data,
                financial_data,
                str(audit_pdf),
                narrative=narrative,
            )
            template_engine.delete_template(temp_tmpl_id)
            if not ok or not audit_pdf.exists():
                raise Exception(
                    "Audit PDF generation failed. Check LibreOffice is installed."
                )
            pdfs_to_merge.append(str(audit_pdf))

        # ── Liquidation report ────────────────────────────────────────────────
        liq_pdf = TMP_DIR / f"liquidation_report_{job_id}.pdf"

        if liquidation_template_id:
            jobs[job_id]["progress"].put_nowait(
                {
                    "step": "generating",
                    "progress": 60,
                    "message": "Filling liquidation template...",
                }
            )
            ok = await asyncio.to_thread(
                template_engine.fill_and_generate,
                liquidation_template_id,
                "liquidation",
                config_data,
                financial_data,
                str(liq_pdf),
                narrative=narrative,
            )
            if ok and liq_pdf.exists():
                pdfs_to_merge.append(str(liq_pdf))

        elif sample_liquidation_path and sample_liquidation_path.exists():
            jobs[job_id]["progress"].put_nowait(
                {
                    "step": "generating",
                    "progress": 55,
                    "message": "Analyzing liquidation sample format...",
                }
            )
            temp_tmpl_id = f"_tmp_liq_{job_id}"
            meta = await asyncio.to_thread(
                template_engine.create_template,
                sample_path=str(sample_liquidation_path),
                report_type="liquidation",
                template_id=temp_tmpl_id,
                known_values=_extract_known_values(config_data),
            )
            if not meta:
                raise Exception(
                    "Failed to parse liquidation sample. Please check the file is a valid DOCX or PDF."
                )
            jobs[job_id]["progress"].put_nowait(
                {
                    "step": "generating",
                    "progress": 75,
                    "message": "Generating liquidation report...",
                }
            )
            ok = await asyncio.to_thread(
                template_engine.fill_and_generate,
                temp_tmpl_id,
                "liquidation",
                config_data,
                financial_data,
                str(liq_pdf),
                narrative=narrative,
            )
            template_engine.delete_template(temp_tmpl_id)
            if not ok or not liq_pdf.exists():
                raise Exception(
                    "Liquidation PDF generation failed. Check LibreOffice is installed."
                )
            pdfs_to_merge.append(str(liq_pdf))

        if not pdfs_to_merge:
            raise Exception(
                "No sample or template provided. Please upload at least one sample report or select a saved template."
            )

        jobs[job_id]["progress"].put_nowait(
            {"step": "compiling", "progress": 90, "message": "Finalizing output PDF..."}
        )

        if len(pdfs_to_merge) > 1:
            merger = PdfWriter()
            for pdf in pdfs_to_merge:
                merger.append(pdf)
            final_pdf = TMP_DIR / f"Final_Report_{job_id}.pdf"
            await asyncio.to_thread(merger.write, str(final_pdf))
            merger.close()
            jobs[job_id]["pdf"] = str(final_pdf)
        else:
            jobs[job_id]["pdf"] = pdfs_to_merge[0]

        jobs[job_id]["progress"].put_nowait(
            {"step": "done", "progress": 100, "pdf_url": f"/api/reports/{job_id}/pdf"}
        )

    except Exception as e:
        logger.exception(f"Error processing job {job_id}")
        jobs[job_id]["progress"].put_nowait(
            {"step": "error", "progress": 0, "message": str(e)}
        )
    finally:
        asyncio.create_task(cleanup_job_files(job_id))


def _extract_known_values(config_data: dict) -> dict:
    """Flatten structured config to flat known_values dict for template annotation."""
    entity = config_data.get("Entity Details", {})
    dates = config_data.get("Dates", {})
    sigs = config_data.get("Signatories", {})
    return {
        "Company_Name": entity.get("Company Name", ""),
        "Address": entity.get("Address", ""),
        "License_Number": entity.get("License Number", ""),
        "Manager_Name": entity.get("Manager Name", ""),
        "Liquidator_Name": sigs.get("Liquidator Name", ""),
        "Report_Date": dates.get("Report Date", ""),
        "Liquidation_Start_Date": dates.get("Liquidation Start Date", ""),
        "Period_End_Date": dates.get("Period End Date", ""),
    }


@app.post("/api/reports/generate")
async def generate_report(
    file: UploadFile = File(...),
    sample_audit: UploadFile | None = File(None),
    sample_liquidation: UploadFile | None = File(None),
    config: str = Form(...),
    audit_template_id: str | None = Form(None),
    liquidation_template_id: str | None = Form(None),
):
    ALLOWED_EXCEL_EXTENSIONS = {".xlsx", ".xls"}
    ALLOWED_SAMPLE_EXTENSIONS = {".pdf", ".docx", ".doc"}

    if not file.filename:
        raise HTTPException(400, "Trial balance file must have a filename")

    excel_ext = Path(file.filename).suffix.lower()
    if excel_ext not in ALLOWED_EXCEL_EXTENSIONS:
        raise HTTPException(
            400, f"Excel file required (.xlsx or .xls), got {excel_ext}"
        )

    if sample_audit and sample_audit.filename:
        audit_ext = Path(sample_audit.filename).suffix.lower()
        if audit_ext not in ALLOWED_SAMPLE_EXTENSIONS:
            raise HTTPException(
                400, f"Audit sample must be PDF or DOCX, got {audit_ext}"
            )

    if sample_liquidation and sample_liquidation.filename:
        liq_ext = Path(sample_liquidation.filename).suffix.lower()
        if liq_ext not in ALLOWED_SAMPLE_EXTENSIONS:
            raise HTTPException(
                400, f"Liquidation sample must be PDF or DOCX, got {liq_ext}"
            )

    try:
        config_dict = json.loads(config)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid config JSON")

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"progress": asyncio.Queue(), "data": None, "pdf": None}

    safe_filename = "".join(c for c in file.filename if c.isalnum() or c in "._-")
    file_path = TMP_DIR / f"tmp_{job_id}_{safe_filename}"
    contents = await file.read()
    await asyncio.to_thread(file_path.write_bytes, contents)

    sample_audit_path = None
    if sample_audit and sample_audit.filename:
        safe_name = "".join(
            c for c in sample_audit.filename if c.isalnum() or c in "._-"
        )
        sample_audit_path = TMP_DIR / f"tmp_{job_id}_audit_{safe_name}"
        audit_contents = await sample_audit.read()
        await asyncio.to_thread(sample_audit_path.write_bytes, audit_contents)

    sample_liquidation_path = None
    if sample_liquidation and sample_liquidation.filename:
        safe_name = "".join(
            c for c in sample_liquidation.filename if c.isalnum() or c in "._-"
        )
        sample_liquidation_path = TMP_DIR / f"tmp_{job_id}_liq_{safe_name}"
        liq_contents = await sample_liquidation.read()
        await asyncio.to_thread(sample_liquidation_path.write_bytes, liq_contents)

    structured_config = _build_structured_config(config_dict)

    asyncio.create_task(
        process_report(
            job_id,
            file_path,
            structured_config,
            sample_audit_path,
            sample_liquidation_path,
            audit_template_id,
            liquidation_template_id,
        )
    )

    return {"job_id": job_id}


@app.get("/api/reports/{job_id}/stream")
async def stream_progress(job_id: str):
    async def event_generator():
        if job_id not in jobs:
            yield {"event": "error", "data": json.dumps({"message": "Job not found"})}
            return
        queue = jobs[job_id]["progress"]
        try:
            while True:
                msg = await asyncio.wait_for(queue.get(), timeout=60)
                yield {"data": json.dumps(msg)}
                if msg["step"] in ("done", "error"):
                    break
        except TimeoutError:
            yield {
                "event": "error",
                "data": json.dumps({"message": "Stream timed out"}),
            }

    return EventSourceResponse(event_generator())


@app.get("/api/reports/{job_id}/pdf")
async def get_pdf(job_id: str):
    if job_id not in jobs or not jobs[job_id].get("pdf"):
        raise HTTPException(404, "PDF not ready")
    pdf_path = Path(jobs[job_id]["pdf"])
    if not pdf_path.exists():
        raise HTTPException(404, "PDF file missing")
    return FileResponse(
        pdf_path, media_type="application/pdf", filename=f"Report_{job_id}.pdf"
    )


@app.get("/api/reports/{job_id}/data")
async def get_data(job_id: str):
    if job_id not in jobs or not jobs[job_id].get("data"):
        raise HTTPException(404, "Data not ready")
    return jobs[job_id].get("data")


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
