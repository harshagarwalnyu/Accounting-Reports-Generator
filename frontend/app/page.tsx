import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { ArrowRight, FileText, Activity, Layers } from "lucide-react";

export default function Dashboard() {
  return (
    <div className="max-w-5xl mx-auto space-y-12">
      <section className="text-center py-20 space-y-6">
        <h1 className="text-5xl font-bold tracking-tight text-gradient">
          Financial Intelligence. <br/> Automated.
        </h1>
        <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
          Transform raw trial balances into professional, audit-ready liquidation reports in seconds.
        </p>
        <div className="pt-8">
          <Link href="/upload">
            <Button size="lg" className="h-14 px-8 text-lg font-medium shadow-emerald-500/25 shadow-lg hover:scale-105 transition-transform">
              Generate New Report <ArrowRight className="ml-2 w-5 h-5" />
            </Button>
          </Link>
        </div>
      </section>

      <div className="grid md:grid-cols-3 gap-6">
        <Card className="glass-card bg-white/5 border-white/10 hover:-translate-y-1 transition-transform">
          <CardHeader>
            <FileText className="w-8 h-8 text-emerald-500 mb-2" />
            <CardTitle>Instant LaTeX Generation</CardTitle>
            <CardDescription>Pixel-perfect PDF output</CardDescription>
          </CardHeader>
          <CardContent>
            Automatically compiles financial statements into a beautiful LaTeX document, ensuring typography is crisp and professional.
          </CardContent>
        </Card>
        
        <Card className="glass-card bg-white/5 border-white/10 hover:-translate-y-1 transition-transform">
          <CardHeader>
            <Layers className="w-8 h-8 text-emerald-500 mb-2" />
            <CardTitle>Smart Data Mapping</CardTitle>
            <CardDescription>Intelligent account categorization</CardDescription>
          </CardHeader>
          <CardContent>
            Map trial balance accounts to standard financial statement lines automatically with real-time preview and editing.
          </CardContent>
        </Card>
        
        <Card className="glass-card bg-white/5 border-white/10 hover:-translate-y-1 transition-transform">
          <CardHeader>
            <Activity className="w-8 h-8 text-emerald-500 mb-2" />
            <CardTitle>Real-time Insights</CardTitle>
            <CardDescription>Live streaming updates</CardDescription>
          </CardHeader>
          <CardContent>
            Watch your report generate in real-time with Server-Sent Events showing progress and dynamic financial insights.
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
