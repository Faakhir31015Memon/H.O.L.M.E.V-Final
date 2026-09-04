# H.O.L.M.E.V — Multimodal Personal AI Operating System

Python-first production multimodal personal AI operating system featuring authoritative continuous voice, zero-hardcoded command NLU intent routing, typed Pydantic Tool SDK with Permission Engine, OpenCV vision engine, Three.js 3D workspace, and electrical circuit physics simulator.

## Architecture

- **Backend**: Python 3.10+ FastAPI, Pydantic v2, SQLAlchemy 2.x, Asyncio, WebSockets.
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, Framer Motion, Three.js / React Three Fiber.
- **Voice System**: Authoritative VoiceManager with Barge-in interruption support, VAD, continuous voice loop (`"Holmev chal kaam par lag ja"` / `"Holmev so ja"`).
- **Tool SDK**: Typed Pydantic tools with 5 permission levels (Level 0 Read-Only to Level 4 High Risk).
- **Circuit Simulator**: Python physics engine computing Ohm's Law ($V = I \times R$), current draw, LED emission, short circuit warnings.

## Quick Start

### 1. Start Python Backend
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

### 2. Start React Web Frontend
```bash
cd apps/web
npm install
npm run dev
```

### 3. Run Backend Test Suite
```bash
cd backend
python -m pytest tests
```