import React from 'react';
import { useHolmevStore } from '../store/useHolmevStore';
import { Activity, Box, Cpu, Terminal, Shield, Mic } from 'lucide-react';

export const Navbar: React.FC = () => {
  const { activeTab, setActiveTab, voiceDiag, health } = useHolmevStore();

  return (
    <header className="h-16 border-b border-cyber-border glass-panel px-6 flex items-center justify-between z-50 relative">
      <div className="flex items-center space-x-3">
        <div className="relative">
          <div className="w-9 h-9 rounded-lg bg-cyan-500/20 border border-cyber-cyan flex items-center justify-center text-cyber-cyan shadow-[0_0_15px_rgba(0,240,255,0.4)]">
            <Cpu className="w-5 h-5 animate-pulse" />
          </div>
          <span className="absolute -top-1 -right-1 flex h-3 w-3">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-3 w-3 bg-cyan-500"></span>
          </span>
        </div>
        <div>
          <h1 className="text-lg font-bold tracking-wider text-glow bg-gradient-to-r from-cyan-400 via-blue-400 to-purple-400 bg-clip-text text-transparent">
            H.O.L.M.E.V
          </h1>
          <p className="text-[10px] font-mono text-cyan-400/70 tracking-widest uppercase">
            Personal AI OS v1.0.0
          </p>
        </div>
      </div>

      <nav className="flex items-center space-x-1 glass-panel p-1 rounded-xl">
        <button
          onClick={() => setActiveTab("dashboard")}
          className={`flex items-center space-x-2 px-4 py-2 rounded-lg font-mono text-xs transition-all duration-200 ${
            activeTab === "dashboard"
              ? "bg-cyan-500/20 text-cyber-cyan border border-cyan-500/50 shadow-[0_0_12px_rgba(0,240,255,0.3)]"
              : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
          }`}
        >
          <Activity className="w-4 h-4" />
          <span>Dashboard</span>
        </button>

        <button
          onClick={() => setActiveTab("3d")}
          className={`flex items-center space-x-2 px-4 py-2 rounded-lg font-mono text-xs transition-all duration-200 ${
            activeTab === "3d"
              ? "bg-cyan-500/20 text-cyber-cyan border border-cyan-500/50 shadow-[0_0_12px_rgba(0,240,255,0.3)]"
              : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
          }`}
        >
          <Box className="w-4 h-4" />
          <span>3D Workspace</span>
        </button>

        <button
          onClick={() => setActiveTab("circuit")}
          className={`flex items-center space-x-2 px-4 py-2 rounded-lg font-mono text-xs transition-all duration-200 ${
            activeTab === "circuit"
              ? "bg-cyan-500/20 text-cyber-cyan border border-cyan-500/50 shadow-[0_0_12px_rgba(0,240,255,0.3)]"
              : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
          }`}
        >
          <Cpu className="w-4 h-4" />
          <span>Circuit Engine</span>
        </button>

        <button
          onClick={() => setActiveTab("command")}
          className={`flex items-center space-x-2 px-4 py-2 rounded-lg font-mono text-xs transition-all duration-200 ${
            activeTab === "command"
              ? "bg-cyan-500/20 text-cyber-cyan border border-cyan-500/50 shadow-[0_0_12px_rgba(0,240,255,0.3)]"
              : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
          }`}
        >
          <Terminal className="w-4 h-4" />
          <span>Command Center</span>
        </button>
      </nav>

      <div className="flex items-center space-x-4">
        <div className="flex items-center space-x-2 font-mono text-xs px-3 py-1.5 rounded-lg border border-cyan-500/30 bg-cyan-950/30">
          <Mic className={`w-3.5 h-3.5 ${voiceDiag.state === "LISTENING" ? "text-emerald-400 animate-pulse" : "text-slate-400"}`} />
          <span className="text-slate-300">Voice:</span>
          <span className={`font-semibold ${voiceDiag.state === "LISTENING" ? "text-emerald-400" : "text-amber-400"}`}>
            {voiceDiag.state}
          </span>
        </div>

        <div className="flex items-center space-x-2 font-mono text-xs px-3 py-1.5 rounded-lg border border-emerald-500/30 bg-emerald-950/30">
          <Shield className="w-3.5 h-3.5 text-emerald-400" />
          <span className="text-slate-300">System:</span>
          <span className="text-emerald-400 font-semibold uppercase">{health.status}</span>
        </div>
      </div>
    </header>
  );
};
