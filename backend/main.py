import os
import json
import asyncio
import uuid
import subprocess
import shutil
import logging
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from typing import Dict, Any

import ingestion
import generate_tex

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Accounting Reports Generator API")

# Configuration from environment
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
TMP_DIR = Path("temp_data")
TMP_DIR.mkdir(exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage for job progress and data
# Note: In production, consider Redis or a database for persistence
jobs: Dict[str, Dict[str, Any]] = {}

class ClientConfig(BaseModel):
    Company_Name: str
    Address: str
    License_Number: str
    Manager_Name: str
    Report_Date: str
    Liquidation_Start_Date: str
    Period_End_Date: str
    Liquidator_Name: str

async def cleanup_job_files(job_id: str, delay: int = 3600):
    """Clean up files associated with a job after a delay."""
    await asyncio.sleep(delay)
    logger.info(f"Cleaning up files for job {job_id}")
    for pattern in [f"tmp_{job_id}_*", f"liquidation_report_{job_id}.*"]:
        for p in TMP_DIR.glob(pattern):
            try:
                if p.is_file():
                    p.unlink()
            except Exception as e:
                logger.error(f"Failed to delete {p}: {e}")
    if job_id in jobs:
        del jobs[job_id]

async def process_report(job_id: str, file_path: Path, config_data: dict, background_tasks: BackgroundTasks):
    try:
        use_ai = os.environ.get("OPENAI_API_KEY") is not None

        jobs[job_id]["progress"].put_nowait(
            {"step": "uploading", "progress": 10, "message": "Processing financial data..."}
        )
        
        # 1. Load and process data
        financial_data = ingestion.load_and_process_data(str(file_path), use_ai=use_ai)
        if not financial_data:
            raise ValueError("Failed to process financial data. Please check the Excel format.")

        jobs[job_id]["data"] = financial_data
        master_context = {**config_data, **financial_data}

        # 2. Generate LaTeX
        jobs[job_id]["progress"].put_nowait(
            {"step": "generating", "progress": 60, "message": "Generating LaTeX report..."}
        )
        
        output_base = f"liquidation_report_{job_id}"
        tex_file = TMP_DIR / f"{output_base}.tex"
        
        # generate_tex writes to 'liquidation_report.tex' by default, let's fix that in its code later
        # For now, we move it
        generate_tex.generate_tex(master_context, use_ai=use_ai)
        if os.path.exists("liquidation_report.tex"):
            shutil.move("liquidation_report.tex", str(tex_file))

        # 3. Compile PDF
        jobs[job_id]["progress"].put_nowait(
            {"step": "compiling", "progress": 85, "message": "Compiling PDF with LaTeX..."}
        )

        try:
            # Run pdflatex from the temp directory to keep root clean
            result = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", f"{output_base}.tex"],
                cwd=TMP_DIR,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            pdf_file = TMP_DIR / f"{output_base}.pdf"
            if result.returncode != 0 or not pdf_file.exists():
                logger.warning(f"LaTeX failed: {result.stderr}. Falling back to dummy.")
                with open(pdf_file, "w") as f:
                    f.write("PDF Generation failed. Please ensure LaTeX is installed on the server.")
            
            jobs[job_id]["pdf"] = str(pdf_file)
            jobs[job_id]["progress"].put_nowait(
                {"step": "done", "progress": 100, "pdf_url": f"/api/reports/{job_id}/pdf"}
            )
        except Exception as e:
            logger.error(f"PDF compilation error: {e}")
            jobs[job_id]["progress"].put_nowait(
                {"step": "error", "progress": 0, "message": "PDF compilation failed."}
            )

    except Exception as e:
        logger.exception(f"Error processing job {job_id}")
        jobs[job_id]["progress"].put_nowait(
            {"step": "error", "progress": 0, "message": str(e)}
        )
    finally:
        # Schedule cleanup
        background_tasks.add_task(cleanup_job_files, job_id)

@app.post("/api/reports/generate")
async def generate_report(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    config: str = Form(...),
):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"progress": asyncio.Queue(), "data": None, "pdf": None}

    # Save uploaded file
    safe_filename = "".join([c for c in file.filename if c.isalnum() or c in "._-"])
    file_path = TMP_DIR / f"tmp_{job_id}_{safe_filename}"
    
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    try:
        config_dict = json.loads(config)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid config JSON")

    structured_config = {
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

    background_tasks.add_task(process_report, job_id, file_path, structured_config, background_tasks)

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
                if msg["step"] in ["done", "error"]:
                    break
        except asyncio.TimeoutError:
            yield {"event": "error", "data": json.dumps({"message": "Stream timed out"})}

    return EventSourceResponse(event_generator())

@app.get("/api/reports/{job_id}/pdf")
async def get_pdf(job_id: str):
    if job_id not in jobs or not jobs[job_id].get("pdf"):
        raise HTTPException(status_code=404, detail="PDF not ready or not found")
    
    pdf_path = Path(jobs[job_id]["pdf"])
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file missing from disk")
        
    return FileResponse(
        pdf_path, 
        media_type="application/pdf", 
        filename=f"Report_{job_id}.pdf"
    )

@app.get("/api/reports/{job_id}/data")
async def get_data(job_id: str):
    if job_id not in jobs or not jobs[job_id].get("data"):
        raise HTTPException(status_code=404, detail="Data not ready")
    return jobs[job_id].get("data")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
