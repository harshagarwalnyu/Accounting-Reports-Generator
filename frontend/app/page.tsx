import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { ArrowRight, Activity, Layers, Copy, Zap } from "lucide-react";

export default function Dashboard() {
  return (
    <div className="max-w-5xl mx-auto space-y-12">
      <section className="text-center py-20 space-y-6">
        <h1 className="text-5xl font-bold tracking-tight text-gradient">
          Financial Reports. <br /> Exact Format. Automated.
        </h1>
        <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
          Upload a sample audit or liquidation report, upload your client&apos;s trial balance,
          and get back a pixel-perfect PDF that matches your firm&apos;s exact format — every time.
        </p>
        <div className="pt-8 flex flex-col sm:flex-row gap-4 justify-center">
          <Link href="/upload">
            <Button size="lg" className="h-14 px-8 text-lg font-medium shadow-emerald-500/25 shadow-lg hover:scale-105 transition-transform">
              Generate New Report <ArrowRight className="ml-2 w-5 h-5" />
            </Button>
          </Link>
        </div>
      </section>

      <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="glass-card bg-white/5 border-white/10 hover:-translate-y-1 transition-transform">
          <CardHeader>
            <Copy className="w-8 h-8 text-emerald-500 mb-2" />
            <CardTitle>Exact Format Clone</CardTitle>
            <CardDescription>Not AI-generated layout</CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-slate-400">
            Your sample document is cloned directly — fonts, margins, table borders, spacing — and only the data values are replaced. No LLM is used for formatting.
          </CardContent>
        </Card>

        <Card className="glass-card bg-white/5 border-white/10 hover:-translate-y-1 transition-transform">
          <CardHeader>
            <Layers className="w-8 h-8 text-emerald-500 mb-2" />
            <CardTitle>Template Library</CardTitle>
            <CardDescription>Save once, reuse forever</CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-slate-400">
            Save your firm&apos;s audit and liquidation templates. For every new client, just upload their Excel — the format is applied automatically.
          </CardContent>
        </Card>

        <Card className="glass-card bg-white/5 border-white/10 hover:-translate-y-1 transition-transform">
          <CardHeader>
            <Zap className="w-8 h-8 text-emerald-500 mb-2" />
            <CardTitle>Any Excel Format</CardTitle>
            <CardDescription>Auto-detects column structure</CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-slate-400">
            No rigid column name requirements. The system detects account names, current year, and prior year amounts from any trial balance layout.
          </CardContent>
        </Card>

        <Card className="glass-card bg-white/5 border-white/10 hover:-translate-y-1 transition-transform">
          <CardHeader>
            <Activity className="w-8 h-8 text-emerald-500 mb-2" />
            <CardTitle>Live Progress</CardTitle>
            <CardDescription>Real-time SSE streaming</CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-slate-400">
            Watch every step — parsing, template filling, PDF compilation — in real time with live progress updates.
          </CardContent>
        </Card>
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-8 space-y-4">
        <h2 className="text-2xl font-bold">How it works</h2>
        <div className="grid md:grid-cols-3 gap-6 text-sm">
          {[
            ["1. Upload Sample", "Provide your firm's existing audit or liquidation report (DOCX preferred, PDF supported). This defines the format."],
            ["2. Upload Trial Balance", "Upload the client's Excel trial balance in any format. The system identifies account names and amounts automatically."],
            ["3. Download PDF", "Receive a complete PDF with your firm's exact formatting, populated with the new client's financial data."],
          ].map(([title, desc]) => (
            <div key={title} className="space-y-2">
              <p className="font-semibold text-emerald-400">{title}</p>
              <p className="text-slate-400">{desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
