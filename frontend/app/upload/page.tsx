"use client";

import { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "motion/react";
import { Upload, FileType, CheckCircle, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { uploadReport } from "@/lib/api";
import { useMutation } from "@tanstack/react-query";

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const router = useRouter();

  const [step, setStep] = useState<1 | 2>(1);

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

  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      setFile(acceptedFiles[0]);
      setStep(2);
      toast.success("File accepted", { description: acceptedFiles[0].name });
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"]
    },
    maxFiles: 1,
  });

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("No file selected");
      return uploadReport(file, config);
    },
    onSuccess: (data) => {
      toast.success("Generation started!");
      router.push(`/generating/${data.job_id}`);
    },
    onError: (err) => {
      toast.error("Upload failed", { description: err.message });
    }
  });

  const handleGenerate = () => {
    if (!config.Company_Name) {
      toast.error("Missing fields", { description: "Company name is required." });
      return;
    }
    uploadMutation.mutate();
  };

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight">New Report</h1>
        <div className="flex items-center gap-2">
          <div className={`w-3 h-3 rounded-full ${step >= 1 ? 'bg-emerald-500' : 'bg-slate-700'}`} />
          <div className="w-10 h-[2px] bg-slate-800" />
          <div className={`w-3 h-3 rounded-full ${step >= 2 ? 'bg-emerald-500' : 'bg-slate-700'}`} />
        </div>
      </div>

      <AnimatePresence mode="wait">
        {step === 1 && (
          <motion.div
            key="step1"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
          >
            <div
              {...getRootProps()}
              className={`
                border-2 border-dashed rounded-2xl p-16 text-center cursor-pointer transition-all duration-300
                ${isDragActive ? "border-emerald-500 bg-emerald-500/10 scale-[1.02]" : "border-slate-700 hover:border-slate-500 hover:bg-slate-800/50"}
              `}
            >
              <input {...getInputProps()} />
              <div className="mx-auto w-20 h-20 mb-6 rounded-full bg-slate-800 flex items-center justify-center">
                {isDragActive ? (
                  <Upload className="w-10 h-10 text-emerald-500 animate-bounce" />
                ) : (
                  <FileType className="w-10 h-10 text-slate-400" />
                )}
              </div>
              <h3 className="text-2xl font-semibold mb-2">Drop your trial balance here</h3>
              <p className="text-slate-400">Supports .xlsx and .xls files</p>
            </div>
          </motion.div>
        )}

        {step === 2 && (
          <motion.div
            key="step2"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="grid md:grid-cols-2 gap-8"
          >
            <Card className="glass-card">
              <CardContent className="pt-6 space-y-4">
                <div className="flex items-center gap-4 p-4 rounded-lg bg-slate-800/50 border border-slate-700">
                  <div className="w-10 h-10 rounded-full bg-emerald-500/20 flex items-center justify-center">
                    <CheckCircle className="w-5 h-5 text-emerald-500" />
                  </div>
                  <div className="flex-1 overflow-hidden">
                    <p className="font-medium truncate">{file?.name}</p>
                    <p className="text-sm text-slate-400">{(file?.size || 0) / 1024} KB</p>
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => setStep(1)}>Change</Button>
                </div>

                <div className="space-y-4 pt-4 border-t border-slate-800">
                  <div className="space-y-2">
                    <Label>Company Name</Label>
                    <Input 
                      value={config.Company_Name} 
                      onChange={(e) => setConfig({...config, Company_Name: e.target.value})}
                      placeholder="e.g. Acme Corp LLC"
                      className="bg-slate-900/50"
                    />
                  </div>
                  
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label>License Number</Label>
                      <Input 
                        value={config.License_Number} 
                        onChange={(e) => setConfig({...config, License_Number: e.target.value})}
                        className="bg-slate-900/50"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Manager Name</Label>
                      <Input 
                        value={config.Manager_Name} 
                        onChange={(e) => setConfig({...config, Manager_Name: e.target.value})}
                        className="bg-slate-900/50"
                      />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label>Liquidator Name</Label>
                    <Input 
                      value={config.Liquidator_Name} 
                      onChange={(e) => setConfig({...config, Liquidator_Name: e.target.value})}
                      className="bg-slate-900/50"
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label>Liquidation Start</Label>
                      <Input 
                        type="date"
                        value={config.Liquidation_Start_Date} 
                        onChange={(e) => setConfig({...config, Liquidation_Start_Date: e.target.value})}
                        className="bg-slate-900/50 block w-full"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Period End</Label>
                      <Input 
                        type="date"
                        value={config.Period_End_Date} 
                        onChange={(e) => setConfig({...config, Period_End_Date: e.target.value})}
                        className="bg-slate-900/50 block w-full"
                      />
                    </div>
                  </div>
                </div>

                <div className="pt-6">
                  <Button 
                    className="w-full h-12 text-lg shadow-emerald-500/20 shadow-lg" 
                    onClick={handleGenerate}
                    disabled={uploadMutation.isPending}
                  >
                    {uploadMutation.isPending ? "Starting job..." : "Generate Report"}
                    {!uploadMutation.isPending && <ArrowRight className="ml-2 w-5 h-5" />}
                  </Button>
                </div>
              </CardContent>
            </Card>

            <div className="space-y-6">
              <h3 className="text-xl font-semibold">Live Preview</h3>
              <Card className="bg-slate-50 text-slate-900 p-8 shadow-2xl rotate-1 hover:rotate-0 transition-transform origin-bottom-right">
                <div className="text-center space-y-4">
                  <h2 className="text-3xl font-serif border-b pb-4">{config.Company_Name || "Company Name"}</h2>
                  <p className="text-lg font-serif">Liquidator's Report</p>
                  <p className="text-slate-600 font-serif">For the period ended {config.Period_End_Date || "..."}</p>
                </div>
                <div className="mt-12 space-y-2">
                  <div className="flex justify-between border-b pb-2">
                    <span className="font-semibold">License No:</span>
                    <span>{config.License_Number || "---"}</span>
                  </div>
                  <div className="flex justify-between border-b pb-2">
                    <span className="font-semibold">Manager:</span>
                    <span>{config.Manager_Name || "---"}</span>
                  </div>
                </div>
              </Card>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
