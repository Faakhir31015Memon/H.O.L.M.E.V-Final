import React, { useEffect } from 'react';
import { useHolmevStore } from './store/useHolmevStore';
import { Navbar } from './components/Navbar';
import { Dashboard } from './components/Dashboard';
import { ThreeDCanvas } from './components/ThreeDCanvas';
import { CircuitCanvas } from './components/CircuitCanvas';
import { CommandCenter } from './components/CommandCenter';

export const App: React.FC = () => {
  const { activeTab, setHealth } = useHolmevStore();

  useEffect(() => {
    // Fetch initial real backend health telemetry
    const fetchHealth = async () => {
      try {
        const resp = await fetch("/api/health");
        if (resp.ok) {
          const data = await resp.json();
          setHealth(data);
        }
      } catch (e) {
        console.warn("Backend health check fallback");
      }
    };
    fetchHealth();
    const interval = setInterval(fetchHealth, 10000);
    return () => clearInterval(interval);
  }, [setHealth]);

  return (
    <div className="min-h-screen bg-[#05070f] text-slate-100 flex flex-col font-sans overflow-hidden">
      <Navbar />

      <main className="flex-1 p-4 overflow-hidden relative">
        {activeTab === "dashboard" && <Dashboard />}
        {activeTab === "3d" && <ThreeDCanvas />}
        {activeTab === "circuit" && <CircuitCanvas />}
        {activeTab === "command" && <CommandCenter />}
      </main>
    </div>
  );
};

export default App;
