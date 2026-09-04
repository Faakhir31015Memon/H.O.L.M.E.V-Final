import React, { useState } from 'react';
import { useHolmevStore } from '../store/useHolmevStore';
import { MicrophoneUI } from './MicrophoneUI';
import { Bot, Send, User, Sparkles, Lightbulb, Fan, Tv, Video, ShieldCheck } from 'lucide-react';

export const Dashboard: React.FC = () => {
  const { messages, addMessage, voiceDiag } = useHolmevStore();
  const [inputText, setInputText] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);

  const handleSendText = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputText.trim() || isProcessing) return;

    const userQuery = inputText.trim();
    setInputText("");

    addMessage({
      id: `msg_user_${Date.now()}`,
      role: "user",
      content: userQuery,
      timestamp: new Date().toLocaleTimeString()
    });

    setIsProcessing(true);

    try {
      const resp = await fetch("/api/v1/brain/process", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: userQuery })
      });
      const data = await resp.json();

      addMessage({
        id: `msg_ai_${Date.now()}`,
        role: "assistant",
        content: data.spoken_response || "Task executed successfully.",
        tool_name: data.tool,
        timestamp: new Date().toLocaleTimeString()
      });
    } catch (err) {
      addMessage({
        id: `msg_err_${Date.now()}`,
        role: "assistant",
        content: "Boss, request execution error occurred.",
        timestamp: new Date().toLocaleTimeString()
      });
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="h-[calc(100vh-5rem)] grid grid-cols-12 gap-6 p-2 overflow-hidden">
      {/* Left Column: Voice Core + Conversation History */}
      <div className="col-span-7 flex flex-col space-y-6 overflow-hidden">
        {/* Authoritative Microphone Voice Core */}
        <MicrophoneUI />

        {/* Real-time Assistant Conversation Feed */}
        <div className="glass-panel rounded-2xl p-5 flex-1 flex flex-col overflow-hidden border border-cyber-border">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800/80 mb-3">
            <div className="flex items-center space-x-2">
              <Bot className="w-4 h-4 text-cyan-400" />
              <h3 className="text-xs font-mono font-bold text-slate-200 uppercase tracking-wider">
                Multimodal Interaction Feed
              </h3>
            </div>
            <span className="text-[10px] font-mono text-cyan-400/70">LIVE STREAM</span>
          </div>

          <div className="flex-1 overflow-y-auto space-y-4 pr-1">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex space-x-3 text-xs ${
                  msg.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                {msg.role !== "user" && (
                  <div className="w-8 h-8 rounded-xl bg-cyan-500/20 border border-cyan-500/50 flex items-center justify-center text-cyan-400 shrink-0 mt-0.5">
                    <Sparkles className="w-4 h-4" />
                  </div>
                )}

                <div
                  className={`max-w-[80%] rounded-2xl p-3.5 font-sans ${
                    msg.role === "user"
                      ? "bg-gradient-to-r from-cyan-600 to-blue-600 text-white shadow-[0_0_15px_rgba(0,240,255,0.25)]"
                      : msg.role === "system"
                      ? "bg-slate-900/80 text-amber-300 border border-amber-500/30 font-mono text-[11px]"
                      : "bg-slate-900/90 text-slate-100 border border-slate-800"
                  }`}
                >
                  <p className="leading-relaxed">{msg.content}</p>
                  {msg.tool_name && (
                    <div className="mt-2 pt-1.5 border-t border-slate-800 text-[10px] font-mono text-cyan-400 flex items-center gap-1">
                      <ShieldCheck className="w-3 h-3 text-cyan-400" />
                      <span>Verified Action Tool: {msg.tool_name}</span>
                    </div>
                  )}
                  <span className="text-[9px] opacity-60 font-mono block mt-1 text-right">
                    {msg.timestamp}
                  </span>
                </div>

                {msg.role === "user" && (
                  <div className="w-8 h-8 rounded-xl bg-blue-500/20 border border-blue-500/50 flex items-center justify-center text-blue-400 shrink-0 mt-0.5">
                    <User className="w-4 h-4" />
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Quick Voice / Text Input Bar */}
          <form onSubmit={handleSendText} className="mt-3 flex items-center space-x-2 pt-2 border-t border-slate-800">
            <input
              type="text"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder="Speak command or type natural query..."
              className="flex-1 bg-slate-950/80 border border-slate-800 rounded-xl px-4 py-2.5 text-xs text-slate-100 font-sans focus:outline-none focus:border-cyan-500/80 transition-all placeholder:text-slate-500"
            />
            <button
              type="submit"
              disabled={isProcessing || !inputText.trim()}
              className="p-2.5 rounded-xl bg-cyan-500/20 border border-cyan-500/50 text-cyan-400 hover:bg-cyan-500/30 disabled:opacity-50 transition-all shadow-[0_0_15px_rgba(0,240,255,0.25)]"
            >
              <Send className="w-4 h-4" />
            </button>
          </form>
        </div>
      </div>

      {/* Right Column: Smart Home Devices & Camera View */}
      <div className="col-span-5 flex flex-col space-y-6 overflow-hidden">
        {/* Smart Home Devices Quick Status Card */}
        <div className="glass-panel rounded-2xl p-5 border border-cyber-border">
          <h3 className="text-xs font-mono font-bold text-slate-200 uppercase tracking-wider mb-3 flex items-center gap-2">
            <Lightbulb className="w-4 h-4 text-amber-400" />
            Registered Smart Home Devices
          </h3>

          <div className="grid grid-cols-2 gap-3 text-xs font-mono">
            <div className="bg-slate-900/60 p-3 rounded-xl border border-slate-800 flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <Fan className="w-4 h-4 text-cyan-400 animate-spin" />
                <span>Bedroom Fan</span>
              </div>
              <span className="text-emerald-400 font-bold">SPEED 2 (ON)</span>
            </div>

            <div className="bg-slate-900/60 p-3 rounded-xl border border-slate-800 flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <Lightbulb className="w-4 h-4 text-amber-400" />
                <span>Bedroom Light</span>
              </div>
              <span className="text-emerald-400 font-bold">ON</span>
            </div>

            <div className="bg-slate-900/60 p-3 rounded-xl border border-slate-800 flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <Fan className="w-4 h-4 text-slate-500" />
                <span>Hall Fan</span>
              </div>
              <span className="text-slate-500 font-bold">OFF</span>
            </div>

            <div className="bg-slate-900/60 p-3 rounded-xl border border-slate-800 flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <Tv className="w-4 h-4 text-purple-400" />
                <span>Bedroom AC</span>
              </div>
              <span className="text-cyan-400 font-bold">24°C</span>
            </div>
          </div>
        </div>

        {/* Live Camera & Vision Feed */}
        <div className="glass-panel rounded-2xl p-5 flex-1 flex flex-col border border-cyber-border overflow-hidden">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center space-x-2">
              <Video className="w-4 h-4 text-cyan-400" />
              <h3 className="text-xs font-mono font-bold text-slate-200 uppercase tracking-wider">
                Bedroom Camera Feed
              </h3>
            </div>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-500/20 text-emerald-400 border border-emerald-500/40">
              ONLINE
            </span>
          </div>

          <div className="flex-1 bg-slate-950/80 rounded-xl border border-slate-800 flex items-center justify-center relative overflow-hidden">
            <div className="text-center p-6">
              <div className="w-16 h-16 rounded-full bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400 mx-auto mb-3">
                <Video className="w-8 h-8 animate-pulse" />
              </div>
              <p className="text-xs font-mono text-slate-300">
                Camera Stream #1 — Bedroom
              </p>
              <p className="text-[10px] font-mono text-slate-500 mt-1">
                OpenCV Face & Hand Landmark Tracking Active
              </p>
            </div>

            {/* Bounding box overlay demo indicator */}
            <div className="absolute top-4 left-4 border border-cyan-400/60 bg-cyan-500/10 text-cyan-300 px-2 py-1 text-[9px] font-mono rounded">
              FACE_DETECTED [0.92]
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
