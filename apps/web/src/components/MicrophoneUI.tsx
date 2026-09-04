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
        recognitionRef.current.stop();
      }
      const recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = false;
      recognition.lang = 'en-US';

      recognition.onresult = async (event: any) => {
        const lastIndex = event.results.length - 1;
        const transcript = event.results[lastIndex][0].transcript.trim();
        if (!transcript) return;

        addMessage({
          id: `msg_user_${Date.now()}`,
          role: 'user',
          content: transcript,
          timestamp: new Date().toLocaleTimeString()
        });

        try {
          const resp = await fetch('/api/v1/voice/speak', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: transcript })
          });
          const data = await resp.json();
          const spoken = data.spoken_response || data.spoken || 'Task executed successfully';

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

      recognition.onerror = (err: any) => {
        console.warn("Speech recognition notice:", err);
      };

      recognition.start();
      recognitionRef.current = recognition;
    } catch (e) {
      console.warn("Speech recognition initialization fallback:", e);
    }
  };

  const stopSpeechRecognition = () => {
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
      startSpeechRecognition();
    } catch (err) {
      console.warn("Microphone access restricted or not connected:", err);
    }
  };

  const stopRealMicrophone = () => {
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

      {/* REAL Microphone Signal Bar Visualizer */}
      <div className="bg-slate-950/60 rounded-xl p-4 border border-slate-800/80 mb-4">
        <div className="flex items-center justify-between text-xs font-mono text-slate-400 mb-2">
          <span>Real Hardware Mic Amplitude Signal</span>
          <span className="text-cyan-400 font-bold">{(micAudioLevel * 100).toFixed(1)}%</span>
        </div>
        <div className="h-3 w-full bg-slate-900 rounded-full overflow-hidden border border-slate-800 flex items-center p-0.5">
          <div
            className="h-full bg-gradient-to-r from-cyan-500 via-emerald-400 to-amber-400 rounded-full transition-all duration-75"
            style={{ width: `${Math.max(2, micAudioLevel * 100)}%` }}
          />
        </div>
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
