"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { getReportData, API_BASE_URL } from "@/lib/api";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from "recharts";
import { motion } from "motion/react";

function AnimatedNumber({ value }: { value: number }) {
  // Simple static display for now, motion values could be applied here
  const formatted = new Intl.NumberFormat("en-AE", {
    style: "currency",
    currency: "AED",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0
  }).format(value);
  
  return <span className="financial-number">{formatted}</span>;
}

export default function ReportViewer() {
  const { id } = useParams() as { id: string };

  const { data, isLoading, error } = useQuery({
    queryKey: ["report", id],
    queryFn: () => getReportData(id),
  });

  if (isLoading) {
    return (
      <div className="h-[calc(100vh-8rem)] flex items-center justify-center">
        <div className="space-y-4 text-center">
          <Skeleton className="w-16 h-16 rounded-full mx-auto" />
          <h2 className="text-xl font-medium">Loading Report Data...</h2>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="text-center text-destructive py-20">
        <h2 className="text-2xl font-bold">Failed to load report</h2>
        <p>{error?.message}</p>
      </div>
    );
  }

  const totals = data.Totals || {};
  const financialPosition = data["Financial Position"] || {};
  
  // Prepare chart data
  const chartData: any[] = [];
  if (financialPosition.Assets) {
    Object.entries(financialPosition.Assets).forEach(([name, amounts]: any) => {
      chartData.push({
        name,
        category: "Assets",
        current: amounts["Amount-25"] || 0,
        prior: amounts["Amount-24"] || 0
      });
    });
  }
  if (financialPosition["Liabilities & Equity"]) {
    Object.entries(financialPosition["Liabilities & Equity"]).forEach(([name, amounts]: any) => {
      chartData.push({
        name,
        category: "Liabilities",
        current: Math.abs(amounts["Amount-25"] || 0),
        prior: Math.abs(amounts["Amount-24"] || 0)
      });
    });
  }

  return (
    <div className="h-[calc(100vh-6rem)] -m-4">
      {/* @ts-expect-error - shadcn types are currently mismatched */}
      <ResizablePanelGroup direction="horizontal">
        <ResizablePanel defaultSize={50} minSize={30}>
          <div className="h-full overflow-y-auto p-6 space-y-6">
            <div className="flex items-center justify-between">
              <h2 className="text-2xl font-bold tracking-tight">Financial Dashboard</h2>
            </div>
            
            <div className="grid grid-cols-2 gap-4">
              <Card className="glass-card">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-slate-400">Total Assets</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-bold text-emerald-400">
                    <AnimatedNumber value={totals["Total Assets"] || 0} />
                  </div>
                </CardContent>
              </Card>
              <Card className="glass-card">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-slate-400">Total Liabilities</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-bold text-rose-400">
                    <AnimatedNumber value={Math.abs(totals["Total Liabilities & Equity"] || 0)} />
                  </div>
                </CardContent>
              </Card>
            </div>

            <Card className="glass-card h-[400px]">
              <CardHeader>
                <CardTitle>Current vs Prior Year (AED)</CardTitle>
              </CardHeader>
              <CardContent className="h-[300px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1E293B" vertical={false} />
                    <XAxis 
                      dataKey="name" 
                      stroke="#94a3b8" 
                      tick={{ fill: '#94a3b8', fontSize: 12 }} 
                      tickFormatter={(value) => value.substring(0, 15) + (value.length > 15 ? '...' : '')}
                    />
                    <YAxis stroke="#94a3b8" tick={{ fill: '#94a3b8', fontSize: 12 }} />
                    <Tooltip 
                      contentStyle={{ backgroundColor: '#0A0F1E', borderColor: '#1E293B', color: '#e2e8f0' }}
                      itemStyle={{ color: '#e2e8f0' }}
                      cursor={{ fill: '#1E293B' }}
                    />
                    <Legend wrapperStyle={{ paddingTop: '20px' }} />
                    <Bar dataKey="current" name="Current Year" fill="#10B981" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="prior" name="Prior Year" fill="#1E293B" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>
        </ResizablePanel>
        
        <ResizableHandle withHandle className="bg-slate-800" />
        
        <ResizablePanel defaultSize={50} minSize={30}>
          <div className="h-full bg-slate-900 border-l border-slate-800 p-4">
             <iframe 
                src={`${API_BASE_URL}/reports/${id}/pdf`}
                className="w-full h-full rounded-lg border border-slate-800 shadow-xl"
                title="Report PDF"
             />
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}
