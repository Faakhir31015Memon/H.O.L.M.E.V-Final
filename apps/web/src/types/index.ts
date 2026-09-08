export type VoiceState = 
  | "DEACTIVATED"
  | "IDLE"
  | "ACTIVATING"
  | "LISTENING"
  | "THINKING"
  | "EXECUTING"
  | "SPEAKING"
  | "INTERRUPTED"
  | "ERROR"
  | "DEACTIVATING";

export interface VoiceDiagnostics {
  state: VoiceState;
  microphone_status: string;
  input_level: number;
  vad_active: boolean;
  stt_connected: boolean;
  tts_playing: boolean;
  active_audio_sessions: number;
}

export interface SystemHealth {
  status: string;
  services: {
    database: string;
    redis: string;
    ai: string;
    voice: string;
    vision: string;
    desktop_agent: string;
  };
}

export interface MessageItem {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  tool_name?: string;
  timestamp: string;
}

export interface ThreeDObject {
  id: string;
  type: string;
  position: [number, number, number];
  rotation: [number, number, number];
  scale: [number, number, number];
  color: string;
  wireframe?: boolean;
}

export interface CircuitData {
  components: any[];
  connections: any[];
  simulation: {
    status: string;
    current_ma: number;
    voltage_v: number;
    resistance_ohm: number;
    led_illuminated: boolean;
    error?: string;
  };
}
