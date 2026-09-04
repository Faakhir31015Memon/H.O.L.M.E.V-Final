import { create } from 'zustand';
import { VoiceDiagnostics, SystemHealth, MessageItem, ThreeDObject, CircuitData } from '../types';

interface HolmevState {
  voiceDiag: VoiceDiagnostics;
  health: SystemHealth;
  messages: MessageItem[];
  threeDObjects: ThreeDObject[];
  circuitData: CircuitData | null;
  activeTab: "dashboard" | "3d" | "circuit" | "command";
  micAudioLevel: number;
  
  setVoiceDiag: (diag: VoiceDiagnostics) => void;
  setHealth: (health: SystemHealth) => void;
  addMessage: (msg: MessageItem) => void;
  setThreeDObjects: (objs: ThreeDObject[]) => void;
  addThreeDObject: (obj: ThreeDObject) => void;
  setCircuitData: (data: CircuitData) => void;
  setActiveTab: (tab: "dashboard" | "3d" | "circuit" | "command") => void;
  setMicAudioLevel: (level: number) => void;
}

export const useHolmevStore = create<HolmevState>((set) => ({
  voiceDiag: {
    state: "DEACTIVATED",
    microphone_status: "IDLE",
    input_level: 0,
    vad_active: false,
    stt_connected: true,
    tts_playing: false,
    active_audio_sessions: 0
  },
  health: {
    status: "healthy",
    services: {
      database: "online",
      redis: "online",
      ai: "online",
      voice: "online",
      vision: "offline",
      desktop_agent: "online"
    }
  },
  messages: [
    {
      id: "msg_init",
      role: "assistant",
      content: "H.O.L.M.E.V System Ready, Boss. Continuous Voice interaction is online.",
      timestamp: new Date().toLocaleTimeString()
    }
  ],
  threeDObjects: [
    {
      id: "obj_prime",
      type: "cube",
      position: [0, 0, 0],
      rotation: [0, 0, 0],
      scale: [1, 1, 1],
      color: "#00f0ff"
    }
  ],
  circuitData: {
    components: [],
    connections: [],
    simulation: {
      status: "NORMAL_OPERATION",
      current_ma: 21.2,
      voltage_v: 9.0,
      resistance_ohm: 330.0,
      led_illuminated: true
    }
  },
  activeTab: "dashboard",
  micAudioLevel: 0,

  setVoiceDiag: (diag) => set({ voiceDiag: diag }),
  setHealth: (health) => set({ health }),
  addMessage: (msg) => set((state) => ({ messages: [...state.messages, msg] })),
  setThreeDObjects: (objs) => set({ threeDObjects: objs }),
  addThreeDObject: (obj) => set((state) => ({ threeDObjects: [...state.threeDObjects, obj] })),
  setCircuitData: (data) => set({ circuitData: data }),
  setActiveTab: (tab) => set({ activeTab: tab }),
  setMicAudioLevel: (level) => set({ micAudioLevel: level })
}));
