"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "motion/react";
import { Upload, FileType, CheckCircle, ArrowRight, FileText, Library, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { uploadReport, getTemplates, deleteTemplate, type TemplateInfo } from "@/lib/api";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

type Step = 1 | 2 | 3;
type TemplateMode = "library" | "upload" | "none";

export default function UploadPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [step, setStep] = useState<Step>(1);

  // Step 1 — files
  const [file, setFile] = useState<File | null>(null);

  // Step 2 — template selection
  const [auditMode, setAuditMode] = useState<TemplateMode>("none");
  const [liquidationMode, setLiquidationMode] = useState<TemplateMode>("none");
  const [selectedAuditId, setSelectedAuditId] = useState<string | null>(null);
  const [selectedLiquidationId, setSelectedLiquidationId] = useState<string | null>(null);
  const [sampleAudit, setSampleAudit] = useState<File | null>(null);
  const [sampleLiquidation, setSampleLiquidation] = useState<File | null>(null);

  // Step 3 — config
  const [config, setConfig] = useState({
    Company_Name: "",
    Address: "",
    License_Number: "",
    Manager_Name: "",
    Report_Date: new Date().toISOString().split("T")[0],
    Liquidation_Start_Date: "",
    Period_End_Date: "",
    Liquidator_Name: "",
  });

  // Fetch saved templates
  const { data: templates = [] } = useQuery<TemplateInfo[]>({
    queryKey: ["templates"],
    queryFn: getTemplates,
  });

  const auditTemplates = templates.filter(t => t.report_type === "audit");
  const liqTemplates = templates.filter(t => t.report_type === "liquidation");

  const deleteMutation = useMutation({
    mutationFn: deleteTemplate,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates"] });
      toast.success("Template deleted");
    },
  });

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("No file");
      if (!config.Company_Name) throw new Error("Company name is required");
      return uploadReport(
        file, config,
        auditMode === "upload" ? sampleAudit : null,
        liquidationMode === "upload" ? sampleLiquidation : null,
        auditMode === "library" ? selectedAuditId : null,
        liquidationMode === "library" ? selectedLiquidationId : null,
      );
    },
    onSuccess: (data) => {
      toast.success("Generation started!");
      router.push(`/generating/${data.job_id}`);
    },
    onError: (err: Error) => {
      toast.error("Failed", { description: err.message });
    },
  });

  const steps = ["Upload Excel", "Select Templates", "Configure & Generate"];

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Step indicator */}
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight">New Report</h1>
        <div className="flex items-center gap-2">
          {steps.map((label, i) => (
            <div key={i} className="flex items-center gap-2">
              <div className="flex items-center gap-1.5">
                <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold transition-all ${
                  step > i + 1 
                    ? "bg-emerald-600 text-white" 
                    : step === i + 1 
                    ? "bg-emerald-500 text-white ring-2 ring-emerald-400 ring-offset-2 ring-offset-slate-950" 
                    : "bg-slate-700 text-slate-400"
                }`}>
                  {step > i + 1 ? "✓" : i + 1}
                </div>
                <span className={`text-xs hidden sm:block ${step === i + 1 ? "text-white" : "text-slate-500"}`}>{label}</span>
              </div>
              {i < steps.length - 1 && <div className="w-8 h-[2px] bg-slate-800" />}
            </div>
          ))}
        </div>
      </div>

      <AnimatePresence mode="wait">

        {/* ── Step 1: Upload Excel ── */}
        {step === 1 && (
          <motion.div key="step1" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }} className="space-y-6">
            <Card className="glass-card">
              <CardContent className="pt-6">
                <Label className="text-lg font-semibold mb-3 block">Trial Balance (Excel)</Label>
                <p className="text-sm text-slate-400 mb-4">
                  Upload your client&apos;s trial balance. Any column structure is supported — the system auto-detects account names and amounts.
                </p>
                <div className="border-2 border-dashed rounded-xl p-10 text-center bg-slate-800/20 border-slate-700 relative cursor-pointer hover:border-emerald-500/50 transition-colors">
                  <Input
                    type="file"
                    accept=".xlsx,.xls"
                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                  />
                  <FileType className={`w-12 h-12 mb-3 mx-auto ${file ? "text-emerald-500" : "text-slate-400"}`} />
                  <p className="font-medium">{file ? file.name : "Click or drop Excel file here"}</p>
                  <p className="text-sm text-slate-500 mt-1">.xlsx or .xls</p>
                </div>
              </CardContent>
            </Card>
            <Button className="w-full h-12 text-lg" onClick={() => {
              if (!file) { toast.error("Please upload a trial balance first"); return; }
              setStep(2);
            }}>
              Continue <ArrowRight className="ml-2 w-5 h-5" />
            </Button>
          </motion.div>
        )}

        {/* ── Step 2: Template Selection ── */}
        {step === 2 && (
          <motion.div key="step2" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }} className="space-y-6">
            <div className="p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
              <p className="text-sm text-emerald-400">
                <strong>Format fidelity:</strong> When you provide a sample report, the system clones its exact format — fonts, spacing, tables — and fills in the new client&apos;s data. No AI is used for layout.
              </p>
            </div>

            {/* Audit Report Template */}
            <TemplateSelector
              title="Audit Report Template"
              savedTemplates={auditTemplates}
              mode={auditMode}
              setMode={setAuditMode}
              selectedId={selectedAuditId}
              setSelectedId={setSelectedAuditId}
              uploadedFile={sampleAudit}
              setUploadedFile={setSampleAudit}
              onDelete={(id) => deleteMutation.mutate(id)}
            />

            {/* Liquidation Report Template */}
            <TemplateSelector
              title="Liquidation Report Template"
              savedTemplates={liqTemplates}
              mode={liquidationMode}
              setMode={setLiquidationMode}
              selectedId={selectedLiquidationId}
              setSelectedId={setSelectedLiquidationId}
              uploadedFile={sampleLiquidation}
              setUploadedFile={setSampleLiquidation}
              onDelete={(id) => deleteMutation.mutate(id)}
            />

            <div className="flex gap-3">
              <Button variant="outline" className="flex-1" onClick={() => setStep(1)}>Back</Button>
              <Button className="flex-1" onClick={() => {
                if (auditMode === "none" && liquidationMode === "none") {
                  toast.error("Please select at least one template (audit or liquidation)");
                  return;
                }
                if (auditMode === "library" && !selectedAuditId) {
                  toast.error("Please select an audit template from the library");
                  return;
                }
                if (auditMode === "upload" && !sampleAudit) {
                  toast.error("Please upload an audit sample document");
                  return;
                }
                if (liquidationMode === "library" && !selectedLiquidationId) {
                  toast.error("Please select a liquidation template from the library");
                  return;
                }
                if (liquidationMode === "upload" && !sampleLiquidation) {
                  toast.error("Please upload a liquidation sample document");
                  return;
                }
                setStep(3);
              }}>
                Continue to Configuration <ArrowRight className="ml-2 w-5 h-5" />
              </Button>
            </div>
          </motion.div>
        )}

        {/* ── Step 3: Configuration ── */}
        {step === 3 && (
          <motion.div key="step3" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="grid md:grid-cols-2 gap-8">
            <Card className="glass-card">
              <CardContent className="pt-6 space-y-4">
                {/* Summary */}
                <div className="flex items-center gap-3 p-3 rounded-lg bg-slate-800/50 border border-slate-700">
                  <CheckCircle className="w-5 h-5 text-emerald-500 shrink-0" />
                  <div className="flex-1 overflow-hidden">
                    <p className="font-medium text-sm truncate">{file?.name}</p>
                    <div className="flex gap-2 mt-1">
                      {(auditMode !== "none") && (
                        <Badge variant="secondary" className="text-xs">Audit ✓</Badge>
                      )}
                      {(liquidationMode !== "none") && (
                        <Badge variant="secondary" className="text-xs">Liquidation ✓</Badge>
                      )}
                    </div>
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => setStep(2)}>Back</Button>
                </div>

                <div className="space-y-4 pt-2 border-t border-slate-800">
                  <div className="space-y-2">
                    <Label>Company Name *</Label>
                    <Input value={config.Company_Name} onChange={(e) => setConfig({ ...config, Company_Name: e.target.value })} placeholder="ABC Trading LLC" className="bg-slate-900/50" />
                  </div>

                  <div className="space-y-2">
                    <Label>Address</Label>
                    <Input value={config.Address} onChange={(e) => setConfig({ ...config, Address: e.target.value })} placeholder="Dubai, UAE" className="bg-slate-900/50" />
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label>License Number</Label>
                      <Input value={config.License_Number} onChange={(e) => setConfig({ ...config, License_Number: e.target.value })} className="bg-slate-900/50" />
                    </div>
                    <div className="space-y-2">
                      <Label>Manager Name</Label>
                      <Input value={config.Manager_Name} onChange={(e) => setConfig({ ...config, Manager_Name: e.target.value })} className="bg-slate-900/50" />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label>Liquidator Name</Label>
                    <Input value={config.Liquidator_Name} onChange={(e) => setConfig({ ...config, Liquidator_Name: e.target.value })} className="bg-slate-900/50" />
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label>Report Date</Label>
                      <Input type="date" value={config.Report_Date} onChange={(e) => setConfig({ ...config, Report_Date: e.target.value })} className="bg-slate-900/50 block w-full" />
                    </div>
                    <div className="space-y-2">
                      <Label>Period End</Label>
                      <Input type="date" value={config.Period_End_Date} onChange={(e) => setConfig({ ...config, Period_End_Date: e.target.value })} className="bg-slate-900/50 block w-full" />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label>Liquidation Start Date</Label>
                    <Input type="date" value={config.Liquidation_Start_Date} onChange={(e) => setConfig({ ...config, Liquidation_Start_Date: e.target.value })} className="bg-slate-900/50 block w-full" />
                  </div>
                </div>

                <div className="pt-4">
                  <Button
                    className="w-full h-12 text-lg shadow-emerald-500/20 shadow-lg"
                    onClick={() => uploadMutation.mutate()}
                    disabled={uploadMutation.isPending}
                  >
                    {uploadMutation.isPending ? "Starting..." : "Generate Report"}
                    {!uploadMutation.isPending && <ArrowRight className="ml-2 w-5 h-5" />}
                  </Button>
                </div>
              </CardContent>
            </Card>

            {/* Live preview */}
            <div className="space-y-4 hidden md:block">
              <h3 className="text-xl font-semibold">Preview</h3>
              <Card className="bg-slate-50 text-slate-900 p-8 shadow-2xl rotate-1 hover:rotate-0 transition-transform origin-bottom-right">
                <div className="text-center space-y-3 border-b pb-4">
                  <h2 className="text-2xl font-serif font-bold">{config.Company_Name || "Company Name"}</h2>
                  <p className="font-serif text-slate-700">Liquidator&apos;s Report</p>
                  <p className="text-sm text-slate-500 font-serif">Period ended {config.Period_End_Date || "—"}</p>
                </div>
                <div className="mt-6 space-y-2 text-sm">
                  {[
                    ["License No", config.License_Number],
                    ["Manager", config.Manager_Name],
                    ["Liquidator", config.Liquidator_Name],
                  ].map(([label, val]) => (
                    <div key={label} className="flex justify-between border-b pb-1">
                      <span className="font-semibold">{label}:</span>
                      <span>{val || "—"}</span>
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}


// ── Template Selector Component ───────────────────────────────────────────────

function TemplateSelector({
  title,
  savedTemplates,
  mode,
  setMode,
  selectedId,
  setSelectedId,
  uploadedFile,
  setUploadedFile,
  onDelete,
}: {
  title: string;
  savedTemplates: TemplateInfo[];
  mode: TemplateMode;
  setMode: (m: TemplateMode) => void;
  selectedId: string | null;
  setSelectedId: (id: string | null) => void;
  uploadedFile: File | null;
  setUploadedFile: (f: File | null) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <Card className="glass-card">
      <CardHeader className="pb-3">
        <CardTitle className="text-base font-semibold flex items-center gap-2">
          <FileText className="w-4 h-4 text-emerald-500" />
          {title}
          {mode !== "none" && <Badge className="ml-auto text-xs bg-emerald-500/20 text-emerald-400 border-emerald-500/30">Selected</Badge>}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Mode selector */}
        <div className="flex gap-2">
          <Button
            variant={mode === "library" ? "default" : "outline"}
            size="sm"
            className="flex-1"
            onClick={() => setMode(mode === "library" ? "none" : "library")}
            disabled={savedTemplates.length === 0}
          >
            <Library className="w-3.5 h-3.5 mr-1.5" />
            Saved Templates {savedTemplates.length > 0 && `(${savedTemplates.length})`}
          </Button>
          <Button
            variant={mode === "upload" ? "default" : "outline"}
            size="sm"
            className="flex-1"
            onClick={() => setMode(mode === "upload" ? "none" : "upload")}
          >
            <Plus className="w-3.5 h-3.5 mr-1.5" />
            Upload Sample
          </Button>
          {mode !== "none" && (
            <Button variant="ghost" size="sm" onClick={() => { setMode("none"); setSelectedId(null); setUploadedFile(null); }}>
              Clear
            </Button>
          )}
        </div>

        {/* Library picker */}
        {mode === "library" && savedTemplates.length > 0 && (
          <div className="space-y-2">
            {savedTemplates.map(t => (
              <div
                key={t.template_id}
                className={`flex items-center justify-between p-3 rounded-lg border cursor-pointer transition-colors ${selectedId === t.template_id ? "border-emerald-500 bg-emerald-500/10" : "border-slate-700 hover:border-slate-600"}`}
                onClick={() => setSelectedId(t.template_id)}
              >
                <div>
                  <p className="text-sm font-medium">{t.template_id}</p>
                  <p className="text-xs text-slate-400">{t.original_filename} · {new Date(t.created_at).toLocaleDateString()}</p>
                </div>
                <div className="flex items-center gap-2">
                  {selectedId === t.template_id && <CheckCircle className="w-4 h-4 text-emerald-500" />}
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 w-7 p-0 text-slate-500 hover:text-red-400"
                    onClick={(e) => { e.stopPropagation(); onDelete(t.template_id); }}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Upload sample */}
        {mode === "upload" && (
          <div className="border-2 border-dashed rounded-lg p-6 text-center relative cursor-pointer hover:border-emerald-500/50 transition-colors border-slate-700">
            <Input
              type="file"
              accept=".pdf,.doc,.docx"
              className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
              onChange={(e) => setUploadedFile(e.target.files?.[0] || null)}
            />
            <Upload className={`w-8 h-8 mb-2 mx-auto ${uploadedFile ? "text-emerald-500" : "text-slate-400"}`} />
            <p className="text-sm font-medium">{uploadedFile ? uploadedFile.name : "Upload sample report"}</p>
            <p className="text-xs text-slate-500 mt-1">DOCX preferred for exact format match · PDF also accepted</p>
          </div>
        )}

        {mode === "none" && (
          <p className="text-xs text-slate-500 text-center py-2">
            No template selected — a default format will be used
          </p>
        )}
      </CardContent>
    </Card>
  );
}
