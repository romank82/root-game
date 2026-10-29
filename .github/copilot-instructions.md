<!-- BEGIN TOKEN HYGIENE RULES -->
## Token Hygiene Rules

These rules are mandatory for AI agents working in this repository.

### Do not read or index
- node_modules/
- backend/.venv/
- .venv/
- venv/
- __pycache__/
- dist/
- build/
- coverage/
- backups/
- .local-migration-tests/
- .git/
- *.log
- *.db
- *.sqlite
- *.sqlite3
- *.map
- *.wasm
- *.node
- *.min.js
- *.bundle.js
- package-lock.json
- pnpm-lock.yaml
- yarn.lock
- bun.lockb
- poetry.lock
- Pipfile.lock
- *.bak
- *.bak.*
- *.backup
- wallets.toml
- .env
- .env.*

### Allowed search scopes
Prefer targeted search only in:
- src/
- backend/app/
- backend/tests/
- docs/
- migrations/

### Do not do
- Do not use `grep -r` across the whole repository.
- Do not use `rg --no-ignore`.
- Do not use `find -exec cat` on broad paths.
- Do not read large files entirely unless strictly necessary.
- Do not repeatedly read `backend/app/models.py`, `backend/app/main.py`, or `backend/app/mission_engine.py` without need.

### Large files to handle carefully
Read these by line ranges or targeted search, not whole-file:
- backend/tests/test_mission_engine_integration.py
- src/App.css
- src/components/admin/MissionsSection.tsx
- backend/app/mission_engine.py
- backend/tests/test_admin_players.py
- src/api/adminApi.ts
- backend/app/models.py
- backend/app/main.py
- docs/roadmap-detailed.md
- src/api/engineApi.ts

### Before reading a file
Check size and line count first. If a file is larger than approximately 100 KB or 1000 lines, prefer targeted search or line-range reading.
<!-- END TOKEN HYGIENE RULES -->
