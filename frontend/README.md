# Frontend

Безопасная миграция кабинета на `Vite + React + shadcn/ui`.

## Локальный запуск

```bash
cd frontend
npm install
npm run dev
```

Backend продолжает работать отдельно:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Прод-сборка

```bash
cd frontend
npm install
npm run build
```

После сборки `FastAPI` автоматически начнёт отдавать SPA для `/dashboard`, `/stats` и `/settings`, если существует `frontend/dist/index.html`.
