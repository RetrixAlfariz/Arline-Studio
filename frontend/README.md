# Arline Studio frontend

Arline's v1.2 frontend is a React + TypeScript + Vite application. It replaces
new UI development in the old `src/interface/web/static` HTML/vanilla-JS
surface. The Python/FastAPI backend remains authoritative for workspace data,
memory, discovery, inference, generation, history, media, and storage.

## Development

Run the backend from the repository root:

```powershell
uv sync
uv run python app.py
```

Then run the frontend in another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api`, `/static`, `/downloads`, and
`/dataset-downloads` to the backend at `127.0.0.1:7860`.

## Production/local integrated build

```powershell
cd frontend
npm install
npm run build
cd ..
uv run python app.py
```

When `frontend/dist/index.html` and its `assets/` directory exist, `app.py`
serves the React frontend at the configured Arline port. When the build is not
present, Arline falls back to the previous static interface so backend-only
work and recovery remain possible.

## Boundaries

- TypeScript owns presentation, client interaction state, local UI preferences,
  and unsent draft recovery.
- FastAPI/Python owns canonical state and application behavior.
- Rust remains available for native/performance-sensitive storage work.
- Opening a Library sheet is navigation only; explicit references control model
  context.
- `node_modules/`, `dist/`, Vite caches, coverage output, and TypeScript build
  metadata are ignored and must never be committed.
