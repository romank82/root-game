from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Any


class PublicContentValidationError(ValueError):
    pass

FORBIDDEN_KEYS = frozenset({
    "validationconfig", "validation_config", "validator", "acceptedanswers",
    "correctsequence", "correctcombination", "answerhash", "answer_hash", "solutionkey", "solution_key",
    "hiddenpuzzlestate", "hidden_puzzle_state", "walletbalanceafter",
    "wallet_balance_after", "awardamount", "award_amount", "inventorymutation",
    "inventory_mutation", "completionflag", "completion_flag", "entryfee",
    "entry_fee", "approvaldata", "approval_data", "auditdata", "audit_data",
    "adminmetadata", "admin_metadata",
})


def _fail(path: str, message: str) -> None:
    raise PublicContentValidationError(f"{path}: {message}")


def _object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    return value


def _only(value: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _fail(path, f"contains unsupported keys: {', '.join(unknown)}")


def _text(value: Any, path: str, maximum: int = 20_000) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        _fail(path, f"must be a non-empty string of at most {maximum} characters")


def _number(value: Any, path: str, minimum: float, maximum: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum:
        _fail(path, f"must be a number between {minimum} and {maximum}")


def _integer(value: Any, path: str, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        _fail(path, f"must be an integer between 1 and {maximum}")


def _integer_between(value: Any, path: str, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        _fail(path, f"must be an integer between {minimum} and {maximum}")


def _schema_version_one(value: Any, path: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != 1:
        _fail(path, "must equal integer 1")


def _ambiguity_key(value: str) -> str:
    """Fold a display symbol for duplicate detection.

    Mirrors ``app/runtime_policy_contract._ambiguity_key``: NFKC folds full-width
    and compatibility forms; casefold folds case. This intentionally does not
    cover visual lookalikes across scripts (O/0, l/1, I/1); those are checked
    separately in the cipher alphabet rules.
    """
    return unicodedata.normalize("NFKC", value).casefold()


# Pairs that must never coexist in a public cipher alphabet because the player
# cannot reliably tell them apart in the drum UI.
VISUAL_CONFLICT_PAIRS = frozenset({
    ("o", "0"),
    ("l", "1"),
    ("i", "1"),
})


def _visual_conflict(a: str, b: str) -> bool:
    """Return True when any character of ``a`` and ``b`` look alike."""
    a_chars = {char.casefold() for char in a}
    b_chars = {char.casefold() for char in b}
    for left in a_chars:
        for right in b_chars:
            if (left, right) in VISUAL_CONFLICT_PAIRS or (right, left) in VISUAL_CONFLICT_PAIRS:
                return True
    return False


def _reject_hidden(value: Any, path: str = "content") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                _fail(path, "object keys must be strings")
            if key.casefold() in FORBIDDEN_KEYS:
                _fail(f"{path}.{key}", "is server-only and prohibited in public content")
            _reject_hidden(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_hidden(nested, f"{path}[{index}]")


def validate_segment_content(content: Any) -> None:
    _reject_hidden(content)
    root = _object(content, "segment.content")
    _only(root, {"schemaVersion", "presentation", "location", "arScene"}, "segment.content")
    _schema_version_one(
        root.get("schemaVersion"),
        "segment.content.schemaVersion",
    )
    presentation = _object(root.get("presentation"), "segment.content.presentation")
    _only(presentation, {"code", "type"}, "segment.content.presentation")
    _text(presentation.get("code"), "segment.content.presentation.code", 128)
    _text(presentation.get("type"), "segment.content.presentation.type", 128)
    location = _object(root.get("location"), "segment.content.location")
    _only(location, {"searchRadiusMeters", "safeScanRadiusMeters", "safeScanPoint"}, "segment.content.location")
    _number(location.get("searchRadiusMeters"), "segment.content.location.searchRadiusMeters", 1, 100_000)
    _number(location.get("safeScanRadiusMeters"), "segment.content.location.safeScanRadiusMeters", 1, 100_000)
    if location["searchRadiusMeters"] < location["safeScanRadiusMeters"]:
        _fail("segment.content.location", "searchRadiusMeters must be >= safeScanRadiusMeters")
    point = _object(location.get("safeScanPoint"), "segment.content.location.safeScanPoint")
    _only(point, {"latitude", "longitude"}, "segment.content.location.safeScanPoint")
    _number(point.get("latitude"), "segment.content.location.safeScanPoint.latitude", -90, 90)
    _number(point.get("longitude"), "segment.content.location.safeScanPoint.longitude", -180, 180)
    scene = _object(root.get("arScene"), "segment.content.arScene")
    _only(
        scene,
        {
            "scenePreset",
            "scanHoldDurationMs",
            "visibleFaces",
            "qrMode",
            # Тип AR-объекта (ARObjectsEditor): objectType — канонический ключ
            # admin API, object_type — ключ, читаемый игровым фронтом.
            "objectType",
            "object_type",
        },
        "segment.content.arScene",
    )
    _text(scene.get("scenePreset"), "segment.content.arScene.scenePreset", 128)
    _integer(
        scene.get("scanHoldDurationMs"),
        "segment.content.arScene.scanHoldDurationMs",
        60_000,
    )
    if "visibleFaces" in scene:
        visible_faces = scene["visibleFaces"]
        if not isinstance(visible_faces, list) or not 1 <= len(visible_faces) <= 32:
            _fail(
                "segment.content.arScene.visibleFaces",
                "must be a list containing 1 to 32 public identifiers",
            )
        for index, face in enumerate(visible_faces):
            _text(face, f"segment.content.arScene.visibleFaces[{index}]", 128)
    if "qrMode" in scene:
        _text(scene["qrMode"], "segment.content.arScene.qrMode", 128)


# Bounds for the public cipher mission schema version 1
# (docs/minigame-cipher.md, "Схема данных").
CIPHER_DRUM_COUNT_MIN = 2
CIPHER_DRUM_COUNT_MAX = 12
CIPHER_FALSE_CHOICES_MIN = 0
CIPHER_FALSE_CHOICES_MAX = 10
CIPHER_ALPHABET_MAX = 64
CIPHER_SYMBOL_MAX_LENGTH = 2
CIPHER_COMBINATION_MAX = 64
CIPHER_TIME_LIMIT_MIN = 1
CIPHER_TIME_LIMIT_MAX = 3600


def _validate_cipher_ui(
    ui: Mapping[str, Any], *, require_full_ui: bool = True
) -> None:
    """Validate public cipher-mission content.ui (schemaVersion 1)."""
    if not require_full_ui:
        # Sprint 8.17.16: для миссий с published-профилем старые поля
        # content.ui не требуются (настройки в profile.settings).
        return
    drum_count = ui.get("drumCount")
    _integer_between(drum_count, "mission.content.ui.drumCount", CIPHER_DRUM_COUNT_MIN, CIPHER_DRUM_COUNT_MAX)

    false_choices = ui.get("falseChoicesPerDrum")
    _integer_between(false_choices, "mission.content.ui.falseChoicesPerDrum", CIPHER_FALSE_CHOICES_MIN, CIPHER_FALSE_CHOICES_MAX)

    alphabet = ui.get("alphabet")
    if not isinstance(alphabet, list) or not 1 <= len(alphabet) <= CIPHER_ALPHABET_MAX:
        _fail(
            "mission.content.ui.alphabet",
            "must be a list containing 1 to 64 display symbols",
        )
    if len(alphabet) < drum_count + false_choices:
        _fail(
            "mission.content.ui.alphabet",
            "must contain at least drumCount + falseChoicesPerDrum display symbols",
        )
    seen_keys: set[str] = set()
    seen_symbols: list[str] = []
    for index, symbol in enumerate(alphabet):
        path = f"mission.content.ui.alphabet[{index}]"
        if (
            not isinstance(symbol, str)
            or not symbol.strip()
            or len(symbol) > CIPHER_SYMBOL_MAX_LENGTH
        ):
            _fail(path, "must be a non-empty display symbol of at most 2 characters")
        key = _ambiguity_key(symbol)
        if key in seen_keys:
            _fail(
                "mission.content.ui.alphabet",
                "must not contain visually or case equivalent entries",
            )
        for previous in seen_symbols:
            if _visual_conflict(symbol, previous):
                _fail(
                    "mission.content.ui.alphabet",
                    "must not contain visually conflicting symbols",
                )
        seen_keys.add(key)
        seen_symbols.append(symbol)

    combination = ui.get("combination")
    if not isinstance(combination, str) or not combination.strip() or len(combination) > CIPHER_COMBINATION_MAX:
        _fail(
            "mission.content.ui.combination",
            "must be a non-empty string of at most 64 characters",
        )

    if "timeLimitSeconds" in ui and ui["timeLimitSeconds"] is not None:
        _integer_between(
            ui["timeLimitSeconds"],
            "mission.content.ui.timeLimitSeconds",
            CIPHER_TIME_LIMIT_MIN,
            CIPHER_TIME_LIMIT_MAX,
        )


def validate_mission_content(
    mission_type: str, content: Any, *, require_full_cipher_ui: bool = True
) -> None:
    _reject_hidden(content)
    root = _object(content, "mission.content")
    _only(root, {"schemaVersion", "ui", "arScene"}, "mission.content")
    _schema_version_one(
        root.get("schemaVersion"),
        "mission.content.schemaVersion",
    )
    ui = _object(root.get("ui"), "mission.content.ui")
    if "arScene" in root:
        scene = _object(root["arScene"], "mission.content.arScene")
        _only(
            scene,
            {
                "scenePreset",
                "scanHoldDurationMs",
                "visibleFaces",
                "qrMode",
                # Тип AR-объекта (ARObjectsEditor): objectType — канонический ключ
                # admin API, object_type — ключ, читаемый игровым фронтом.
                "objectType",
                "object_type",
            },
            "mission.content.arScene",
        )
    if mission_type == "text_answer":
        allowed = {"label", "question", "inputPlaceholder", "successTitle", "successText", "rewardPreview"}
        text_keys = allowed - {"rewardPreview"}
    elif mission_type == "code_repair":
        allowed = {"label", "instruction", "blocks", "maxBlocks", "lineNumber", "placeholder", "wrongAnswerText", "rewardPreview"}
        text_keys = {"label", "instruction", "lineNumber", "placeholder", "wrongAnswerText"}
    elif mission_type == "team":
        allowed = {
            "label",
            "instruction",
            "joinTitle",
            "joinText",
            "waitingText",
            "readyText",
            "activeText",
            "successTitle",
            "failureText",
            "rewardPreview",
        }
        text_keys = allowed - {"rewardPreview"}
    elif mission_type == "cipher":
        allowed = {
            "label",
            "instruction",
            "drumCount",
            "alphabet",
            "falseChoicesPerDrum",
            "combination",
            "timeLimitSeconds",
            "successTitle",
            "successText",
            "wrongAnswerText",
            "rewardPreview",
        }
        text_keys = {"label", "instruction", "combination", "successTitle", "successText", "wrongAnswerText"}
    elif mission_type == "memory":
        # Sprint Memory-2d: публичный контент memory-миссии — только тексты.
        # Сложность (grid_size/time_limit_seconds) живёт в профиле мини-игры,
        # раскладка карточек и лимит времени — в серверной сессии
        # (mission.memorySession); в content.ui их нет.
        allowed = {
            "label",
            "instruction",
            "successTitle",
            "successText",
            "wrongAnswerText",
            "rewardPreview",
        }
        text_keys = allowed - {"rewardPreview"}
    else:
        _fail("mission.missionType", "must be text_answer, code_repair, team, cipher, or memory for public content schemaVersion 1")
    _only(ui, allowed, "mission.content.ui")
    for key in text_keys:
        if key in ui:
            _text(ui[key], f"mission.content.ui.{key}")
    if "blocks" in ui:
        blocks = ui["blocks"]
        if not isinstance(blocks, list) or not 1 <= len(blocks) <= 100:
            _fail("mission.content.ui.blocks", "must be a list containing 1 to 100 public blocks")
        for index, block in enumerate(blocks):
            _text(block, f"mission.content.ui.blocks[{index}]", 2_000)
    if "maxBlocks" in ui:
        _integer(ui["maxBlocks"], "mission.content.ui.maxBlocks", 100)
    if "rewardPreview" in ui:
        preview = _object(ui["rewardPreview"], "mission.content.ui.rewardPreview")
        _only(preview, {"text"}, "mission.content.ui.rewardPreview")
        _text(preview.get("text"), "mission.content.ui.rewardPreview.text", 512)
    if mission_type == "cipher":
        _validate_cipher_ui(ui, require_full_ui=require_full_cipher_ui)
