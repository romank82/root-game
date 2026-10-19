# Мини-игра Cipher (кодовый замок с барабанами)

## Актуальная модель (с 2026-10-19, Sprint 8.17)

Настройки cipher живут в профиле мини-игры (таблица minigame_profiles, поле settings JSON), а НЕ в content.ui миссии. Миссия ссылается на профиль через mission.minigame_profile_id. Движок читает profile.settings через реестр обработчиков (см. docs/roadmap-detailed.md, Спринт 8.17, «Архитектурное решение: реестр обработчиков мини-игр»).

Состав profile.settings для cipher (whitelist, admin_minigame_profiles.py:45-49):
- drumCount: int 2..12
- falseChoicesPerDrum: int 0..36
- timeLimitSeconds: int 1..3600 | null

В профиле НЕТ alphabet и combination — алфавит фиксированный (A-Z + 0-9, 36 символов), правильный код генерируется на backend случайно (длина = drumCount). Тексты (label, instruction, successTitle, successText, wrongAnswerText) остаются в миссии.

Legacy (миссии без профиля, minigame_profile_id IS NULL): работают по старой схеме — параметры в content.ui, валидация через validation_config.correctCombination. Нужны только для test-cipher-01/02 до миграции (8.17.11).

Универсальная мини-игра. Применяется к заданиям любого слоя (solo / team / story),
когда админ выбирает `mission_type = "cipher"`. Не привязана к конкретному режиму.

## 1. Идея

Игрок видит правильную комбинацию символов и должен собрать её на нескольких
барабанах (как кодовый замок). Символы на барабанах прокручиваются свайпом.
Задача — на внимательность и скорость, не на разгадку.

Сложность определяется админом: количеством барабанов, размером алфавита,
количеством ложных символов рядом с правильным, лимитом времени.

## 2. Схема данных

### content.ui (публичная, приходит на фронт через bootstrap миссии)

> ⚠️ Legacy (до Sprint 8.17). Для новых миссий параметры cipher живут в profile.settings (см. «Актуальная модель» выше). Этот раздел описывает старый формат, который поддерживается только для миссий без профиля.

```json
{
  "schemaVersion": 1,
  "ui": {
    "label": "КОДОВЫЙ ЗАМОК",
    "instruction": "Набери комбинацию на барабанах",
    "drumCount": 4,
    "alphabet": ["R", "O", "T", "G", "A", "M", "E", "1", "2", "3"],
    "falseChoicesPerDrum": 3,
    "combination": "ROOT",
    "timeLimitSeconds": 60,
    "successTitle": "Замок открыт",
    "successText": "Код собран.",
    "wrongAnswerText": "Неверно, попробуй ещё.",
    "rewardPreview": { "text": "100 ROOT" }
  }
}
```

Поля:
- `drumCount`: int, 2..12 — количество барабанов.
- `alphabet`: string[], уникальные символы, длина >= drumCount + falseChoicesPerDrum,
  каждый символ длиной 1-2 знака, без визуально конфликтующих (O/0, l/1, I/1).
- `falseChoicesPerDrum`: int, 0..10 — сколько ложных символов рядом с правильным.
- `combination`: string — правильная комбинация, показывается игроку на экране
  (например "ROOT"). НЕ является секретом: игра на внимательность и скорость,
  а не на разгадку.
- `timeLimitSeconds`: int | null, 1..3600 — лимит времени (null = без лимита).
- `label`, `instruction`, `successTitle`, `successText`, `wrongAnswerText`: string.
- `rewardPreview`: { text: string }.

### validation_config (в БД, на фронт не уходит)

```json
{
  "validator": "cipher_match",
  "correctCombination": ["R", "O", "O", "T"]
}
```

Правила:
- `correctCombination`: string[], длина == drumCount, каждый элемент ∈ alphabet.
  Должна совпадать с combination из content.ui (admin вводит один раз,
  backend формирует оба поля).
- Сравнение: sequence == correctCombination (case-sensitive, по порядку).

### Правила anti-ambiguity

Все символы в alphabet визуально однозначны. Переиспользовать логику из
runtime_policy_contract.py (ambiguity key). Запрещённые пары: O/0, l/1, I/1
и аналогичные визуально неотличимые.

## 3. Поток игрока

1. Игрок в AR-камере видит куб.
2. Тап по кубу (условия: |delta| < 15°, distance < zone_radius).
3. Фронт берёт content из mission.content (bootstrap, без запросов на сервер).
4. Открывается CipherScreen (камера скрыта).
5. Игрок видит:
   - label / instruction сверху;
   - правильную комбинацию крупно (показана всегда);
   - N барабанов (свайп вверх/вниз);
   - таймер (если timeLimitSeconds задан);
   - кнопку "ГОТОВО" (активна, когда все барабаны остановлены на символе).
6. Игрок собирает комбинацию, жмёт "ГОТОВО".
7. submitMission(missionId, { sequence: [...] }).

Результаты:
- ВЕРНО: награда по существующему механизму (attemptMultipliers применятся
  автоматически). Возврат в Контур.
- НЕВЕРНО: показывается wrongAnswerText, попытка уменьшается. Награда при
  следующем успехе: 100% / 50% / 25% (существующие attemptMultipliers).
- ПОПЫТКИ ИСЧЕРПАНЫ (3): провал, миссия в cooldown (существующий механизм).
- ВРЕМЯ ВЫШЛО: провал, возврат в Контур.

## 4. UI-детали

### Показ правильной комбинации

Всегда видна сверху, крупно, явно. Это не загадка — это внимательность + скорость.

### Барабаны

- Вертикальные ленты символов.
- Свайп вверх/вниз (touchstart / touchmove / touchend).
- CSS touch-action: none на лентах, чтобы не дёргать скролл страницы.
- Видно 3 символа одновременно: текущий по центру, соседние сверху и снизу.
- Текущий символ выделен рамкой.
- Между барабанами — разделители.

### Набор символов в каждом барабане

- Правильный символ (correctCombination[i]) + falseChoicesPerDrum ложных,
  случайно выбранных из alphabet, без повторов внутри барабана.
- Порядок символов случайный, правильный не всегда по центру.
- Разные ложные символы на каждом барабане.

### Таймер

Если timeLimitSeconds задан — обратный отсчёт сверху. Последние 10 секунд — красный.
По истечении — экран "Время вышло", возврат в Контур.

### Кнопка "ГОТОВО"

Заблокирована, пока хотя бы один барабан не остановлен на символе (все
currentIndex инициализированы, но кнопка активна, когда игрок явно выбрал символ —
по решению фронта; минимально: активна всегда, сервер проверит).

## 5. Backend — что надо

> ⚠️ Требования ниже — для legacy-миссий без профиля (minigame_profile_id IS NULL).
> Для миссий с профилем combination в content.ui НЕ нужна: правильный код
> генерируется на backend случайно (длина = drumCount), проверка ответа —
> сравнение sequence с cipherSession.correct_code (см. реестр обработчиков в
> roadmap-detailed.md, Sprint 8.17).

- content_contract.py: добавить mission_type == "cipher" в validate_mission_content.
  Схема — как в разделе 2. Переиспользовать anti-ambiguity из runtime_policy_contract.
- content_contract.py: в схеме cipher поле combination обязательно и непустое —
  только для legacy-миссий без профиля. Админ заполняет одно поле, backend
  копирует его в content.ui.combination и в validation_config.correctCombination.
- mission_engine._validate_submission: добавить validator == "cipher_match".
  Простое сравнение sequence == correctCombination.
- admin_missions.py: publish-валидация для cipher — correctCombination непустой,
  длина == drumCount, все элементы ∈ alphabet.
- scan-qr и qr-payload: НЕ трогаем, помечаем deprecated (см. раздел 8).
- submit: НЕ трогаем (кроме нового валидатора).
- challenge_policy_json: НЕ трогаем.

## 6. Admin UI

В редакторе миссии при mission_type = "cipher":

Для миссий с профилем (8.17.18, в работе): поля drumCount/alphabet/
falseChoicesPerDrum/«Правильная комбинация» НЕ показываются. Остаются:
- dropdown «Профиль мини-игры» (выбор из minigame_profiles, поле minigame_profile_id);
- label / instruction / successTitle / successText / wrongAnswerText / rewardPreview —
  как у code_repair.

Для legacy-миссий без профиля (старый редактор, до 8.17.18):
- drumCount — число.
- alphabet — список символов (чипы или через запятую).
- falseChoicesPerDrum — число.
- timeLimitSeconds — число или "без лимита".
- "Правильная комбинация" — одно поле, строка (например "ROOT"). Backend
  раскидывает её в content.ui.combination и validation_config.correctCombination.
- label / instruction / successTitle / successText / wrongAnswerText / rewardPreview —
  как у code_repair.

Валидация при сохранении:
- len(correctCombination) == drumCount.
- Каждый символ correctCombination ∈ alphabet.
- Anti-ambiguity для alphabet.

## 7. Frontend

- Новый компонент src/components/screens/CipherScreen.tsx.
- Пропсы: content (из mission.content), missionId, onSubmit(sequence), onClose().
- Состояние: drums: Array<{ symbols, currentIndex }>, timeLeft, submitting, error.
- Свайп-логика: touchstart / touchmove / touchend на каждой ленте.
- Сбор sequence = drums.map(d => d.symbols[d.currentIndex]).
- Отправка через submitMission(missionId, { sequence }).
- Интеграция в CameraTestScreen: после тапа по кубу (без scan-qr) — если
  mission.missionType === 'cipher' — рендерим CipherScreen вместо камеры.

## 8. Статус QR (deprecated)

QR больше не используется в solo-flow.
- backend/app/qr_service.py — оставить, пометить DEPRECATED в docstring.
- GET /missions/{id}/qr-payload и POST /missions/{id}/scan-qr — оставить,
  пометить deprecated в docstring.
- Frontend: удалить рендер QR на кубе, jsQR-сканер, qrPayload state,
  getMissionQrPayload и scanMissionQr вызовы. Функции в engineApi.ts оставить
  с пометкой @deprecated.

## 9. Roadmap / audit

- Sprint 8.13 "Мини-игра Cipher" — новый спринт в roadmap-detailed.
- Sprint 8.7 "Индивидуальный QR" — пометить устаревшим (QR отменён).
- Sprint 8.8 "QR-скан + запуск мини-игры" — переформулировать как
  "Мини-игра после активации куба" (без QR).
- Обновление в audit-2026-10-04.md при закрытии спринта.

## 10. Что НЕ входит

- LocationProof (Sprint 8.5) — отдельно.
- Античит (Sprint 8.9) — отдельно.
- Team-flow для cipher — отдельно (контракт уже есть).
- Удаление qr_service.py — не делаем, оставляем deprecated.
