import React, { useState } from 'react';
import { useHolmevStore } from '../store/useHolmevStore';
import { Cpu, Zap, Activity, Trash2, Plus, Play } from 'lucide-react';

export const CircuitCanvas: React.FC = () => {
  const { circuitData, setCircuitData } = useHolmevStore();
  const [resistance, setResistance] = useState<number>(330);
  const [voltage, setVoltage] = useState<number>(9);
  const [componentsList, setComponentsList] = useState<string[]>(["9V Battery", "330Ω Resistor", "Red LED", "Custom IR Module"]);

  const handleRemoveComponent = (index: number) => {
    setComponentsList(prev => prev.filter((_, i) => i !== index));
  };

  const handleAddComponent = () => {
    setComponentsList(prev => [...prev, `Module #${prev.length + 1}`]);
  };

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
    <div className="glass-panel rounded-2xl p-6 h-[calc(100vh-8rem)] flex flex-col border border-cyber-border relative overflow-hidden">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-bold font-mono text-cyan-400 text-glow flex items-center gap-2">
            <Cpu className="w-5 h-5 text-cyan-400" />
            3D Circuit & Holographic Modular Builder
          </h2>
          <p className="text-xs text-slate-400 font-mono">
            Hand Gesture Pinning & Trash Throw Deletion Workspace
          </p>
        </div>

        <div className="flex items-center space-x-3">
          <button
            onClick={handleAddComponent}
            className="flex items-center space-x-2 px-3 py-2 rounded-xl bg-purple-500/20 text-purple-300 border border-purple-500/40 hover:bg-purple-500/30 text-xs font-mono transition-all"
          >
            <Plus className="w-4 h-4" />
            <span>Add Module</span>
          </button>

          <button
            onClick={handleSimulateCircuit}
            className="flex items-center space-x-2 px-4 py-2 rounded-xl bg-cyan-500/20 text-cyan-400 border border-cyan-500/50 hover:bg-cyan-500/30 text-xs font-mono transition-all shadow-[0_0_15px_rgba(0,240,255,0.25)]"
          >
            <Play className="w-4 h-4 fill-cyan-400" />
            <span>Execute Simulation</span>
          </button>
        </div>
      </div>

      {/* Physics Metric Telemetry Cards */}
      <div className="grid grid-cols-4 gap-4 mb-4">
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

      {/* Visual Circuit Diagram Canvas with Trash Drop Zone */}
      <div className="flex-1 bg-slate-950/80 rounded-xl border border-slate-800 p-6 flex flex-col justify-between relative overflow-hidden">
        <div className="flex items-center justify-between text-[11px] font-mono text-cyan-400 mb-2">
          <span>AIR GESTURE BOARD — PINCH TO HOLD, SWIPE TO TRASH BIN</span>
          <span className="text-purple-400">MODULAR ADDITION MODE</span>
        </div>

        <div className="flex-1 border-2 border-dashed border-cyan-500/30 rounded-2xl flex items-center justify-around p-4 relative">
          {componentsList.map((comp, idx) => (
            <div key={idx} className="flex flex-col items-center group relative">
              <div className="w-20 h-20 bg-slate-900/90 border border-cyan-500/50 rounded-xl flex items-center justify-center p-2 text-cyan-300 font-mono text-xs text-center shadow-lg group-hover:border-rose-500 transition-all cursor-grab">
                {comp}
              </div>
              <button
                onClick={() => handleRemoveComponent(idx)}
                className="mt-1 text-[10px] text-rose-400 hover:text-rose-300 font-mono flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <Trash2 className="w-3 h-3" /> Throw
              </button>
            </div>
          ))}
        </div>

        {/* Hand Gesture Trash Bin Drop Area */}
        <div className="mt-4 p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl flex items-center justify-between text-xs font-mono text-rose-400">
          <div className="flex items-center space-x-2">
            <Trash2 className="w-5 h-5 text-rose-400 animate-bounce" />
            <span>GESTURE DUSTBIN: Hold component and swipe towards bottom right to delete object</span>
          </div>
          <span className="text-[10px] text-rose-300/70 uppercase">TRASH_THROW ACTIVE</span>
        </div>
      </div>
    </div>
  );
};
