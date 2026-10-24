# Telegram-Flow — agent entry

## Read first

1. `README.md`: product, setup, controls, runtime boundaries. For a fresh local deployment, follow `AGENTREADME.md` step by step.
2. `docs/ARCHITECTURE.md`: data flow, implementation symbols and API map.
3. Relevant source and focused tests before editing. Source is the runtime truth.

Product: combine selected Telegram sources into a browser feed, relay media on demand, and learn preferences locally. Public copy should use this general-purpose positioning. “Relay” means Telegram → local service → browser. Describe existing behavior precisely and distinguish plans from shipped features.

## Workspace and runtime

- Python aiohttp + Telethon + SQLite. Backend lives in the `telegram_flow/` package, one responsibility per module with one-way imports (config → features → learning → storage → filters → telegram → ranking/media → server). Keep it acyclic; put new code in the module that owns the concern.
- `app.py` and `login.py` are thin entry points. Static pages live in `web/`: `index.html` (reader, plain JavaScript), `about.html` (introduction), `architecture.svg` (shared diagram).
- Docker Compose service: `tg-feed`; host port: `8978`; data mount: `./data:/app/data`.
- Clones are usually named `Telegram-Flow`, but use the actual checkout path rather than an assumed one.
- Operate on this machine. Never deploy to another server as part of routine maintenance.
- Keep one runtime per data directory. Do not start a native Python service beside Docker or run `login.py` against a running shared session.

## Private data

`data/`, `.env*`, session/database files, access tokens and logs are private. Do not print, commit, embed in docs/screenshots, or include in image build context. Do not read real media or personal preference records merely to validate UI or documentation. Use mocks and synthetic content.

Avoid opening the live bind-mounted SQLite database from the host while the container is running. Use application interfaces for read-only status. Stop the service before offline database migration, backup or recovery. Preserve data unless the user explicitly requests deletion.

## Small changes, checked claims

- Change only the requested behavior. Preserve existing queue, feedback, filtering and authentication semantics.
- Keep channel diversity and media balancing approximate when inventory is limited.
- 200 queued cards means metadata; 4 cards ahead means ready media. Do not claim 200 videos are fully buffered.
- Respect FloodWait / HTTP 429, retain queued work, and avoid parallel scans of Telegram to test local sorting.
- Preference learning is a local feature model; do not imply visual understanding, agent discovery, GPU models or measured recommendation gains without implementation and evidence.
- Public docs must not contain actual account names, selected channels, media, tokens or individual preference examples.

## Checks

```sh
uv sync --locked
.venv/bin/python -m unittest discover -s tests -v
node tests/test_queue.cjs
node tests/test_hold.cjs
docker compose config --quiet
git diff --check
```

Python tests mock Telegram and database-dependent feed lookup. Node tests use built-in modules only. For docs/static UI changes, validate links, HTML/SVG and layout at desktop/mobile sizes; avoid adding tests that merely repeat copy.

For authorized runtime deployment: `./start.sh` rebuilds/recreates the container and briefly interrupts service. Capture its output locally: it prints token-bearing URLs. Verify container health, `ready` status and changed behavior; never paste raw access URLs into shared logs. Stop with `./stop.sh`.

`GET /api/status` is a low-impact health/status check. `/api/channels`, media endpoints and `/api/more` can call Telegram; `/api/event` changes user history. Do not trigger them as generic smoke tests.

## Delivery

Report what changed, what was checked and any material limitation. Keep README, architecture and introduction consistent when interfaces change. Commit source and documentation only; preserve repository privacy. Publishing public pages, changing repository visibility and sending Telegram messages are separate actions requiring explicit user scope.
