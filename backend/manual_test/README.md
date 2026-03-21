# Manual Flow Tester

## What this tests

1. Create user with full profile fields
2. Create family for that user
3. Upload multiple images + notes and videos + notes
4. Retrieve memories via graph query (`/api/v1/graph/query`)
5. Optional: list media rows

## Files

- `index.html`: Browser UI tester
- `sample_inputs.json`: Example payloads/notes/queries

## Run

1. Start backend API:

```powershell
cd backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

2. Open `manual_test/index.html` in your browser (double-click or serve with any static server).

3. Click buttons in order:

- **Create User + Family**
- **Upload All Media**
- **Query Graph Memories**

## Notes

- Upload endpoint is `POST /api/v1/media/upload` (multipart form).
- Upload flow is automatic: S3 upload -> Postgres save -> memory graph sync.
- If CORS/browser local file issues happen, host this folder with a simple static server.
