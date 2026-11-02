from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


class GeoTeamConfigurationError(ValueError):
    """Safe validation failure for protected geo/team CMS configuration."""


TEAM_MISSION_TYPE = "team"
CIPHER_CHALLENGE_TYPE = "cipher"
LOCAL_MATCHMAKING_MODE = "local_matchmaking"
PRODUCTION_LOCATION_PROOF_PROVIDER = "production_verifier"
DEVELOPMENT_LOCATION_PROOF_PROVIDER = "dev_mock"

_ALLOWED_ROOT_KEYS = {
    "schemaVersion",
    "team",
    "economy",
    "attempts",
    "geo",
    "activation",
    "fallback",
}
_ALLOWED_TEAM_KEYS = {"matchmakingMode", "minMembers", "maxMembers"}
_ALLOWED_ECONOMY_KEYS = {"entryFeeRootAtomic", "requiredItems"}
_ALLOWED_ITEM_REQUIREMENT_KEYS = {"itemId", "quantity"}
_ALLOWED_ATTEMPTS_KEYS = {"maxAttempts", "rewardMultipliers"}
_ALLOWED_GEO_KEYS = {
    "zoneId",
    "proofFreshnessSeconds",
    "pairwiseProximityMeters",
    # Optional: лимит «рядом» при create/join в метрах. Отсутствие ключа —
    # не ошибка (существующие миссии остаются валидными); runtime-фолбэк —
    # 50000 (team_missions_service.DEFAULT_JOIN_PROXIMITY_METERS).
    "joinProximityMeters",
    "periodicCheckPolicy",
}
_ALLOWED_PERIODIC_POLICY_KEYS = {"mode", "intervalSeconds"}
_ALLOWED_ACTIVATION_KEYS = {"challengeType", "deadlineSeconds", "qrMode"}
_ALLOWED_FALLBACK_KEYS = {"enabled", "quotaPerPlayer", "offerId"}


def _fail(_: str) -> None:
    # Do not echo CMS values, QR material, answers, or free text in errors.
    raise GeoTeamConfigurationError(
        "Protected geo/team mission configuration is invalid."
    )


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path)
    return value


def _only(value: Mapping[str, Any], allowed: set[str], path: str) -> None:
    if set(value) - allowed:
        _fail(path)


def _required(value: Mapping[str, Any], key: str, path: str) -> Any:
    if key not in value:
        _fail(f"{path}.{key}")
    return value[key]


def _integer(value: Any, path: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(path)
    if not minimum <= value <= maximum:
        _fail(path)
    return value


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        _fail(path)
    return value


def _nonempty_text(value: Any, path: str, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        _fail(path)
    return value


def _multipliers(value: Any, path: str, max_attempts: int) -> list[float]:
    if not isinstance(value, list) or len(value) != max_attempts:
        _fail(path)

    normalized: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            _fail(path)
        number = float(item)
        if not 0 <= number <= 1:
            _fail(path)
        normalized.append(number)

    if normalized[0] != 1.0:
        _fail(path)
    if any(
        normalized[index] > normalized[index - 1]
        for index in range(1, len(normalized))
    ):
        _fail(path)
    return normalized


def validate_team_mission_validation_config(value: Any) -> dict[str, Any]:
    """
    Validate protected CMS configuration for the future team/cipher vertical.

    This function never validates raw device location evidence, QR payloads,
    answers, or other runtime secrets. Those belong to server-only runtime
    records and trusted verifier integrations.
    """
    root = _mapping(value, "validationConfig")
    _only(root, _ALLOWED_ROOT_KEYS, "validationConfig")

    if _integer(
        _required(root, "schemaVersion", "validationConfig"),
        "validationConfig.schemaVersion",
        1,
        1,
    ) != 1:
        _fail("validationConfig.schemaVersion")

    team = _mapping(
        _required(root, "team", "validationConfig"),
        "validationConfig.team",
    )
    _only(team, _ALLOWED_TEAM_KEYS, "validationConfig.team")
    if _nonempty_text(
        _required(team, "matchmakingMode", "validationConfig.team"),
        "validationConfig.team.matchmakingMode",
    ) != LOCAL_MATCHMAKING_MODE:
        _fail("validationConfig.team.matchmakingMode")
    min_members = _integer(
        _required(team, "minMembers", "validationConfig.team"),
        "validationConfig.team.minMembers",
        2,
        100,
    )
    max_members = _integer(
        _required(team, "maxMembers", "validationConfig.team"),
        "validationConfig.team.maxMembers",
        2,
        100,
    )
    if min_members > max_members:
        _fail("validationConfig.team")

    economy = _mapping(
        _required(root, "economy", "validationConfig"),
        "validationConfig.economy",
    )
    _only(economy, _ALLOWED_ECONOMY_KEYS, "validationConfig.economy")
    _integer(
        _required(economy, "entryFeeRootAtomic", "validationConfig.economy"),
        "validationConfig.economy.entryFeeRootAtomic",
        0,
        2_147_483_647,
    )
    required_items = _required(
        economy, "requiredItems", "validationConfig.economy"
    )
    if not isinstance(required_items, list) or len(required_items) > 100:
        _fail("validationConfig.economy.requiredItems")
    seen_item_ids: set[str] = set()
    for index, item in enumerate(required_items):
        requirement = _mapping(
            item,
            f"validationConfig.economy.requiredItems[{index}]",
        )
        _only(
            requirement,
            _ALLOWED_ITEM_REQUIREMENT_KEYS,
            f"validationConfig.economy.requiredItems[{index}]",
        )
        item_id = _nonempty_text(
            _required(
                requirement,
                "itemId",
                f"validationConfig.economy.requiredItems[{index}]",
            ),
            f"validationConfig.economy.requiredItems[{index}].itemId",
            64,
        )
        if item_id in seen_item_ids:
            _fail("validationConfig.economy.requiredItems")
        seen_item_ids.add(item_id)
        _integer(
            _required(
                requirement,
                "quantity",
                f"validationConfig.economy.requiredItems[{index}]",
            ),
            f"validationConfig.economy.requiredItems[{index}].quantity",
            1,
            2_147_483_647,
        )

    attempts = _mapping(
        _required(root, "attempts", "validationConfig"),
        "validationConfig.attempts",
    )
    _only(attempts, _ALLOWED_ATTEMPTS_KEYS, "validationConfig.attempts")
    max_attempts = _integer(
        _required(attempts, "maxAttempts", "validationConfig.attempts"),
        "validationConfig.attempts.maxAttempts",
        1,
        10,
    )
    _multipliers(
        _required(
            attempts,
            "rewardMultipliers",
            "validationConfig.attempts",
        ),
        "validationConfig.attempts.rewardMultipliers",
        max_attempts,
    )

    geo = _mapping(
        _required(root, "geo", "validationConfig"),
        "validationConfig.geo",
    )
    _only(geo, _ALLOWED_GEO_KEYS, "validationConfig.geo")
    _nonempty_text(
        _required(geo, "zoneId", "validationConfig.geo"),
        "validationConfig.geo.zoneId",
        128,
    )
    _integer(
        _required(
            geo,
            "proofFreshnessSeconds",
            "validationConfig.geo",
        ),
        "validationConfig.geo.proofFreshnessSeconds",
        1,
        86_400,
    )
    _integer(
        _required(
            geo,
            "pairwiseProximityMeters",
            "validationConfig.geo",
        ),
        "validationConfig.geo.pairwiseProximityMeters",
        1,
        100_000,
    )
    # Optional: если ключа нет — валидация проходит (runtime-фолбэк 50000).
    if "joinProximityMeters" in geo:
        _integer(
            geo["joinProximityMeters"],
            "validationConfig.geo.joinProximityMeters",
            1,
            100_000,
        )
    periodic = _mapping(
        _required(
            geo,
            "periodicCheckPolicy",
            "validationConfig.geo",
        ),
        "validationConfig.geo.periodicCheckPolicy",
    )
    _only(
        periodic,
        _ALLOWED_PERIODIC_POLICY_KEYS,
        "validationConfig.geo.periodicCheckPolicy",
    )
    periodic_mode = _nonempty_text(
        _required(
            periodic,
            "mode",
            "validationConfig.geo.periodicCheckPolicy",
        ),
        "validationConfig.geo.periodicCheckPolicy.mode",
    )
    if periodic_mode not in {"none", "required"}:
        _fail("validationConfig.geo.periodicCheckPolicy.mode")
    interval_seconds = _integer(
        _required(
            periodic,
            "intervalSeconds",
            "validationConfig.geo.periodicCheckPolicy",
        ),
        "validationConfig.geo.periodicCheckPolicy.intervalSeconds",
        0,
        86_400,
    )
    if (periodic_mode == "none" and interval_seconds != 0) or (
        periodic_mode == "required" and interval_seconds < 1
    ):
        _fail("validationConfig.geo.periodicCheckPolicy")

    activation = _mapping(
        _required(root, "activation", "validationConfig"),
        "validationConfig.activation",
    )
    _only(activation, _ALLOWED_ACTIVATION_KEYS, "validationConfig.activation")
    if _nonempty_text(
        _required(
            activation,
            "challengeType",
            "validationConfig.activation",
        ),
        "validationConfig.activation.challengeType",
    ) != CIPHER_CHALLENGE_TYPE:
        _fail("validationConfig.activation.challengeType")
    _integer(
        _required(
            activation,
            "deadlineSeconds",
            "validationConfig.activation",
        ),
        "validationConfig.activation.deadlineSeconds",
        1,
        86_400,
    )
    _nonempty_text(
        _required(activation, "qrMode", "validationConfig.activation"),
        "validationConfig.activation.qrMode",
    )

    fallback = _mapping(
        _required(root, "fallback", "validationConfig"),
        "validationConfig.fallback",
    )
    _only(fallback, _ALLOWED_FALLBACK_KEYS, "validationConfig.fallback")
    fallback_enabled = _boolean(
        _required(fallback, "enabled", "validationConfig.fallback"),
        "validationConfig.fallback.enabled",
    )
    quota = _integer(
        _required(
            fallback,
            "quotaPerPlayer",
            "validationConfig.fallback",
        ),
        "validationConfig.fallback.quotaPerPlayer",
        0,
        1_000_000,
    )
    offer_id = fallback.get("offerId")
    if fallback_enabled:
        _nonempty_text(offer_id, "validationConfig.fallback.offerId", 64)
        if quota < 1:
            _fail("validationConfig.fallback.quotaPerPlayer")
    elif offer_id is not None or quota != 0:
        _fail("validationConfig.fallback")

    return deepcopy(dict(root))
