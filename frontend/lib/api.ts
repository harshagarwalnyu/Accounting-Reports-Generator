export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "/api";

// ── Report generation ─────────────────────────────────────────────────────────

export async function uploadReport(
  file: File,
  config: Record<string, string>,
  sampleAudit: File | null = null,
  sampleLiquidation: File | null = null,
  auditTemplateId: string | null = null,
  liquidationTemplateId: string | null = null,
) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("config", JSON.stringify(config));

  if (sampleAudit) formData.append("sample_audit", sampleAudit);
  if (sampleLiquidation) formData.append("sample_liquidation", sampleLiquidation);
  if (auditTemplateId) formData.append("audit_template_id", auditTemplateId);
  if (liquidationTemplateId) formData.append("liquidation_template_id", liquidationTemplateId);

  const res = await fetch(`${API_BASE_URL}/reports/generate`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Failed to start report generation: ${res.status} ${body}`);
  }
  return res.json() as Promise<{ job_id: string }>;
}

export async function getReportData(jobId: string) {
  const res = await fetch(`${API_BASE_URL}/reports/${jobId}/data`);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Failed to fetch report data: ${res.status} ${body}`);
  }
  return res.json();
}

// ── Template management ───────────────────────────────────────────────────────

export interface TemplateInfo {
  template_id: string;
  report_type: "audit" | "liquidation";
  original_filename: string;
  created_at: string;
  applied_replacements: Record<string, string>;
}

export async function getTemplates(): Promise<TemplateInfo[]> {
  const res = await fetch(`${API_BASE_URL}/templates`);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Failed to fetch templates: ${res.status} ${body}`);
  }
  return res.json();
}

export async function createTemplate(
  sampleFile: File,
  reportType: "audit" | "liquidation",
  templateId: string,
  knownValues: Record<string, string>,
): Promise<TemplateInfo> {
  const formData = new FormData();
  formData.append("sample_file", sampleFile);
  formData.append("report_type", reportType);
  formData.append("template_id", templateId);
  formData.append("known_values", JSON.stringify(knownValues));

  const res = await fetch(`${API_BASE_URL}/templates`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Template creation failed: ${res.status} ${body}`);
  }
  return res.json();
}

export async function deleteTemplate(templateId: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/templates/${templateId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Failed to delete template: ${res.status} ${body}`);
  }
}
