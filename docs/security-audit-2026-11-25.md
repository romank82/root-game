# Аудит безопасности ROOT Game — 2026-11-25

## 1. Резюме

Проверены backend `backend/app`, frontend `src`, deployment-файлы, документация,
денежный контур ROOT, TON-интеграция, маршруты и тесты. Найдено:

| Уровень | Количество |
|---|---:|
| Критично | 0 |
| Высоко | 1 |
| Средне | 2 |
| Низко | 2 |

Самые опасные проблемы:

1. Production deposit poller работает от `root`, хотя ему достаточно отдельного
   непривилегированного пользователя; компрометация poller/API-кода получает
   права ОС root.
2. В nginx отсутствуют базовые browser security headers: HSTS, CSP,
   `X-Frame-Options`, `X-Content-Type-Options`.
3. Ядро депозитов не проверяет, что `tx.to_address` совпадает с CMS-адресом
   deposit wallet; сейчас это ограничивается только текущим poller-потоком.

В хорошем состоянии находятся Telegram HMAC-аутентификация с проверкой возраста,
HttpOnly-сессии, permission-based admin access, immutable ledger, холды и
идемпотентность withdrawal, row locks в критичных денежных операциях, подпись и
сопоставление BOC, проверка доставки в TON и обработка ошибок внешнего API.

## 2. Карта проекта

| Область | Основные файлы | Назначение |
|---|---|---|
| HTTP/API и auth | `backend/app/main.py`, `telegram_auth.py`, `admin_auth.py`, `admin_access.py` | FastAPI-маршруты, Telegram/game cookies, admin sessions и permissions |
| Игровой движок | `mission_engine.py`, `geo_location_proof.py`, `geo_anticheat.py` | миссии, награды, location proof и античит |
| ROOT ledger | `models.py`, `mission_engine.py`, `deposit_service.py`, `withdrawal_service.py`, `transfer_service.py` | кошельки, immutable `WalletTransaction`, кредиты/дебеты и переводы |
| Выплаты | `payout_batch_service.py`, `payout_confirm_service.py`, `payout_rollback_service.py`, `admin_withdrawals.py` | холд, payout batch, BOC confirm, rollback |
| TON | `ton_connect_parser.py`, `ton_payout_lookup.py`, `ton_service.py`, `deposit_poller.py` | разбор BOC, Ton API, jetton deposits и delivery lookup |
| Admin/CMS | `admin_*.py`, `system_settings_catalog.py`, `admin_audit.py` | CMS, permission checks, approvals и immutable audit |
| Фоновые задачи | `retention.py`, `deposit_poller.py` | retention и отдельный systemd deposit poller |
| Frontend | `src/api/*.ts`, `src/components`, `src/AdminApp.tsx` | Telegram Mini App и admin UI |
| Deployment | `deploy/nginx.conf`, `deploy/*.service`, `deploy/README.md` | nginx, gunicorn и systemd |

## 3. Инвентаризация эндпоинтов

Маршруты извлечены AST-анализом декораторов без импорта приложения. `Game` означает
`Depends(get_current_player_id)`, `Admin` — `get_admin_user` или
`require_permission`, `Super-admin` — `require_super_admin`.

### Публичные и системные маршруты

| Путь | Метод | Авторизация | Проверка прав | Замечания |
|---|---|---|---|---|
| `/` | GET | нет | нет | Служебная информация |
| `/health` | GET | нет | нет | Health endpoint; раскрывает `environment` (F-04) |
| `/api/v1/auth/telegram` | POST | нет | нет | HMAC Telegram initData, rate limit 5/min |
| `/api/v1/auth/logout` | POST | нет | нет | Удаляет game cookie |
| `/api/v1/admin/auth/login` | POST | нет | нет | Argon2id, rate limit 10/min |
| `/api/v1/admin/auth/me` | GET | cookie проверяется в обработчике | нет | Возвращает только admin projection |
| `/api/v1/admin/auth/logout` | POST | cookie обрабатывается в обработчике | нет | Отзывает server-side session |
| `/webhook/telegram` | POST | Telegram secret header в production | нет | В dev отсутствие secret разрешено конфигурацией |

### Игровые маршруты

Все перечисленные ниже требуют `Game` и не принимают `player_id` из URL как
источник личности.

| Метод | Пути |
|---|---|
| GET | `/api/v1/engine/bootstrap`, `/api/v1/engine/me/profile`, `/api/v1/engine/me/referral`, `/api/v1/me/ton-wallet`, `/api/v1/me/withdrawals`, `/api/v1/engine/missions/{mission_id}/qr-payload`, `/api/v1/engine/fallback-offers`, `/api/v1/players/search`, `/api/v1/engine/shop/items`, `/api/v1/engine/teams/me`, `/api/v1/engine/teams/{team_id}`, `/api/v1/engine/teams/invitations/me`, `/api/v1/engine/teams/join-requests/me`, `/api/v1/engine/team-missions/sessions/me`, `/api/v1/engine/team-missions/sessions/last`, `/api/v1/engine/team-missions/sessions/active`, `/api/v1/engine/team-missions/sessions/{session_id}/messages` |
| POST | `/api/v1/engine/missions/{mission_id}/submit`, `/api/v1/engine/missions/{mission_id}/accept`, `/api/v1/engine/missions/{mission_id}/location-proof`, `/api/v1/players/transfer`, `/api/v1/me/ton-wallet`, `/api/v1/me/withdrawals`, `/api/v1/engine/gas/invoice`, `/api/v1/engine/gas/invoice/send`, `/api/v1/engine/missions/{mission_id}/expire`, `/api/v1/engine/missions/{mission_id}/scan-qr`, `/api/v1/engine/fallback-offers/{offer_id}/purchases`, `/api/v1/engine/shop/items/{item_id}/purchases`, `/api/v1/engine/teams`, `/api/v1/engine/teams/{team_id}/join`, `/api/v1/engine/teams/{team_id}/leave`, `/api/v1/engine/teams/{team_id}/members/{target_player_id}/kick`, `/api/v1/engine/teams/{team_id}/transfer-leadership`, `/api/v1/engine/teams/{team_id}/disband`, `/api/v1/engine/teams/{team_id}/invitations`, `/api/v1/engine/teams/invitations/{invitation_id}/accept`, `/api/v1/engine/teams/invitations/{invitation_id}/reject`, `/api/v1/engine/teams/{team_id}/join-requests`, `/api/v1/engine/teams/{team_id}/join-requests/{request_id}/approve`, `/api/v1/engine/teams/{team_id}/join-requests/{request_id}/reject`, `/api/v1/engine/team-missions/sessions`, `/api/v1/engine/team-missions/sessions/{session_id}/join`, `/api/v1/engine/team-missions/sessions/{session_id}/ready`, `/api/v1/engine/team-missions/sessions/{session_id}/leave`, `/api/v1/engine/team-missions/sessions/{session_id}/location`, `/api/v1/engine/team-missions/sessions/{session_id}/activate`, `/api/v1/engine/team-missions/sessions/{session_id}/submit-wave`, `/api/v1/engine/team-missions/sessions/{session_id}/messages` |
| PATCH | `/api/v1/engine/me/profile`, `/api/v1/engine/teams/{team_id}` |
| DELETE | `/api/v1/me/ton-wallet`, `/api/v1/engine/teams/{team_id}/invitations/{invitation_id}`, `/api/v1/engine/teams/join-requests/{request_id}` |

### Административные маршруты

Все admin-маршруты ниже защищены либо `require_permission(...)`, либо
`get_admin_user` с последующей domain-проверкой, либо `require_super_admin`.
Исключение — `POST /api/v1/admin/approvals`: он намеренно доступен без auth,
но всегда возвращает 410 и ничего не создаёт.

| Prefix | Маршруты и требуемая защита |
|---|---|
| `/api/v1/admin/approvals` | `POST /` — 410 без auth; `GET /`, `GET /{approval_id}`, `POST /{approval_id}/cancel` — admin session; `POST /{approval_id}/approve`, `POST /{approval_id}/reject` — super-admin |
| `/api/v1/admin/admins` | `GET /`, `POST /`, `POST /{admin_id}/permissions`, `DELETE /{admin_id}/permissions/{permission_code}`, `POST /{admin_id}/deactivate`, `POST /{admin_id}/reactivate` — super-admin |
| `/api/v1/admin/missions` | list/get/translations GET — `missions.read`; create/update/publish/unpublish/translations PUT — `missions.manage` |
| `/api/v1/admin/mission-runtime-policies` | read — policy read; create/update/publish/unpublish/archive — policy manage |
| `/api/v1/admin/key-rules` | read — key-rules read; create/update — key-rules manage |
| `/api/v1/admin/reward-pools` | read — reward-pools read; create/update — reward-pools manage |
| `/api/v1/admin/geo-zones` | read — geo-zones read; create/update — geo-zones manage |
| `/api/v1/admin/ar-objects` | read — ar-objects read; create/update — ar-objects manage |
| `/api/v1/admin/minigame-profiles` | read — minigame read; create/update/publish/archive — minigame manage |
| `/api/v1/admin/seasons` | read — seasons read; create/update/publish/archive — seasons manage |
| `/api/v1/admin/system-settings` | GET — settings read; PUT non-sensitive — settings manage; sensitive approval request — admin session + approval-mode check; execute — super-admin |
| `/api/v1/admin/players` | list/stats/profile-fields/card/transactions — players read; profile/gas/root/block/unblock — players manage |
| `/api/v1/admin/players/{player_id}` | wallet/inventory/mission/restriction mutation endpoints — admin session + domain-specific permission/approval workflow; execute approval endpoints — super-admin |
| `/api/v1/admin/economy` | audit/transactions/stars-payments — economy read |
| `/api/v1/admin/country-policies` | all four routes — players manage |
| `/api/v1/admin/monitoring` | errors/error-groups/events — players read |
| `/api/v1/admin/geo-audit` | read/detail — geo-audit read; review — geo-audit manage |
| `/api/v1/admin/teams` | read/detail/members/history/invitations/join requests — teams read; force actions — admin session + domain approval; execute — super-admin |
| `/api/v1/admin/withdrawals` | list/batch/payout-batch/rollback/confirm/reject — players read/manage; batch detail/list — players read |

### Эндпоинты без авторизации

`/`, `/health`, Telegram auth/logout, admin login, admin session discovery/logout и
Telegram webhook имеют ожидаемую публичность или отдельную проверку. `/health`
раскрывает лишнее значение окружения (F-04). Webhook в production блокируется без
секрета на старте и повторно проверяет header; в development отсутствие секрета
явно разрешено.

## 4. Находки

### [ВЫСОКО] Deposit poller работает с правами root

- **Где:** `/home/Roman/projects/root-game/deploy/root-game-deposit-poller.service:8-15`
- **Что не так:** systemd запускает `app.deposit_poller` как `User=root`, `Group=root`,
  при этом процесс читает `/opt/root-game/backend/.env` и исполняет код проекта.
  Основной gunicorn работает от `deployer`, то есть для poller выбран более
  привилегированный режим без необходимости.
- **Как эксплуатируется:** при уязвимости в poller-зависимости, цепочке поставки,
  доступном для записи файле проекта или ошибке deployment злоумышленник получает
  выполнение Python-кода с правами root на сервере.
- **Последствия:** полный takeover ОС, чтение/подмена production `.env`, доступ к
  PostgreSQL и секретам, изменение backend и systemd-конфигурации, дальнейшая
  компрометация TON/API credentials.
- **Как проверить:** `systemctl cat root-game-deposit-poller` и
  `ps -o user,group,cmd -C python3`; дополнительно проверить ownership и права
  `/opt/root-game/backend` и `.env` на production. Команда read-only.
- **Как исправить:** запускать poller от отдельного непривилегированного service
  account с минимальными правами на каталог и `.env`; добавить systemd hardening
  (`NoNewPrivileges`, filesystem/network restrictions) после проверки совместимости.
- **Уверенность:** высокая.

### [СРЕДНЕ] В nginx отсутствуют базовые security headers

- **Где:** `/home/Roman/projects/root-game/deploy/nginx.conf:19-104`
- **Что не так:** HTTPS и TLS-версии настроены, но в server/location-блоках нет
  `Strict-Transport-Security`, `Content-Security-Policy`, `X-Frame-Options` и
  `X-Content-Type-Options`.
- **Как эксплуатируется:** браузер не получает защиту от downgrade после первого
  визита, clickjacking и MIME-sniffing; при появлении XSS или ошибочной раздаче
  контента последствия шире. Это defense-in-depth, а не самостоятельный обход
  backend auth.
- **Последствия:** повышается риск clickjacking, content-type confusion и
  компрометации браузерной сессии при другой frontend-ошибке.
- **Как проверить:** `curl -sSI https://<production-host>/` и `curl -sSI
  https://<production-host>/api/...` в production; не выполнять запросы к
  production из этого аудита.
- **Как исправить:** добавить согласованный набор headers на HTTPS server block,
  отдельно проверить совместимость CSP с Telegram Mini App, TON Connect и
  inline/build assets; HSTS включать только после гарантии HTTPS на всех доменах.
- **Уверенность:** высокая для отсутствия headers, средняя для практического
  воздействия без другой browser-уязвимости.

### [СРЕДНЕ] Deposit core не сверяет адрес назначения с deposit wallet

- **Где:** `/home/Roman/projects/root-game/backend/app/deposit_service.py:170-201`
  и `/home/Roman/projects/root-game/backend/app/deposit_poller.py:67-93`
- **Что не так:** poller получает CMS `ton.deposit_wallet` и запрашивает историю
  именно этого адреса, но `process_incoming_transfer()` принимает уже разобранный
  `tx` и проверяет master, сумму и sender mapping, не проверяя
  `tx["to_address"]` против CMS deposit wallet.
- **Как эксплуатируется:** если появится другой вызывающий путь, подменённый
  parser/provider или ошибочная маршрутизация parsed transaction, перевод на
  другой адрес может быть зачислен как депозит. Прямой текущий poller-flow снижает
  вероятность эксплуатации, поэтому это defense-in-depth finding.
- **Последствия:** ошибочное или злонамеренное зачисление ROOT при обходе границы
  `deposit_wallet`; возможная потеря соответствия on-chain funds и ledger.
- **Как проверить:** написать read-only unit scenario с `tx["to_address"]`, не
  равным active `ton.deposit_wallet`, и вызвать `process_incoming_transfer()` в
  disposable test DB; миграции production не запускать.
- **Как исправить:** перед credit проверять и канонизировать destination против
  активной CMS-настройки в самом domain service; poller должен оставаться только
  транспортным источником.
- **Уверенность:** средняя.

### [НИЗКО] Публичный health endpoint раскрывает окружение

- **Где:** `/home/Roman/projects/root-game/backend/app/main.py:779-787`
- **Что не так:** `GET /health` без auth возвращает `settings.app_env` в поле
  `environment`.
- **Как эксплуатируется:** внешний сканер получает подтверждение production/staging/
  development без аутентификации.
- **Последствия:** небольшое информационное раскрытие, упрощающее fingerprinting
  и выбор targeted атак; секреты и stack trace не раскрываются.
- **Как проверить:** `curl -s https://<production-host>/health` только в
  разрешённом окружении; локально маршрут виден в `main.py`.
- **Как исправить:** для публичного health возвращать минимальный стабильный
  статус; environment/version отдавать только во внутренний диагностический
  endpoint или за ограничением доступа.
- **Уверенность:** высокая.

### [НИЗКО] Уязвимые dev-зависимости frontend по `pnpm audit`

- **Где:** `/home/Roman/projects/root-game/package.json:32-43` и lockfile
  (значения lockfile не цитируются согласно token-hygiene правилам).
- **Что не так:** `pnpm audit --json` сообщает 2 high, 4 moderate и 1 low advisory
  для dev-цепочки Vite/`source-map-js`; среди них advisory для `vite 8.3.0` и
  `source-map-js 1.2.1`.
- **Как эксплуатируется:** уязвимость затрагивает преимущественно локальный
  development/build tooling и требует запуска затронутого инструмента или
  соответствующего входа в CI; production bundle не является Vite dev server.
- **Последствия:** риск компрометации developer workstation/CI или утечки файлов
  при небезопасном использовании dev server; прямого runtime-влияния на уже
  собранный frontend не подтверждено.
- **Как проверить:** `pnpm audit --json` (read-only) и `pnpm why vite
  source-map-js`.
- **Как исправить:** обновить зависимости до версий с advisory fix, проверить
  lockfile и повторить build/audit в CI; не запускать Vite dev server на
  недоверенном интерфейсе.
- **Уверенность:** высокая для audit-результата, средняя для фактической
  эксплуатируемости в production.

## 5. Деньги: отдельный разбор

### Начисление и ledger

Все найденные production-пути создания `WalletTransaction` находятся в
`mission_engine.py`, `deposit_service.py`, `withdrawal_service.py`,
`transfer_service.py`, shop/fallback/referral/team services и admin wallet domain
executor. В денежных путях используются положительные суммы, направление задаётся
`transaction_type`, а операции защищены row locks и/или уникальными reference keys.
Триггеры БД и модельный unique index защищают append-only ledger. По коду не найден
подтверждённый путь, позволяющий игроку передать отрицательную сумму или повторно
получить reward простым replay.

### Баланс

`Wallet.available_balance_nano` используется как кэш, а admin economy audit
сверяет его с `SUM(credit)-SUM(debit)` по ledger. В legacy ROOT-полях сохраняется
целочисленный floor; nano-поле является точным каналом. Риск рассинхронизации при
ошибке dual-write остаётся операционным, но автоматический exploit не подтверждён.

### Заявка и холд

`POST /api/v1/me/withdrawals` (`main.py:1235-1259`) принимает Pydantic payload и
игровую cookie. `withdrawal_service.py:207-296` под row lock проверяет CMS flag,
адрес, сумму, restriction, дневной лимит и баланс, затем атомарно списывает холд
и создаёт immutable debit. `request_id` и unique index закрывают повтор заявки и
гонку idempotency.

### Батч и попытка

`payout_batch_service.py:308-427` использует один открытый batch через partial
unique index, повторно блокирует pending заявки и создаёт отдельную `sending`
attempt с уникальным uint64 `query_id`. `uq_payout_attempts_no_second_send`
не позволяет создать вторую active attempt; rollback переводит `sending` и `sent`
в `failed`, чтобы заявки не застревали.

### Подпись, адрес, сумма и доставка

`payout_confirm_service.py:142-300` читает CMS key/address, проверяет Ed25519 BOC,
sender через `same_address`, query_id, точную nano-сумму и recipient. Затем
`ton_payout_lookup.py:122-253` при известном recipient jetton wallet ищет успешный
входящий `internal_transfer` с тем же query_id и точной суммой. `delivered=False`,
отсутствие tx hash или недоступность API не переводят заявку в confirmed.

### Откат и зависания

`payout_rollback_service.py:81-209` не откатывает confirmed и поддерживает
частично подтверждённые batch. `retention.py:125-153` добавляет timeout rollback.
Остаётся operational risk: каждый из трёх gunicorn workers запускает свой
APScheduler (`main.py:181-193`, `retention.py:94-138`), но DB locks/status checks
делают повторный rollback идемпотентным. Deposit poller, напротив, вынесен в
отдельный systemd process; его проблема — права root (F-01).

## 6. Что проверено и в порядке

- Telegram initData: HMAC через bot token, `compare_digest`, duplicate-key reject,
  `auth_date` future skew и max age.
- Game session: HMAC-signed cookie, `iat`/`exp`, HttpOnly, Secure в production,
  SameSite=Lax; player id берётся из cookie, а не URL.
- Admin: Argon2id, server-side hashed sessions, expiry, logout/deactivation revoke,
  generic errors, permission dependencies и super-admin separation.
- Admin approvals: dedicated executors, expiry, initiator restriction, row locks,
  idempotency и immutable audit.
- SQL injection: raw f-string SQL/опасная конкатенация не найдены; SQLAlchemy
  expressions используют bind parameters.
- XSS: `dangerouslySetInnerHTML`, `innerHTML` и `document.cookie` в `src/` не
  найдены; localStorage хранит UI/draft state, не session token.
- TON BOC: size cap, base64 validation, V4/V5 parsing, Ed25519, exact amount,
  query_id uniqueness, sender/recipient canonical address comparison.
- Withdrawal: hold, daily limit, restricted filter, unique request id, active
  attempt barrier, partial payment и delivered check.
- Deposit: master check, minimum, tx hash/idempotency, sender wallet mapping,
  wallet row lock. Отмечена только отсутствующая target-address проверка (F-03).
- Exception handling: пользовательские 5xx не получают traceback/SQL/path; AppError
  хранит redacted metadata.
- Frontend TypeScript build и lint: ошибок типов/линтера нет.

## 7. Не проверено / требует решения владельца

- Production runtime permissions, ownership каталогов, реальная systemd unit,
  firewall, PostgreSQL роли и права `.env`: в репозитории есть unit/config, но нет
  доступа к production host.
- Реальная TLS-конфигурация certbot и фактические response headers: проверен
  только versioned nginx template; production URL намеренно не вызывался.
- Реальное содержимое `.env`, `wallets.toml`, database и logs: не читалось, чтобы
  не раскрыть секреты и запрещённые binary/config artifacts.
- Полный dependency CVE triage backend: `requirements.txt` просмотрен, но
  network-based vulnerability database для Python packages не запускалась.
- Production TON API/Tonapi TLS, response authenticity и operator DNS: код имеет
  HTTPS defaults/timeouts, но не проверялись реальные endpoint/proxy certificates.
- PostgreSQL-only concurrency semantics в живой БД: 10 тестов пропущены без
  локального PostgreSQL; SQLite suite зелёный, но SQLite не моделирует все row-lock
  свойства PostgreSQL.
- Реальная геолокационная anti-spoof/trusted verifier интеграция: код и contract
  проверены, но физический device/GPS threat model требует отдельного testnet/device
  аудита.
- Проверка git history на значения секретов не выполнялась через вывод patch
  содержимого; проверены только tracked secret-like paths и отсутствие секретных
  файлов в tracked names.

## 8. Приоритетный план исправлений

1. **Немедленно:** перевести deposit poller с `root` на отдельного service user,
   проверить ownership `.env`, каталогов и systemd hardening на production.
2. **Высокий приоритет:** добавить и протестировать nginx security headers;
   CSP сначала в report-only, затем enforce после проверки TON Connect/Telegram.
3. **Средний приоритет:** добавить проверку `to_address == active deposit wallet`
   в `deposit_service`, независимо от того, кто вызывает domain service.
4. **Средний приоритет:** убрать `environment` из публичного `/health` либо закрыть
   расширенный health endpoint внутренней сетью.
5. **Планово:** обновить frontend dev dependencies по advisory fix и закрепить
   `pnpm audit`/version policy в CI.
6. **Отдельный эксплуатационный этап:** прогнать PostgreSQL concurrency tests,
   проверить реальные headers/permissions и провести device-level geo/TON review.

## Методика и результаты проверок

- `cd /home/Roman/projects/root-game/backend && ./.venv/bin/python -m unittest discover -s tests -p 'test_*.py'` — **1079 tests, OK, 10 skipped**, 224.109 s.
- `cd /home/Roman/projects/root-game && npx tsc -b` — **exit 0**.
- `cd /home/Roman/projects/root-game && npx oxlint src/` — **0 errors, 44 warnings**.
- `cd /home/Roman/projects/root-game && pnpm audit --json` — **0 critical, 2 high, 4 moderate, 1 low**, все advisory в frontend dev dependency chain.
- AST-инвентаризация маршрутов: 186 записей включая middleware/handlers; admin/game
  маршруты сопоставлены с auth dependencies.
- Git status до аудита: clean; после аудита изменён только этот отчёт.