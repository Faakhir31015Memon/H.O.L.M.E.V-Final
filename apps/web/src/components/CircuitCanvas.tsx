import React, { useState } from 'react';
import { useHolmevStore } from '../store/useHolmevStore';
import { Cpu, Zap, Activity, AlertTriangle, Play, RefreshCw } from 'lucide-react';

export const CircuitCanvas: React.FC = () => {
  const { circuitData, setCircuitData } = useHolmevStore();
  const [resistance, setResistance] = useState<number>(330);
  const [voltage, setVoltage] = useState<number>(9);

  const handleSimulateCircuit = async () => {
    try {
      const resp = await fetch("/api/v1/brain/process", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: "Ek LED circuit banao" })
      });
      const data = await resp.json();
      if (data?.result?.data) {
        setCircuitData(data.result.data);
      }
    } catch (e) {
      // Local physics fallback
      const vNet = Math.max(0, voltage - 2.0);
      const currentMa = (vNet / resistance) * 1000;
      setCircuitData({
        components: [],
        connections: [],
        simulation: {
          status: "NORMAL_OPERATION",
          voltage_v: voltage,
          current_ma: Number(currentMa.toFixed(2)),
          resistance_ohm: resistance,
          led_illuminated: currentMa >= 5.0 && currentMa <= 30.0
        }
      });
    }
  };

  const sim = circuitData?.simulation || {
    status: "NORMAL_OPERATION",
    current_ma: 21.2,
    voltage_v: 9.0,
    resistance_ohm: 330.0,
    led_illuminated: true
  };

  return (
    <div className="glass-panel rounded-2xl p-6 h-[calc(100vh-8rem)] flex flex-col border border-cyber-border">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-bold font-mono text-cyan-400 text-glow flex items-center gap-2">
            <Cpu className="w-5 h-5 text-cyan-400" />
            Electrical Circuit Physics Simulator
          </h2>
          <p className="text-xs text-slate-400 font-mono">
            Python Physics Engine & Circuit Graph Simulation
          </p>
        </div>

        <button
          onClick={handleSimulateCircuit}
          className="flex items-center space-x-2 px-4 py-2 rounded-xl bg-cyan-500/20 text-cyan-400 border border-cyan-500/50 hover:bg-cyan-500/30 text-xs font-mono transition-all shadow-[0_0_15px_rgba(0,240,255,0.25)]"
        >
          <Play className="w-4 h-4 fill-cyan-400" />
          <span>Execute Simulation</span>
        </button>
      </div>

      {/* Physics Metric Telemetry Cards */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-slate-900/60 p-4 rounded-xl border border-slate-800">
          <div className="flex items-center justify-between text-xs text-slate-400 font-mono mb-1">
            <span>VOLTAGE (V)</span>
            <Zap className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-amber-400">
            {sim.voltage_v} V
          </div>
        </div>

        <div className="bg-slate-900/60 p-4 rounded-xl border border-slate-800">
          <div className="flex items-center justify-between text-xs text-slate-400 font-mono mb-1">
            <span>RESISTANCE (Ω)</span>
            <Activity className="w-4 h-4 text-blue-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-blue-400">
            {sim.resistance_ohm} Ω
          </div>
        </div>

        <div className="bg-slate-900/60 p-4 rounded-xl border border-slate-800">
          <div className="flex items-center justify-between text-xs text-slate-400 font-mono mb-1">
            <span>CURRENT DRAW (mA)</span>
            <Zap className="w-4 h-4 text-cyan-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-cyan-400">
            {sim.current_ma} mA
          </div>
        </div>

        <div className="bg-slate-900/60 p-4 rounded-xl border border-slate-800">
          <div className="flex items-center justify-between text-xs text-slate-400 font-mono mb-1">
            <span>LED EMISSION STATE</span>
            <div className={`w-3 h-3 rounded-full ${sim.led_illuminated ? "bg-emerald-400 shadow-[0_0_12px_#10b981]" : "bg-slate-600"}`} />
          </div>
          <div className={`text-xl font-bold font-mono ${sim.led_illuminated ? "text-emerald-400" : "text-slate-500"}`}>
            {sim.led_illuminated ? "ILLUMINATED (ON)" : "OFF"}
          </div>
        </div>
      </div>

      {/* Visual Circuit Diagram Canvas */}
      <div className="flex-1 bg-slate-950/80 rounded-xl border border-slate-800 p-8 flex items-center justify-center relative overflow-hidden">
        <div className="relative w-full max-w-2xl h-64 border-2 border-dashed border-cyan-500/30 rounded-2xl flex items-center justify-around p-6">
          {/* Component: Battery */}
          <div className="flex flex-col items-center">
            <div className="w-16 h-24 bg-gradient-to-b from-amber-500 to-amber-700 rounded-lg border border-amber-300 flex flex-col items-center justify-between p-2 shadow-lg">
              <span className="text-[10px] font-mono text-black font-bold">9V BAT</span>
              <div className="text-xs font-mono font-bold text-white">+</div>
              <div className="text-xs font-mono font-bold text-white">-</div>
            </div>
            <span className="text-xs font-mono text-slate-400 mt-2">Power Source</span>
          </div>

          {/* Wire 1 */}
          <div className="flex-1 h-1 bg-gradient-to-r from-amber-400 to-blue-400 relative">
            <div className="absolute -top-3 left-1/2 -translate-x-1/2 text-[10px] font-mono text-cyan-400">
              {sim.current_ma} mA
            </div>
          </div>

          {/* Component: Resistor */}
          <div className="flex flex-col items-center">
            <div className="w-20 h-10 bg-slate-800 border border-blue-400 rounded-md flex items-center justify-center space-x-1 px-1">
              <div className="w-2 h-full bg-amber-500" />
              <div className="w-2 h-full bg-blue-500" />
              <div className="w-2 h-full bg-red-500" />
              <div className="w-2 h-full bg-amber-400" />
            </div>
            <span className="text-xs font-mono text-slate-400 mt-2">{sim.resistance_ohm} Ω Resistor</span>
          </div>

          {/* Wire 2 */}
          <div className="flex-1 h-1 bg-gradient-to-r from-blue-400 to-emerald-400" />

          {/* Component: LED */}
          <div className="flex flex-col items-center">
            <div className={`w-14 h-14 rounded-full border-2 flex items-center justify-center transition-all duration-300 ${
              sim.led_illuminated
                ? "bg-red-500 border-red-400 shadow-[0_0_30px_#ef4444] animate-pulse text-white"
                : "bg-slate-800 border-slate-600 text-slate-500"
            }`}>
              <Zap className="w-7 h-7" />
            </div>
            <span className="text-xs font-mono text-slate-400 mt-2">Red LED</span>
          </div>
        </div>
      </div>
    </div>
  );
};
