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
| POST | `/agent/chat` | Question and recent session summaries | Coaching reply |

The three POST endpoints require a valid Supabase bearer token. The frontend calls `/agent/report` after a live presentation ends, then saves the returned report with the session. If report generation fails, the presenter can retry before saving.
