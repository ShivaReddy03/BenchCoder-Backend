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

Runs evaluate at most three public samples. Submissions evaluate the complete suite. Hidden input and expected output must never be returned in user-facing results. Personalized AI hints are optional; configure them as described below.

## Verification checklist

Verify registration/login/expiry, staff permissions and CRUD, public sample redaction, pagination, sample run, accepted/wrong/runtime/time/memory failures, result polling/history, broker outage, Docker outage, duplicate delivery and worker interruption. Verify owner-only result access. Use actual Redis + Celery + Docker for execution acceptance, not eager-mode tasks or simulated verdicts.


## Integration smoke test

Create a disposable administrator on the local stack. Set `BENCHCODER_ADMIN_USERNAME` and `BENCHCODER_ADMIN_PASSWORD`, then run `venv/Scripts/python.exe scripts/integration_smoke.py`. Set `BENCHCODER_TEST_MLE=1` to include the memory-limit case. The script creates unique smoke users and removes its problems/results afterward; user records remain for operator cleanup.

On Windows, port 8080 may be reserved. Use `npm run dev -- --host 127.0.0.1 --port 5173`; both 5173 and 8080 localhost origins are allowed.

For coordinated local acceptance tests, `scripts/resilience_smoke.py` uses the same admin environment variables and requires `BENCHCODER_ALLOW_SERVICE_RESTART=1`. It temporarily stops/restarts the local worker and Redis, restores them in `finally`, and verifies duplicates, queued-job recovery and broker outages. Run only against your local disposable test stack.

See `VERIFICATION.md` for tested outcomes and remaining operational limits.


## Optional personalized AI hints

Hints use OpenAI embeddings plus the Responses API, with retrieval restricted to each learner's genuinely solved problems. Defaults: `gpt-4.1-mini` and `text-embedding-3-small`. No separate vector database or AI SDK is required for this bounded demo corpus.

1. Create an API key at https://platform.openai.com/api-keys and enable API billing. An AI chat subscription does not supply this application's API credentials.
2. Set `OPENAI_API_KEY` in the backend's private `.env` (a blank placeholder is provided locally). Never put it in a `VITE_` variable, chat, or Git.
3. Run `docker compose up --build -d` to apply migrations and pass the key into both API and worker containers. A plain container restart does not reload changed Compose environment variables.
4. Follow `RAG_DEMO.md` to seed the eight reviewed problems and obtain two different real solved histories.
5. Sign in, open a problem, and click Request hint. The browser discloses which context will be sent. Concept, approach, and debugging levels are available.

Default admission limits are20requests per user/day and200globally/day (UTC), one active request per learner, with24-hour identical-request caching. These bound application usage, not an exact dollar budget; configure provider-side billing controls as well. Hint output is capped at450tokens and code context at12,000characters. Provider timeouts/errors produce truthful failure states. With no key, the core judge continues working and AI hints show unavailable.

Problem knowledge is managed through Django admin (`/admin/`, Problem knowledge): add reviewed concept names and short approach notes. Notes for the current problem are never sent; notes from a different problem are retrieved only after the learner has solved that problem. Embeddings are cached and compared in the application over up to40recent solved problems. Low-similarity matches are omitted.

API: authenticated `GET /api/hints/config/`, `POST /api/hints/`, and owner-only `GET /api/hints/<id>/`. Never return API credentials, other users' code, or private test cases. The generation prompt and output checks discourage full solutions but cannot guarantee perfect hints or prevent every conceptual solution leak. Treat AI suggestions as fallible.

References: https://developers.openai.com/api/docs/quickstart, https://developers.openai.com/api/docs/guides/embeddings, https://developers.openai.com/api/docs/guides/structured-outputs.

## Pinecone vector retrieval

The demo now selects `AI_RETRIEVAL_BACKEND=pinecone` in the private local `.env`. Keep PostgreSQL for application data, reviewed teaching notes and solved histories. Pinecone stores/searches public knowledge documents and their vectors; OpenAI GPT generates the final hint. The configured index uses Pinecone's Documents API with integrated `text-embedding-3-small` embeddings (1536dimensions, cosine) on `chunk_text`. This is different from a classic bring-your-own-vector index; do not use the legacy Vectors API for this schema.

Backend/worker environment:

```env
AI_RETRIEVAL_BACKEND=pinecone
PINECONE_API_KEY=your_private_key
PINECONE_INDEX_HOST=your_index_host
PINECONE_NAMESPACE=benchcoder-knowledge-v1
PINECONE_EMBEDDING_FIELD=chunk_text
PINECONE_EMBEDDING_MODEL=text-embedding-3-small
```

Run `docker compose up --build -d`, then `docker compose exec web python manage.py sync_pinecone` to index existing reviewed knowledge. New/changed eligible records are also synchronized lazily during retrieval. `sync_pinecone --force` repairs remote records after manual deletion; it does not delete unrelated data. Upserts are eventually searchable, so the adapter has bounded readiness checks and retryable failure reporting.

Documents contain an identifier, public title/description/concepts, a content hash and model metadata. No user code, private tests, learner identifiers or teaching notes are uploaded to Pinecone. The query filter restricts searches to exact current-version records from that learner's eligible solves. Backend checks IDs, hashes, model, finite scores and current SQL eligibility before using a result; reviewed notes are loaded from PostgreSQL afterward.

In Pinecone mode, a remote failure produces an explicit failed hint; there is no silent local similarity fallback. `AI_RETRIEVAL_BACKEND=local` remains an explicit optional mode using the existing PostgreSQL JSON cache. Existing local embedding cache rows are not deleted by the migration. Old remote record versions are excluded by version filters but remain stored; periodic cleanup is a future operational task for a much larger corpus.

For the real smoke script set `BENCHCODER_EXPECT_RETRIEVAL_BACKEND=pinecone` along with its normal credentials/opt-in environment variables. This prevents a successful local-mode run from being mistaken for Pinecone verification. Pinecone free-plan storage/read/write/inference limits and OpenAI hint-generation charges are separate.

Pinecone API references: https://sdk.pinecone.io/python/how-to/documents/schema-and-upsert.html and https://sdk.pinecone.io/python/how-to/documents/search.html.

## Render PostgreSQL and practice catalog

Compose reads `DATABASE_URL` from the private `.env` when set. The current local API and Celery worker both use the Render external PostgreSQL URL with `sslmode=require`; local PostgreSQL remains as the preserved migration source. A private pre-migration dump was saved outside the repository under LocalAppData/BenchCoder/backups. No local database volume was deleted.

For a hosted database, keep credentials out of Git, use the external URL when your services run outside Render, and recreate containers after environment changes. Connection health checks, a 60-second connection age, TCP keepalives, and connection release around external calls prevent reusing idle cloud sockets. Judge finalization retries its guarded database transaction; hint finalization retries database persistence without repeating paid model generation.

Add or update the 15 original practice problems with `docker compose exec web python manage.py seed_catalog`. Each has an explicit statement, input/output format, constraints, three public samples and four private cases. Seed data includes reviewed RAG knowledge and trusted reference fixtures; reference implementations are never returned by problem APIs. Unrelated problems are preserved. The current database contains 24 problems: 9 existing and 15 new.

Verification script: `docker compose exec web python scripts/verify_catalog.py --skip-fixtures --timeout 600` evaluates both languages through real Celery/Docker using a disposable account. Use `--resume-user <printed_catalog_verify_name>` to resume after an infrastructure interruption. On the host, `venv/Scripts/python.exe scripts/verify_catalog.py --fixtures-only` checks only the trusted repository reference fixtures. Never run arbitrary submitted code outside the Docker runner.

When local `.env` points at Render, run unit tests with process `USE_POSTGRES=false` so Django creates its disposable SQLite test database instead of a cloud test database. Example PowerShell: `$env:USE_POSTGRES='false'` followed by `venv/Scripts/python.exe manage.py test --noinput`. Use a separate shell for normal Render-backed commands afterward.

Render's free PostgreSQL expires 30 days after creation; export or upgrade before expiry. Hosting the database does not deploy the API, worker, Redis or Docker runner; those currently run in the local Compose stack.

## Full AI solutions and caching

Supported editor and judge languages: Python 3, JavaScript, Java 21 (`public class Main`) and C++17. Before accepting submissions on a new server, pre-pull `python:3.12-slim`, `node:22-slim`, `eclipse-temurin:21-jdk` and `gcc:14`. The judge never downloads images during a request. Java/C++ compilation is limited to 30 seconds and uses an isolated 512 MB container; program execution remains limited to 3 seconds. C++ binaries are written only into an ephemeral executable `/build` tmpfs. Source volumes remain read-only and execution has no network access. Run `venv/Scripts/python.exe scripts/compiled_languages_smoke.py` on a Docker-enabled host to verify both compilers, invalid-source diagnostics and runtime timeouts.

The problem page includes Description, your problem-specific Submissions, and Solution tabs. Opening Solution shows an explicit “I give up” gate. Only that button sends the problem's public statement/samples, selected language, and current editor code to OpenAI. Generated solutions include an explanation, runnable code and complexity; they are labeled AI-generated and are not automatically judge-verified or submitted.

`POST /api/solutions/` accepts `problem`, `language` and `code`; completed identical requests return HTTP 200 with the saved result, and queued/running identical requests return HTTP 202 with the existing job. Poll owner-only `GET /api/solutions/<id>/` for new jobs. The PostgreSQL cache is scoped to the user, public problem version, exact editor code, language, model and prompt version. Reopening or refreshing does not require another paid generation for the same inputs. Failed requests may be retried. Default generation limits are 10 per user and 100 globally per UTC day; cached results bypass these limits. Configure `AI_SOLUTION_MODEL`, `AI_SOLUTIONS_DAILY_LIMIT` and `AI_SOLUTIONS_GLOBAL_DAILY_LIMIT` alongside the existing private `OPENAI_API_KEY`.

The frontend caches public problem data for five minutes, scoped to the account and role. Session persistence excludes private test cases. Editor drafts remain stored per user/problem/language; loading an AI solution requires confirmation and keeps a draft backup. `GET /api/submissions/?problem=<positive-id>` returns only the authenticated user's submissions for that problem, excluding sample runs.

For an opt-in live generation/cache/sample-execution check, run `scripts/solutions_smoke.py` with `BENCHCODER_ALLOW_PROVIDER_CALLS=1` and `BENCHCODER_SOLUTION_USERNAME` / `BENCHCODER_SOLUTION_PASSWORD` set privately in the process environment. Optional separate `BENCHCODER_ADMIN_USERNAME` / `BENCHCODER_ADMIN_PASSWORD` enable a real cross-account ownership check. The script runs generated code only through the existing Docker runner and does not award a solve.
