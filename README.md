# Memory Companion Backend

FastAPI backend for a family memory companion app. The API supports:

- Authentication with JWT
- User/family/relation management
- Media upload to S3
- Memory, reminder, and story-audio CRUD
- Entity-relation extraction and memory graph retrieval
- Voice sample upload, voice cloning, and text-to-speech
- Agentic flows (Tinyfish SSE integration for journeys and notifications)
- Manual testing pages for end-to-end flow and graph visualization

## Tech Stack

- Python + FastAPI
- PostgreSQL (Neon) via `psycopg`
- AWS S3 via `boto3`
- OpenAI (entity extraction + embeddings)
- ElevenLabs (voice clone + TTS)
- Tinyfish Web Agent (SSE)
- ngrok (optional tunnel)

## Project Structure

```text
backend/
  app/
    main.py
    routers/
      auth_router.py
      user_crud_router.py
      media_crud_router.py
      relation_router.py
      graph_router.py
      agentic_router.py
    schemas/
      auth.py
      crud.py
      relation.py
      graph.py
      agentic.py
      schema.sql
    services/
      auth_service.py
      user_crud.py
      media_service.py
      media_crud.py
      relation_service.py
      extract_entity_relation.py
      memory_graph_service.py
      voice_service.py
      tinyfish_agent_service.py
  manual_test/
    index.html
    graph_visualize.html
    sample_inputs.json
  tests/
    test_api_routes.py
    test_agentic_router.py
    test_user_crud.py
    test_media_crud.py
    test_media_service.py
    test_extract_entity_relation.py
    test_memory_graph_service.py
  requirements.txt
```

## Installation

1. Create and activate virtual environment.
2. Install dependencies.

```powershell
cd backend
python -m venv ..\.venv
..\.venv\Scripts\activate
pip install -r requirements.txt
```

## Environment Variables

Create/update `.env` in `backend/`.

### Required

```env
DATABASE_URL=postgresql://<user>:<password>@<host>/<db>?sslmode=require
JWT_SECRET_KEY=<strong_secret>
AWS_REGION=us-east-1
AWS_S3_BUCKET_NAME=<bucket>
AWS_ACCESS_KEY_ID=<key>
AWS_SECRET_ACCESS_KEY=<secret>
ELEVENLABS_API_KEY=<key>
```

### Optional (Recommended)

```env
# Auth
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=30

# S3 / media
AWS_SESSION_TOKEN=
AWS_S3_ENDPOINT_URL=
AWS_S3_PRESIGN_EXPIRE_SECONDS=900
MEDIA_MAX_FILE_SIZE_MB=100

# OpenAI (extraction + embeddings)
OPENAI_API_KEY=
OPENAI_LLM_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536

# Tinyfish agentic
TINYFISH_API_KEY=
TINYFISH_SSE_ENDPOINT=https://agent.tinyfish.ai/v1/automation/run-sse
TINYFISH_TIMEOUT_SECONDS=180

# CORS
CORS_ALLOW_ORIGINS=http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:3000,http://localhost:3000
CORS_ALLOW_CREDENTIALS=true
CORS_ALLOW_ORIGIN_REGEX=

# ngrok
NGROK_ENABLED=false
NGROK_AUTHTOKEN=
NGROK_PORT=8000
NGROK_DOMAIN=
```

## Run API

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

- Swagger UI: `http://127.0.0.1:8000/docs`
- Health: `GET /`
- Manual pages:
  - `GET /frontend`
  - `GET /graph_visualize`

## API Overview

Base URL: `/api/v1` (except relation QR endpoint prefix `/api/relations`).

### Auth (`/api/v1/auth`)

- `POST /register`
- `POST /login`
- `GET /me`

### Users, Families, Relations (`/api/v1`)

#### Users

- `POST /users` (supports JSON or multipart form-data with optional avatar upload)
- `GET /users/{user_id}`
- `GET /users?limit=&offset=`
- `PATCH /users/{user_id}` (JSON or multipart; supports avatar update/remove)
- `PATCH /users/{user_id}/avatar`
- `POST /users/{user_id}/avatar/upload`
- `PATCH /users/{user_id}/voice`
- `POST /users/{user_id}/voice/clone`
- `POST /users/{user_id}/voice/upload-and-clone` (single-call flow: upload voice -> set `voice_sample_s3_url` -> clone)
- `POST /users/{user_id}/voice/speak`
- `DELETE /users/{user_id}`

#### Families

- `POST /families`
- `GET /families/{family_id}`
- `GET /families?limit=&offset=`
- `GET /families/get_families_id/{user_id}`
- `PATCH /families/{family_id}`
- `DELETE /families/{family_id}`

#### User relations

- `POST /user-relations`
- `GET /user-relations/{relation_id}`
- `GET /user-relations?limit=&offset=`
- `PATCH /user-relations/{relation_id}`
- `DELETE /user-relations/{relation_id}`

### Join by QR (`/api/relations`)

- `POST /join-by-qr` (auth required)

### Media / Memories / Reminders (`/api/v1`)

#### Upload helpers

- `POST /image/upload-url`
- `POST /voice/upload-url`

#### Media

- `POST /media`
- `POST /media/upload` (multipart: file + `family_id` + `uploaded_by` + optional `notes`, `captured_at`)
- `GET /media/{media_id}`
- `GET /media?limit=&offset=`
- `PATCH /media/{media_id}`
- `DELETE /media/{media_id}`

#### Memories

- `POST /memories`
- `GET /memories/{memory_id}`
- `GET /memories?limit=&offset=`
- `PATCH /memories/{memory_id}`
- `DELETE /memories/{memory_id}`

#### Reminders

- `POST /reminders`
- `GET /reminders/{reminder_id}`
- `GET /reminders?limit=&offset=`
- `PATCH /reminders/{reminder_id}`
- `DELETE /reminders/{reminder_id}`

#### Memory stories audio

- `POST /memory-stories-audio`
- `GET /memory-stories-audio/{story_id}`
- `GET /memory-stories-audio?limit=&offset=`
- `PATCH /memory-stories-audio/{story_id}`
- `DELETE /memory-stories-audio/{story_id}`

### Memory Graph (`/api/v1/graph`)

- `POST /extract-preview`
- `POST /query` (`use_advanced=true` for graph-context search)

### Agentic (`/api/v1/agentic`)

- `POST /tinyfish/sse/test`
- `POST /journey/test`
- `POST /meaningful-notifications/test`

## Core Behaviors

### Media upload pipeline

`POST /media/upload` does:

1. Validate file type/size
2. Upload file to S3
3. Save media row in Postgres
4. Trigger memory graph sync for this media item
5. Return saved media record

### Voice pipeline

Single-call endpoint for FE:

- `POST /users/{user_id}/voice/upload-and-clone`

Flow:

1. Upload voice sample to S3
2. Update `users.voice_sample_s3_url`
3. Clone voice via ElevenLabs
4. Update `users.voice_status` + `users.eleven_voice_id`

### Extraction and retrieval

- Entity extraction is LLM-first (`OPENAI_API_KEY`) with rule-based fallback.
- Graph search supports hybrid and advanced query modes.

## Manual Testing

### 1) Full flow page

- Open `GET /frontend`
- Supports user/family create, media upload, and graph query flow

### 2) Graph visualization

- Open `GET /graph_visualize`
- Queries graph endpoint and renders node-link visualization

## Testing

Run all tests:

```powershell
cd backend
$env:PYTHONPATH='.'
..\.venv\Scripts\python.exe -m pytest -q
```

Run targeted tests:

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_api_routes.py -q
..\.venv\Scripts\python.exe -m pytest tests/test_agentic_router.py -q
```

## Notes

- CORS is configurable via env (`CORS_ALLOW_ORIGINS`, `CORS_ALLOW_ORIGIN_REGEX`, `CORS_ALLOW_CREDENTIALS`).
- ngrok startup is optional and controlled by env.
- `@app.on_event` lifecycle hooks are used (FastAPI warns this is deprecated in favor of lifespan API, but functionality is fine).
- Keep secrets out of version control and rotate any exposed keys.
