# H.O.L.M.E.V — local-first personal AI operating system

A FastAPI brain that turns a sentence into an understanding, a plan over registered
tools, execution behind single-use approvals, and verification against the
filesystem or device state — then answers with what it can actually prove.

The rule this codebase is built around: **if a capability needs hardware or a
service that is not configured, the brain refuses and names the missing setting. It
never reports an action it did not perform.** `GET /api/v1/brain/status` tells you
which capabilities exist on this machine right now, and
`GET /api/v1/brain/audit` shows what really ran.

## What is here

| Area | State on a default install |
| --- | --- |
| Model routing (Ollama local, deterministic, explainable) | Runs for real once Ollama is serving a model; degrades and says so when it is not |
| Understanding → Planning → Execution → Verification → Response | Implemented and covered by the test suite |
| Approvals, audit log, path guard, emergency stop, undo | Implemented and covered by tests |
| Persistent 4-layer memory with user confirm/reject | Implemented |
| 3D scene, OBJ/STL export | Real geometry and real files written inside the workspace |
| Email over SMTP | Really sends once `SMTP_*` is filled; refuses before that |
| Routing / navigation | Really queries OSRM + Nominatim once `OSRM_BASE_URL` is set; refuses with the docker command to run |
| Smart home devices | State tracked honestly; no appliance moves until `HOME_DEVICE_MODE` and MQTT/ESP32 exist |
| IR emitter, camera feeds, phone bridge, keyboard automation, power actions | Wired, and refuse until the matching `.env` setting or device exists |
| Voice STT / TTS | TTS uses the OS voices present on the machine; STT needs `faster-whisper` + `sounddevice` |

`GET /api/v1/brain/status` returns `capabilities` — a boolean per row above, read
from live configuration, so you can check this table against your own machine
instead of trusting it.

## Quick start (Windows PowerShell)

```powershell
cd C:\Users\mymns\OneDrive\Desktop\H.O.L.M.E.V-Final\backend

# 1. virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# 2. local model — this is the brain's default provider
#    (https://ollama.com/download, then:)
ollama pull qwen2.5:3b
ollama list          # must show qwen2.5:3b before the next step means anything

# 3. configuration
Copy-Item ..\.env.example .env       # then open backend\.env

# 4. run
uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000/docs. Two endpoints answer "what is real here":

```powershell
curl.exe http://127.0.0.1:8000/api/v1/brain/status
curl.exe http://127.0.0.1:8000/health
```

`/health` probes the database and asks the providers which models actually
respond; it does not assert them.

### Tests and lint

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m pytest -q          # 227 passed, 1 skipped (that 1 is a POSIX symlink test, no-op on Windows)
python -m ruff check app tests
```

## Optional capabilities

Install only what you want switched on — each one changes a `capabilities` flag in
`/api/v1/brain/status` from false to true.

```powershell
# speech recognition (mic capture stays off until you call /api/v1/voice/listen/capture)
pip install faster-whisper sounddevice numpy

# real map + geocoding for navigation (needs an .osrm extract for your region)
docker run -d -p 5000:5000 -v ${PWD}\maps:/data orosm/osrm-backend osrm-routed --algorithm mli /data/region.osrm
# then set OSRM_BASE_URL=http://127.0.0.1:5000 in backend\.env
```

- **Email** — set `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_ADDRESS`.
  Use an app password, not your account password.
- **Phone actions** (WhatsApp, dialling, gallery) — need a companion HTTP bridge
  running on the phone; set `MOBILE_BRIDGE_URL`. There is no free public API for
  these, and this project will not pretend otherwise.
- **Cameras** — set `CAMERAS` as JSON, then `POST /api/v1/brain/cameras/probe`. Only
  that probe can mark a feed `ONLINE`; nothing probes on voice request.
- **Power actions** (shutdown / restart / lock) — refused until you set
  `ALLOW_SYSTEM_POWER_ACTIONS=true`. A model should not be able to close your work.

## Using a hosted model instead of Ollama

Off by default, and it stays off unless you turn it on yourself:
`PRIVACY_LEVEL` must leave `local_only`, `BRAIN_ALLOW_EXTERNAL=true`, and a key in
`OPENAI_API_KEY`. Sign up on the provider's own site and paste **your own** key —
this repo will not go looking for shared or scraped keys, because that trades your
machine and your account for something free. Fill `EXTERNAL_COST_PER_1K_*_USD` with
the provider's published price; `0.0` is reported as "not configured", never as free.

## Security model, in one place

- **Approvals** — a tool at or above `APPROVAL_MIN_LEVEL` (default 2) parks the run
  until you decide. A grant is single-use and bound to a hash of the exact
  parameters you were shown; changing the parameters needs a new yes.
- **Path guard** — every file operation resolves inside `WORKSPACE_ROOT`; `..` and
  absolute escapes are refused and audited.
- **Undo** — before a file or device action runs, the pre-image is captured. Three
  real reversal kinds exist (`created`, `deleted`, `device`); anything else is
  recorded as not reversible, and says so instead of promising a restore.
  `GET/POST /api/v1/brain/undo` drives it.
- **Emergency stop** — `POST /api/v1/brain/stop` needs no token on purpose: it
  cancels live runs and voids pending approvals.
- **Audit** — append-only, redacted, queryable per run/tool/outcome.
- **Token** — `API_TOKEN` empty means loopback-only. Set it before anything else can
  reach this API.

## Repository layout

```
backend/            FastAPI app: engines, security, tools, providers, tests
  app/engines/      understanding, planning, execution, verification, response, memory, safety
  app/security/     approvals, audit, path_guard, sanitizer, stop, undo
  app/providers/    ollama, openai_compat, mock, registry, deterministic router
  app/tools/        24 registered tools across 5 permission levels
python_services/    voice (STT/TTS), vision, gesture, emotion, circuit physics
apps/web/           React + Three.js client
```

## Known repository hygiene problems (not code problems)

`git ls-files` currently tracks `backend/holmev.db`, every `__pycache__/*.pyc`, and
`apps/web/node_modules` — about 14,000 files. A `.gitignore` has been added; the
already-committed files stay tracked until you untrack them:

```powershell
git rm -r --cached backend/holmev.db "backend/**/__pycache__" apps/web/node_modules
```

Review `git status` before committing that change — it only removes them from the
index, not from disk.
