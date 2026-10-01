from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class PublicContentValidationError(ValueError):
    pass

FORBIDDEN_KEYS = frozenset({
    "validationconfig", "validation_config", "validator", "acceptedanswers",
    "correctsequence", "answerhash", "answer_hash", "solutionkey", "solution_key",
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


def _schema_version_one(value: Any, path: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != 1:
        _fail(path, "must equal integer 1")


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
        {"scenePreset", "scanHoldDurationMs", "visibleFaces", "qrMode"},
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


def validate_mission_content(mission_type: str, content: Any) -> None:
    _reject_hidden(content)
    root = _object(content, "mission.content")
    _only(root, {"schemaVersion", "ui"}, "mission.content")
    _schema_version_one(
        root.get("schemaVersion"),
        "mission.content.schemaVersion",
    )
    ui = _object(root.get("ui"), "mission.content.ui")
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
    else:
        _fail("mission.missionType", "must be text_answer, code_repair, or team for public content schemaVersion 1")
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
