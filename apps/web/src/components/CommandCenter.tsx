import React from 'react';
import { useHolmevStore } from '../store/useHolmevStore';
import { Terminal, Shield, Activity, Cpu, CheckCircle2, Clock, Layers } from 'lucide-react';

export const CommandCenter: React.FC = () => {
  const { health, voiceDiag, messages } = useHolmevStore();

  return (
    <div className="glass-panel rounded-2xl p-6 h-[calc(100vh-8rem)] flex flex-col border border-cyber-border">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-bold font-mono text-cyan-400 text-glow flex items-center gap-2">
            <Terminal className="w-5 h-5 text-cyan-400" />
            Developer & Diagnostics Command Center
          </h2>
          <p className="text-xs text-slate-400 font-mono">
            System Observability, Execution Graphs & Latency Telemetry
          </p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-6 flex-1 overflow-hidden">
        {/* Service Health Telemetry */}
        <div className="bg-slate-950/80 rounded-xl p-4 border border-slate-800 flex flex-col">
          <h3 className="text-xs font-mono font-bold text-slate-300 mb-3 flex items-center gap-2">
            <Shield className="w-4 h-4 text-emerald-400" />
            Subsystem Health Telemetry
          </h3>

          <div className="space-y-2 font-mono text-xs overflow-y-auto pr-1 flex-1">
            {Object.entries(health.services).map(([service, status]) => (
              <div key={service} className="bg-slate-900/60 p-2.5 rounded-lg border border-slate-800 flex items-center justify-between">
                <span className="capitalize text-slate-300">{service.replace("_", " ")}</span>
                <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                  status === "online" ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40" : "bg-amber-500/20 text-amber-400 border border-amber-500/40"
                }`}>
                  {status}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Execution Plan Graph & Tool Logs */}
        <div className="col-span-2 bg-slate-950/80 rounded-xl p-4 border border-slate-800 flex flex-col">
          <h3 className="text-xs font-mono font-bold text-slate-300 mb-3 flex items-center gap-2">
            <Layers className="w-4 h-4 text-cyan-400" />
            Active Execution Plan & Tool Verification Log
          </h3>

          <div className="flex-1 overflow-y-auto space-y-3 font-mono text-xs pr-1">
            {messages.map((msg) => (
              <div key={msg.id} className="bg-slate-900/70 p-3 rounded-xl border border-slate-800/80">
                <div className="flex items-center justify-between mb-1.5">
                  <span className={`font-bold ${msg.role === "user" ? "text-cyan-400" : msg.role === "assistant" ? "text-emerald-400" : "text-amber-400"}`}>
                    [{msg.role.toUpperCase()}]
                  </span>
                  <span className="text-[10px] text-slate-500">{msg.timestamp}</span>
                </div>
                <div className="text-slate-200">{msg.content}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
