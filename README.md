# BenchCoder backend

Django REST API with Redis/Celery jobs and Docker-isolated Python/JavaScript execution. The frontend is the sibling `BenchCoder-Frontend` project.

## Local stack

1. Start Docker Desktop in Linux-container mode.
2. Copy `.env.example` to `.env` if no local environment exists. Set a strong `SECRET_KEY` and your database password. Keep `.env` private.
3. Run `docker compose up --build -d`.
4. Pull execution images on the same Docker daemon: `docker pull python:3.12-slim` and `docker pull node:22-slim`.
5. Create an administrator with `docker compose exec web python manage.py createsuperuser`.
6. In the frontend project, set `VITE_API_URL=http://127.0.0.1:8000/api`, install packages with `npm ci`, and run `npm run dev`.

The API listens on port 8000; Vite uses 8080. Compose waits for PostgreSQL/Redis and API migrations before starting the worker. Data persists in the PostgreSQL volume. Existing local SQLite data is not automatically imported.

## Development and checks

The existing Windows virtual environment can run `venv/Scripts/python.exe manage.py test`. API/unit tests mock external execution; a passing unit suite does not establish that Docker/Celery integration works. Run `python manage.py makemigrations --check --dry-run` to check migration consistency. Frontend verification uses `npm run build` and `npm run lint`.

## Execution boundaries

Submitted programs must run exclusively in constrained containers. There is no host-execution fallback. The trusted worker controls Docker through its socket; do not expose Docker's API or give submitted containers access to that socket. Use a dedicated execution host before serving untrusted public traffic; ordinary containers share the host kernel.

Runs evaluate at most three public samples. Submissions evaluate the complete suite. Hidden input and expected output must never be returned in user-facing results. AI/RAG and generated code analysis are outside this cycle.

## Verification checklist

Verify registration/login/expiry, staff permissions and CRUD, public sample redaction, pagination, sample run, accepted/wrong/runtime/time/memory failures, result polling/history, broker outage, Docker outage, duplicate delivery and worker interruption. Verify owner-only result access. Use actual Redis + Celery + Docker for execution acceptance, not eager-mode tasks or simulated verdicts.


## Integration smoke test

Create a disposable administrator on the local stack. Set `BENCHCODER_ADMIN_USERNAME` and `BENCHCODER_ADMIN_PASSWORD`, then run `venv/Scripts/python.exe scripts/integration_smoke.py`. Set `BENCHCODER_TEST_MLE=1` to include the memory-limit case. The script creates unique smoke users and removes its problems/results afterward; user records remain for operator cleanup.

On Windows, port 8080 may be reserved. Use `npm run dev -- --host 127.0.0.1 --port 5173`; both 5173 and 8080 localhost origins are allowed.

For coordinated local acceptance tests, `scripts/resilience_smoke.py` uses the same admin environment variables and requires `BENCHCODER_ALLOW_SERVICE_RESTART=1`. It temporarily stops/restarts the local worker and Redis, restores them in `finally`, and verifies duplicates, queued-job recovery and broker outages. Run only against your local disposable test stack.

See `VERIFICATION.md` for tested outcomes and remaining operational limits.
