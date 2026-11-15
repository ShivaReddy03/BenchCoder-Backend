# Personalized hint demonstration

The optional hint feature retrieves reviewed teaching notes only from problems the current learner actually solved. The shared target is `[Hint Demo] Two Sum`. Demo histories are intentionally distinct:

| Account | Real evaluated history | Expected useful connection |
| --- | --- | --- |
| `demo_arrays` | Contains Duplicate; Sorted Pair Sum | Membership lookup, complement lookup, sorted two pointers |
| `demo_strings` | Valid Anagram; First Unique Character | Frequency maps and lookup |

The dataset contains eight labeled demo problems, each with four reviewed cases (three public, one private), Python and JavaScript reference solutions, concepts, and short approach notes. Other problems are untouched. Reserved titles are updated only when their description has the dataset marker. Existing demo accounts must have the reserved `@example.invalid` email and cannot be privileged.

## Prepare real solved histories

Run migrations and start web, Redis, and Celery with Docker execution images available. Set `HINT_DEMO_PASSWORD` in the command environment without putting it in shell history or source control. In the backend environment run:

```powershell
python manage.py seed_hint_demo --create-users --submit-solutions --wait
```

For Compose, pass the environment variable through to the command:

```powershell
docker compose exec -e HINT_DEMO_PASSWORD web python manage.py seed_hint_demo --create-users --submit-solutions --wait
```

Without `--submit-solutions`, the command only seeds reviewed content and optionally accounts. It never fabricates accepted submissions or solve-ledger rows. With that flag, correct solutions are submitted to the real Celery/Docker judge; `--wait` checks actual acceptance, with a default 240-second bound. Repeated runs reuse pending work and already solved problems. Existing account passwords are never changed. If no password environment variable is supplied, newly created accounts receive independent random passwords, displayed once in the local command output; store those securely. The HTTP smoke expects a shared `HINT_DEMO_PASSWORD`, so configure it when creating fresh demo accounts.

All 64 reference-solution/case combinations have been checked locally using the trusted fixture implementations. The four demo-history solutions still require real Docker evaluation through the command; local fixture checks do not create solved histories.

## Configure the provider separately

Seeding never calls the AI provider. Configure the backend and worker with the provider settings documented in the main README (`OPENAI_API_KEY`, `AI_HINT_MODEL`, `AI_EMBEDDING_MODEL` and quotas), then restart them. Keep credentials in the environment; never put them in frontend configuration or this file. No API key is needed for core coding workflows or fixture setup.

The first real hint lazily embeds eligible reviewed source knowledge. Changed descriptions/concepts/approach notes invalidate stored embeddings. Only up to three similar solved sources are retrieved; weak similarity can yield fewer sources. Provider outputs are nondeterministic, so exact hint wording and ranking are not golden test expectations. Empty histories must receive an honest general hint rather than invented personalization. Hint generation and embeddings may incur provider charges. With no configured key, the service reports an explicit unavailable state rather than fake hints.

## Verify through the UI

Sign in as each demo learner, open `[Hint Demo] Two Sum`, and request a concept hint. Compare source titles: each account should show only its own actually solved problems. Then request an approach hint or supply an attempt for debugging help. Hints should remain progressive and should not include complete implementations. Check that another user's hint request cannot be opened.

## Optional real provider smoke

After preparing the histories, set `HINT_DEMO_PASSWORD`, optional `BENCHCODER_API_URL`, and explicitly set `BENCHCODER_ALLOW_PROVIDER_CALLS=1`. Run:

```powershell
python scripts/hints_smoke.py
```

This logs in as both learners, requests the same target, polls actual asynchronous provider results, verifies different source sets limited to each learner's accepted history, and checks cross-owner access is denied. It prints public source titles and generated hints, never passwords or provider keys. It never mocks a provider or seeds acceptance. Cached responses can be returned without another model call. Provider errors, exhausted quotas, insufficient similarity, or unavailable workers fail the smoke honestly.

The smoke leaves demo content and request history available for UI review. Remove only the explicitly labeled demo problems/accounts when the demonstration is no longer needed; cascading deletion removes their associated test cases, submissions, knowledge, and hint requests. Do not delete unrelated learner data.



Local verification: both demo accounts have been created, and their four history solutions were accepted through the real Celery/Docker judge. The shared password is stored privately as HINT_DEMO_PASSWORD in the local backend .env. OPENAI_API_KEY is configured and API credits are available. The live provider smoke passed for both learners: hints generated successfully with different personally solved source sets, cached embeddings, and owner-only access. The browser also displayed a live personalized hint referencing Contains Duplicate.

## Pinecone mode

The current local demo has Pinecone configured and8 public knowledge records indexed. The same two-user smoke passed while explicitly asserting `retrieval_backend=pinecone`. Use the settings and `sync_pinecone` command in the main README. The active index embeds `chunk_text` with `text-embedding-3-small` internally; GPT hint generation continues using the OpenAI key. The UI identifies Pinecone retrieval and explains that user code is not sent to the vector service.
