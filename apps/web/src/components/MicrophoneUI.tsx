import React, { useState, useEffect, useRef } from 'react';
import { useHolmevStore } from '../store/useHolmevStore';
import { Mic, MicOff, Radio } from 'lucide-react';

export const speakSpeechUtterance = (text: string) => {
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel(); // Barge-in cancellation
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    window.speechSynthesis.speak(utterance);
  }
};

export const MicrophoneUI: React.FC = () => {
  const { voiceDiag, setVoiceDiag, micAudioLevel, setMicAudioLevel, addMessage } = useHolmevStore();
  const [isListening, setIsListening] = useState<boolean>(false);
  const [lastHeard, setLastHeard] = useState<string>("");
  const [sttLang, setSttLang] = useState<string>("hi-IN");
  const isListeningRef = useRef<boolean>(false);
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const recognitionRef = useRef<any>(null);

  // Speech Recognition setup (STT)
  const startSpeechRecognition = () => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    try {
      if (recognitionRef.current) {
        try { recognitionRef.current.stop(); } catch(e) {}
      }
      const recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = false;
      recognition.lang = sttLang;

      recognition.onresult = async (event: any) => {
        const lastIndex = event.results.length - 1;
        const transcript = event.results[lastIndex][0].transcript.trim();
        if (!transcript) return;

        setLastHeard(transcript);
        await sendVoiceCommand(transcript);
      };

      recognition.onerror = (err: any) => {
        console.warn("Speech recognition notice:", err);
        if (err.error === 'not-allowed' || err.error === 'service-not-allowed') {
          setVoiceDiag({
            ...voiceDiag,
            microphone_status: "BLOCKED (Click button to grant mic permission)"
          });
        }
      };

      recognition.onend = () => {
        if (isListeningRef.current) {
          try {
            recognition.start();
          } catch (e) {}
        }
      };

      recognition.start();
      recognitionRef.current = recognition;
    } catch (e) {
      console.warn("Speech recognition initialization fallback:", e);
    }
  };

  const sendVoiceCommand = async (text: string) => {
    addMessage({
      id: `msg_user_${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: new Date().toLocaleTimeString()
    });

    try {
      const resp = await fetch('/api/v1/voice/speak', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text })
      });
      const data = await resp.json();
      const spoken = data.spoken_response || data.spoken || 'Task executed successfully';

      if (data.state) {
        setVoiceDiag({
          ...voiceDiag,
          state: data.state,
          microphone_status: data.state === "DEACTIVATED" ? "IDLE" : "CONNECTED",
          active_audio_sessions: data.state === "DEACTIVATED" ? 0 : 1
        });
      }

      addMessage({
        id: `msg_ai_${Date.now()}`,
        role: 'assistant',
        content: spoken,
        tool_name: data.tool,
        timestamp: new Date().toLocaleTimeString()
      });

      // Audible TTS Speech Output
      speakSpeechUtterance(spoken);
    } catch (e) {
      console.error("Speech processing error:", e);
    }
  };

  const stopSpeechRecognition = () => {
    isListeningRef.current = false;
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch (e) {}
      recognitionRef.current = null;
    }
  };

  // Initialize real web microphone audio stream analyzer
  const startRealMicrophone = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      mediaStreamRef.current = stream;

      const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
      audioContextRef.current = audioCtx;

      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);

      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);

      const updateAudioMeter = () => {
        analyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < bufferLength; i++) {
          sum += dataArray[i];
        }
        const average = sum / bufferLength;
        const normalized = Math.min(1.0, average / 128.0);
        setMicAudioLevel(normalized);

        animFrameRef.current = requestAnimationFrame(updateAudioMeter);
      };

      updateAudioMeter();
      setIsListening(true);
      isListeningRef.current = true;
      startSpeechRecognition();
    } catch (err) {
      console.warn("Microphone access restricted or not connected:", err);
    }
  };

  const stopRealMicrophone = () => {
    isListeningRef.current = false;
    if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
    }
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      try {
        audioContextRef.current.close();
      } catch (e) {}
    }
    audioContextRef.current = null;
    stopSpeechRecognition();
    setIsListening(false);
    setMicAudioLevel(0);
  };

  const toggleContinuousVoice = async () => {
    if (voiceDiag.state === "LISTENING" || voiceDiag.state === "SPEAKING") {
      // Deactivate
      try {
        await fetch("/api/v1/voice/deactivate", { method: "POST" });
        stopRealMicrophone();
        setVoiceDiag({
          ...voiceDiag,
          state: "DEACTIVATED",
          microphone_status: "IDLE",
          active_audio_sessions: 0
        });
        const msg = "Continuous Voice session DEACTIVATED (Holmev so ja).";
        addMessage({
          id: `msg_${Date.now()}`,
          role: "system",
          content: msg,
          timestamp: new Date().toLocaleTimeString()
        });
        speakSpeechUtterance(msg);
      } catch (e) {
        console.error(e);
      }
    } else {
      // Activate
      try {
        await startRealMicrophone();
        await fetch("/api/v1/voice/activate", { method: "POST" });
        setVoiceDiag({
          ...voiceDiag,
          state: "LISTENING",
          microphone_status: "CONNECTED",
          active_audio_sessions: 1
        });
        const msg = "Continuous Voice session ACTIVATED. Kya hukum hai Boss?";
        addMessage({
          id: `msg_${Date.now()}`,
          role: "system",
          content: msg,
          timestamp: new Date().toLocaleTimeString()
        });
        speakSpeechUtterance(msg);
      } catch (e) {
        console.error(e);
      }
    }
  };

  useEffect(() => {
    // Automatically enable mic on program run / page load
    startRealMicrophone();

    return () => {
      stopRealMicrophone();
    };
  }, []);

  return (
    <div className="glass-panel rounded-2xl p-6 relative overflow-hidden border border-cyber-border">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center space-x-3">
          <div className={`p-2.5 rounded-xl ${isListening ? "bg-emerald-500/20 border border-emerald-500/50 text-emerald-400" : "bg-slate-800 text-slate-400"}`}>
            <Radio className={`w-5 h-5 ${isListening ? "animate-pulse" : ""}`} />
          </div>
          <div>
            <h2 className="text-base font-bold text-slate-100 font-mono tracking-wide">
              Authoritative Voice Core
            </h2>
            <p className="text-xs text-slate-400 font-mono">
              Signal Processing & VAD Pipeline
            </p>
          </div>
        </div>

        <button
          onClick={toggleContinuousVoice}
          className={`flex items-center space-x-2 px-5 py-2.5 rounded-xl font-mono text-xs font-semibold transition-all duration-300 ${
            voiceDiag.state === "LISTENING" || voiceDiag.state === "SPEAKING"
              ? "bg-gradient-to-r from-red-500 to-rose-600 text-white shadow-[0_0_20px_rgba(239,68,68,0.4)] hover:opacity-90"
              : "bg-gradient-to-r from-cyan-500 to-blue-600 text-black shadow-[0_0_20px_rgba(0,240,255,0.4)] hover:opacity-90"
          }`}
        >
          {voiceDiag.state === "LISTENING" || voiceDiag.state === "SPEAKING" ? (
            <>
              <MicOff className="w-4 h-4" />
              <span>Deactivate Voice ("Holmev so ja")</span>
            </>
          ) : (
            <>
              <Mic className="w-4 h-4" />
              <span>Activate Voice ("Holmev chal kaam par lag ja")</span>
            </>
          )}
        </button>
      </div>

      {/* Live Mic Speech Heard Display */}
      <div className="bg-slate-950/80 rounded-xl p-3 border border-cyan-500/30 mb-3 flex items-center justify-between text-xs font-mono">
        <div className="flex items-center space-x-2 overflow-hidden mr-2">
          <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping shrink-0" />
          <span className="text-slate-400 shrink-0">Speech Heard:</span>
          <span className="text-cyan-300 font-bold tracking-wide truncate">
            {lastHeard || 'Listening... Speak "Notepad kholo" or "Holmev chal kaam par lag ja"'}
          </span>
        </div>
        <select
          value={sttLang}
          onChange={(e) => {
            const newLang = e.target.value;
            setSttLang(newLang);
            if (isListeningRef.current) {
              stopSpeechRecognition();
              setTimeout(() => startSpeechRecognition(), 150);
            }
          }}
          className="bg-slate-900 border border-slate-700 text-slate-200 text-[10px] rounded-lg px-2 py-1 focus:outline-none shrink-0"
        >
          <option value="hi-IN">Hinglish / Hindi (hi-IN)</option>
          <option value="en-IN">English India (en-IN)</option>
          <option value="en-US">English US (en-US)</option>
        </select>
      </div>

      {/* Quick Voice Command Chips */}
      <div className="flex items-center space-x-2 mb-4 overflow-x-auto text-[11px] font-mono text-slate-300">
        <span className="text-slate-500 shrink-0">Quick Actions:</span>
        <button
          onClick={() => { setLastHeard("notepad kholo"); sendVoiceCommand("notepad kholo"); }}
          className="bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/30 text-cyan-300 px-3 py-1 rounded-lg shrink-0 transition-all"
        >
          🚀 Notepad Kholo
        </button>
        <button
          onClick={() => { setLastHeard("chrome kholo"); sendVoiceCommand("chrome kholo"); }}
          className="bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/30 text-cyan-300 px-3 py-1 rounded-lg shrink-0 transition-all"
        >
          🌐 Chrome Kholo
        </button>
        <button
          onClick={() => { setLastHeard("calculator kholo"); sendVoiceCommand("calculator kholo"); }}
          className="bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/30 text-cyan-300 px-3 py-1 rounded-lg shrink-0 transition-all"
        >
          🧮 Calculator Kholo
        </button>
        <button
          onClick={() => { setLastHeard("Holmev chal kaam par lag ja"); sendVoiceCommand("Holmev chal kaam par lag ja"); }}
          className="bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 text-emerald-300 px-3 py-1 rounded-lg shrink-0 transition-all"
        >
          ⚡ Activate
        </button>
      </div>

      {/* Telemetry Status Grid */}
      <div className="grid grid-cols-4 gap-3 text-xs font-mono">
        <div className="bg-slate-900/50 p-2.5 rounded-lg border border-slate-800">
          <span className="text-slate-400 block text-[10px]">STATE</span>
          <span className="text-cyan-400 font-bold">{voiceDiag.state}</span>
        </div>
        <div className="bg-slate-900/50 p-2.5 rounded-lg border border-slate-800">
          <span className="text-slate-400 block text-[10px]">VAD STATUS</span>
          <span className={micAudioLevel > 0.1 ? "text-emerald-400 font-bold" : "text-slate-400 font-bold"}>
            {micAudioLevel > 0.1 ? "SPEECH DETECTED" : "SILENT"}
          </span>
        </div>
        <div className="bg-slate-900/50 p-2.5 rounded-lg border border-slate-800">
          <span className="text-slate-400 block text-[10px]">AUDIO SESSIONS</span>
          <span className="text-purple-400 font-bold">{voiceDiag.active_audio_sessions} / 1 MAX</span>
        </div>
        <div className="bg-slate-900/50 p-2.5 rounded-lg border border-slate-800">
          <span className="text-slate-400 block text-[10px]">BARGE-IN READY</span>
          <span className="text-emerald-400 font-bold">ACTIVE</span>
        </div>
      </div>
    </div>
  );
};
