"use client";

import { useSSE } from "@/lib/hooks/useSSE";
import { useParams, useRouter } from "next/navigation";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { CheckCircle2, Circle, Loader2, ArrowRight } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { Button } from "@/components/ui/button";
import { useEffect } from "react";
import { API_BASE_URL } from "@/lib/api";

const STEPS = ["uploading", "generating", "compiling", "done"];

const STEP_LABELS: Record<string, string> = {
  uploading: "Processing Trial Balance",
  generating: "Generating Report Document",
  compiling: "Compiling PDF",
  done: "Report Ready",
};

export default function GeneratingPage() {
  const { id } = useParams() as { id: string };
  const router = useRouter();
  const { events, isComplete, error } = useSSE(id);

  // Fallback: If we get an error or on mount, check if the report is already done
  useEffect(() => {
    const checkStatus = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/reports/${id}/data`);
        if (res.ok) {
          router.push(`/reports/${id}`);
        }
      } catch (e) {
        // ignore
      }
    };
    
    if (error || !isComplete) {
      checkStatus();
    }
  }, [error, id, router, isComplete]);

  // Auto-redirect when done
  useEffect(() => {
    if (isComplete) {
      const t = setTimeout(() => router.push(`/reports/${id}`), 2500);
      return () => clearTimeout(t);
    }
  }, [isComplete, id, router]);

  const currentEvent = events[events.length - 1];
  const progressValue = currentEvent?.progress || 0;
  const currentStepIndex = STEPS.indexOf(currentEvent?.step || "uploading");

  return (
    <div className="max-w-3xl mx-auto py-12 space-y-8">
      <div className="text-center space-y-4">
        <h1 className="text-3xl font-bold tracking-tight">Generating Report</h1>
        <p className="text-muted-foreground">Please wait while we process your financial data and generate the report document.</p>
      </div>

      <Card className="glass-card overflow-hidden">
        <div className="bg-slate-900/50 p-4 border-b border-slate-800">
          <Progress value={progressValue} className="h-2" />
        </div>
        <CardContent className="p-8">
          {error ? (
            <div className="text-destructive text-center py-8">
              <h3 className="text-lg font-semibold mb-2">Generation Failed</h3>
              <p>{error}</p>
            </div>
          ) : (
            <div className="space-y-6">
              {STEPS.map((step, idx) => {
                const isActive = idx === currentStepIndex;
                const isPast = idx < currentStepIndex || isComplete;
                
                return (
                  <div key={step} className="flex items-center gap-4">
                    <div className="relative">
                      {isPast ? (
                        <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }}>
                          <CheckCircle2 className="w-6 h-6 text-emerald-500" />
                        </motion.div>
                      ) : isActive ? (
                        <div className="relative flex items-center justify-center">
                          <Circle className="w-6 h-6 text-emerald-500/30" />
                          <Loader2 className="w-4 h-4 text-emerald-500 absolute animate-spin" />
                        </div>
                      ) : (
                        <Circle className="w-6 h-6 text-slate-700" />
                      )}
                    </div>
                    
                    <div className={`flex-1 transition-colors duration-300 ${isActive ? 'text-white' : isPast ? 'text-slate-300' : 'text-slate-600'}`}>
                      <h4 className="font-medium text-lg">{STEP_LABELS[step as keyof typeof STEP_LABELS]}</h4>
                      <AnimatePresence>
                        {isActive && currentEvent?.message && (
                          <motion.p 
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: 'auto' }}
                            exit={{ opacity: 0, height: 0 }}
                            className="text-sm text-emerald-400/80 mt-1"
                          >
                            {currentEvent.message}
                          </motion.p>
                        )}
                      </AnimatePresence>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          <AnimatePresence>
            {isComplete && (
              <motion.div 
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="mt-12 pt-8 border-t border-slate-800 text-center"
              >
                <h3 className="text-2xl font-bold text-gradient mb-6">Success!</h3>
                <Button 
                  size="lg" 
                  className="h-12 px-8 text-lg font-medium shadow-emerald-500/25 shadow-lg hover:scale-105 transition-transform"
                  onClick={() => router.push(`/reports/${id}`)}
                >
                  View Report <ArrowRight className="ml-2 w-5 h-5" />
                </Button>
              </motion.div>
            )}
          </AnimatePresence>
        </CardContent>
      </Card>
    </div>
  );
}
