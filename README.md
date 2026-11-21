# Ledgerline

**Decisions that stick. Contradictions that don't slip through.**

Ledgerline turns meeting transcripts into reviewable decisions and action items, checks new proposals against approved organizational memory, and tracks approved commitments through completion.

## Run the integrated website + backend (Windows)

1. Install Python 3.10+ (and ensure `py` is available).
2. Double-click `start_windows.bat`. The first run creates a virtual environment and installs the backend requirements. Internet access is required for this first installation.
3. The website opens at **http://127.0.0.1:5173**. The API runs at **http://127.0.0.1:8000**.
4. Open Settings and confirm that the API says Connected. The app attempts to connect automatically on startup.

For macOS/Linux, run `chmod +x start_mac_linux.sh && ./start_mac_linux.sh`.

## Manual startup

Terminal 1 — backend:

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Windows: copy .env.example .env
uvicorn app.main:app --reload
```

Terminal 2 — website (from repository root):

```bash
cd demo
python -m http.server 5173
```

Open http://127.0.0.1:5173. API docs are at http://127.0.0.1:8000/docs.

## Backend configuration

Edit `backend/.env`:

- `DEMO_MODE=auto`: uses the deterministic backend extractor when no Anthropic key is configured; uses Claude when `ANTHROPIC_API_KEY` is present.
- `DEMO_MODE=on`: force deterministic extraction.
- `DEMO_MODE=off`: require live Anthropic extraction.
- `DATABASE_URL=sqlite:///./ledgerline.db`: SQLite database created in the backend working directory.
- `GITHUB_TOKEN` and `GITHUB_REPO=owner/repository`: optional real GitHub Issues publishing. Without these, the backend uses its mock tracker.
- SMTP settings are optional and only needed to send email digests.

Never commit `.env` or API tokens.

## What is connected end-to-end

When the API is reachable, the website uses the FastAPI database as its source of truth for:

- Meeting creation from pasted text or `.txt`, `.vtt`, `.srt` transcripts.
- Backend transcript parsing, speaker attribution and extraction.
- Pending decisions and action items in the human review queue.
- Cross-meeting decision conflict detection and conflict resolution.
- Approved decision memory and source evidence.
- Action-item edits, owner/deadline validation and approval.
- Task board status changes, with the backend tracker adapter updated first.
- Meeting history, audit events and dashboard metrics.

The UI automatically falls back to its browser-local demonstration data if the API is offline. Local demo records and backend database records are separate.

## Extraction modes and integrations

The backend includes a deterministic mock extractor for no-key demos and an Anthropic JSON extraction path for configured live use. The GitHub Issues adapter can create real issues only when valid credentials and a repository are configured. Otherwise the mock tracker records approved tasks locally in the backend database. The backend also includes reminders, notification and weekly digest endpoints.

## Important limitations

This is a hackathon prototype, not a production multi-tenant SaaS. It does not yet include user authentication/authorization, tenant isolation, raw-audio transcription/voice diarization, Slack/Jira integration or production monitoring. The local mock extractor is deterministic and should not be described as an LLM. Before handling real company data, add authentication, authorization, rate limiting, tenant isolation, secure deployment secrets, backups and monitoring.

## Tests

```bash
cd backend
../backend/.venv/bin/pytest   # macOS/Linux
# Windows: .venv\Scripts\python -m pytest
```
