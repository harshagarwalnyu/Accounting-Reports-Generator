FROM python:3.12-slim

# Install system dependencies:
# - LibreOffice: DOCX→PDF conversion (primary, format-preserving)
# - texlive: LaTeX fallback compilation
# - fonts: proper rendering of accounting documents
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    libreoffice-writer \
    fonts-liberation \
    fonts-dejavu \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .

RUN mkdir -p temp_data templates

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
