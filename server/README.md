# PreSense inference and report server

The FastAPI server exposes authenticated live inference, Agent chat, and a post-presentation report.

## Run locally

From the repository root:

```bash
./.venv/bin/pip install -r server/requirements.txt
cd server
../.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
```

Set `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, and `LUXIA_API_KEY` in `server/.env`. Keep the Luxia key on the server. Set `NEXT_PUBLIC_SIGNAL_SOURCE=live` and `NEXT_PUBLIC_INFERENCE_URL=http://localhost:8000` in `frontend/.env.local`. The same Supabase project must be used on both sides.

Apply `frontend/supabase/migrations/20261006_agent_report.sql` before saving generated reports. It adds the `presentation_records.agent_report` JSON column used for history and prior-session Agent memory.
Apply `frontend/supabase/migrations/20261030_user_calibrations.sql` before using persistent personal baselines. It creates a user-owned calibration record with row-level security. Restart the inference server after updating it so `/health`, `/infer`, and `/agent/report` return the model version and baseline comparison fields.

The model loads its Student and CBM checkpoints from `weights/`. The audio projection files and manifest in that directory must match `student_kd_best.pt`; a mismatch prevents model initialization. The paper index is optional for basic report generation. To build it locally, use `python -m agent.download_papers` followed by `python -m agent.index_papers` from the repository root.

## Endpoints

| Method | Path | Input | Result |
| --- | --- | --- | --- |
| GET | `/health` | — | Model health |
| POST | `/infer` | 16 frames and 16 kHz Float32 PCM audio | Stress score, model features, quality flags |
| POST | `/agent/report` | Session metadata and model analysis segments | Structured report with summary, findings, limitations, and memory |
| GET | `/agent/coach/{session_id}?language=ko\|en` | Saved session identity | Restored coaching state and localized conversation |
| POST | `/agent/coach` (also `/agent/chat`) | Session ID, action/question, revision and optional finding/attempt ID | Validated AI-authored coaching and allowlisted UI components |

All report, inference and coaching endpoints require a valid Supabase bearer token. The frontend calls `/agent/report` after a live presentation ends, then saves the returned report with the session. If report generation fails, the presenter can retry before saving.

Coaching requires `LUXIA_API_KEY`. Luxia selects grounded evidence and authors bilingual explanations and short exercises from saved observations/conversation; video/audio originals and credentials are excluded from model prompts. Server-owned state, timestamps and comparison calculations are validated separately. AI unavailability or failed validation returns `503` with `detail.code=coach_ai_unavailable` and preserves the previous state. Apply `frontend/supabase/migrations/20261027_presentation_coaching.sql` for durable coaching storage. See `docs/presentation-coach.md` for the loopback-only preview using actual StressID inference.
