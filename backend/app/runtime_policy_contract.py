"""Validation contract for versioned solo MissionRuntimePolicy CMS data.

Scope: shape, bounds and cross-field invariants of the first solo runtime
vertical, as defined in ``docs/solo-mission-runtime-policy-contract.md``.

This module has no database access, no HTTP concerns and no game rule that the
contract leaves to CMS data. It is the counterpart of ``app/content_contract.py``
(public content) and ``app/geo_team_contract.py`` (protected geo/team
configuration).

Database-dependent checks, such as "the referenced item exists and is
published", belong to the admin API layer that owns a session; every function
here is pure.

Error messages carry only a field path and a static reason. A submitted value is
never echoed, so policy content cannot leak through an API error response.

Multipliers are stored in CMS data as JSON numbers in the range 0..1. They are
validated with ``Decimal`` and must have at most ``MULTIPLIER_DECIMAL_PLACES``
decimal places, so settlement arithmetic can use the exact integer scale factor
from ``multiplier_scale_factor`` instead of floating-point math.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from app.mission_categories import MISSION_CATEGORY_TEAM, is_valid_category

__all__ = [
    "RuntimePolicyValidationError",
    "multiplier_scale_factor",
    "scaled_attempt_multipliers",
    "validate_challenge_policy",
    "validate_fallback_policy",
    "validate_feature_flags",
    "validate_required_items",
    "validate_reward_policy",
    "validate_runtime_policy",
]


class RuntimePolicyValidationError(ValueError):
    """Safe validation failure for versioned solo runtime policy CMS data."""


SOLO_MISSION_TYPE = "solo"
CIPHER_CHALLENGE_TYPE = "cipher"
SCHEMA_VERSION_ONE = 1

# docs/solo-mission-runtime-policy-contract.md, "Скалярные правила policy".
ENTRY_ROOT_ATOMIC_MIN = 0
ENTRY_ROOT_ATOMIC_MAX = 2_147_483_647
MAX_ATTEMPTS_MIN = 1
MAX_ATTEMPTS_MAX = 10
REPEATABILITY_POLICIES = frozenset(
    {"one_time", "after_terminal", "after_failure_only"}
)

# "Entry items".
REQUIRED_ITEMS_MAX = 100
ITEM_QUANTITY_MIN = 1
ITEM_QUANTITY_MAX = 2_147_483_647

# "Cipher".
DRUM_COUNT_MIN = 1
DRUM_COUNT_MAX = 12
ALPHABET_MIN = 2
ALPHABET_MAX = 64
FALSE_CHOICES_PER_DRUM_MIN = 0
FALSE_CHOICES_PER_DRUM_MAX = 16

# "Награды".
REWARDS_MAX = 100
REWARD_AMOUNT_MIN = 1
REWARD_QUANTITY_MIN = 1
REWARD_TYPES = frozenset({"root", "item"})

# Implementation bound: the contract bounds the number of display strings in
# the alphabet but not the length of one.
DISPLAY_STRING_MAX_LENGTH = 8

MULTIPLIER_DECIMAL_PLACES = 6
MULTIPLIER_SCALE = 1_000_000

# Canonical stored form: a plain decimal literal, no exponent, no sign and no
# non-ASCII digits. Decimal() alone would also accept "1e-1" and unicode ones.
_MULTIPLIER_TEXT_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")

_ALLOWED_REQUIRED_ITEMS_KEYS = {"schemaVersion", "items"}
_ALLOWED_ITEM_REQUIREMENT_KEYS = {"itemId", "quantity"}
_ALLOWED_CHALLENGE_KEYS = {
    "schemaVersion",
    "challengeType",
    "drumCount",
    "alphabet",
    "falseChoicesPerDrum",
}
_ALLOWED_REWARD_POLICY_KEYS = {"schemaVersion", "attemptMultipliers", "rewards"}
_ALLOWED_ROOT_REWARD_KEYS = {"rewardType", "amountAtomic"}
_ALLOWED_ITEM_REWARD_KEYS = {"rewardType", "itemId", "quantity"}


def _fail(path: str, reason: str) -> None:
    # Never echo a submitted value: policy content must not leak via an error.
    raise RuntimePolicyValidationError(f"{path}: {reason}")


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    return value


def _only(value: Mapping[str, Any], allowed: set[str], path: str) -> None:
    if set(value) - allowed:
        _fail(path, "contains unsupported keys")


def _required(value: Mapping[str, Any], key: str, path: str) -> Any:
    if key not in value:
        _fail(f"{path}.{key}", "is required")
    return value[key]


def _schema_version_one(value: Any, path: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value != SCHEMA_VERSION_ONE
    ):
        _fail(path, "must equal integer 1")


def _integer(value: Any, path: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(path, "must be an integer")
    if not minimum <= value <= maximum:
        _fail(path, f"must be between {minimum} and {maximum}")
    return value


def _nonempty_text(value: Any, path: str, maximum: int) -> str:
    if not isinstance(value, str):
        _fail(path, "must be a string")
    if not value.strip():
        _fail(path, "must not be empty")
    if len(value) > maximum:
        _fail(path, f"must be at most {maximum} characters")
    return value


def _display_string(value: Any, path: str) -> str:
    text = _nonempty_text(value, path, DISPLAY_STRING_MAX_LENGTH)
    if text != text.strip():
        _fail(path, "must not begin or end with whitespace")
    return text


def _ambiguity_key(value: str) -> str:
    # NFKC folds full-width and compatibility forms; casefold folds case.
    # Homoglyphs across different scripts (O/0, l/1) are not covered.
    return unicodedata.normalize("NFKC", value).casefold()


def _decimal_multiplier(value: Any, path: str) -> Decimal:
    # Accepts JSON numbers and the canonical decimal strings this module
    # produces, so a stored policy can be re-validated when it is read.
    if isinstance(value, bool):
        _fail(path, "must be a number between 0 and 1")
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, float):
        # repr() round-trips the JSON literal, so 0.1 becomes "0.1" rather
        # than the full binary expansion of the float.
        text = repr(value)
    elif isinstance(value, str):
        text = value
    else:
        _fail(path, "must be a number or an exact decimal string between 0 and 1")

    if not _MULTIPLIER_TEXT_PATTERN.fullmatch(text):
        _fail(path, "must be a plain decimal number between 0 and 1")

    if len(text.partition(".")[2]) > MULTIPLIER_DECIMAL_PLACES:
        _fail(path, f"must have at most {MULTIPLIER_DECIMAL_PLACES} decimal places")

    number = Decimal(text)
    if number < 0 or number > 1:
        _fail(path, "must be between 0 and 1")
    return number


def multiplier_scale_factor(value: Decimal) -> int:
    """Return the exact integer ROOT scale factor for a validated multiplier."""
    scaled = value * MULTIPLIER_SCALE
    if scaled != scaled.to_integral_value():
        raise RuntimePolicyValidationError(
            "multiplier: not exactly representable at the configured scale"
        )
    return int(scaled)


def _multipliers(value: Any, path: str, max_attempts: int) -> list[Decimal]:
    if not isinstance(value, list) or len(value) != max_attempts:
        _fail(path, f"must contain exactly {max_attempts} values")

    numbers = [
        _decimal_multiplier(item, f"{path}[{index}]")
        for index, item in enumerate(value)
    ]

    if numbers[0] != 1:
        _fail(path, "first value must equal 1.0")
    if any(numbers[index] > numbers[index - 1] for index in range(1, len(numbers))):
        _fail(path, "values must not increase")

    return numbers


def _canonical_multiplier_text(value: Decimal) -> str:
    """Render a validated multiplier as an exact decimal string."""
    text = format(value.normalize(), "f")
    return text


def validate_required_items(value: Any) -> dict[str, Any]:
    """Validate required_items_json and return its normalized form."""
    root = _mapping(value, "requiredItems")
    _only(root, _ALLOWED_REQUIRED_ITEMS_KEYS, "requiredItems")
    _schema_version_one(
        _required(root, "schemaVersion", "requiredItems"),
        "requiredItems.schemaVersion",
    )

    items = _required(root, "items", "requiredItems")
    if not isinstance(items, list) or len(items) > REQUIRED_ITEMS_MAX:
        _fail(
            "requiredItems.items",
            f"must be a list of at most {REQUIRED_ITEMS_MAX} entries",
        )

    seen_item_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []

    for index, entry in enumerate(items):
        path = f"requiredItems.items[{index}]"
        requirement = _mapping(entry, path)
        _only(requirement, _ALLOWED_ITEM_REQUIREMENT_KEYS, path)

        item_id = _nonempty_text(
            _required(requirement, "itemId", path),
            f"{path}.itemId",
            64,
        )
        if item_id in seen_item_ids:
            _fail("requiredItems.items", "itemId values must be unique")
        seen_item_ids.add(item_id)

        quantity = _integer(
            _required(requirement, "quantity", path),
            f"{path}.quantity",
            ITEM_QUANTITY_MIN,
            ITEM_QUANTITY_MAX,
        )
        normalized.append({"itemId": item_id, "quantity": quantity})

    return {"schemaVersion": SCHEMA_VERSION_ONE, "items": normalized}


def validate_challenge_policy(value: Any) -> dict[str, Any]:
    """Validate challenge_policy_json for the first cipher version."""
    root = _mapping(value, "challengePolicy")
    _only(root, _ALLOWED_CHALLENGE_KEYS, "challengePolicy")
    _schema_version_one(
        _required(root, "schemaVersion", "challengePolicy"),
        "challengePolicy.schemaVersion",
    )

    challenge_type = _nonempty_text(
        _required(root, "challengeType", "challengePolicy"),
        "challengePolicy.challengeType",
        64,
    )
    if challenge_type != CIPHER_CHALLENGE_TYPE:
        _fail("challengePolicy.challengeType", "must be cipher for schemaVersion 1")

    drum_count = _integer(
        _required(root, "drumCount", "challengePolicy"),
        "challengePolicy.drumCount",
        DRUM_COUNT_MIN,
        DRUM_COUNT_MAX,
    )

    alphabet = _required(root, "alphabet", "challengePolicy")
    if (
        not isinstance(alphabet, list)
        or not ALPHABET_MIN <= len(alphabet) <= ALPHABET_MAX
    ):
        _fail(
            "challengePolicy.alphabet",
            f"must be a list of {ALPHABET_MIN} to {ALPHABET_MAX} display strings",
        )

    seen_keys: set[str] = set()
    normalized_alphabet: list[str] = []

    for index, entry in enumerate(alphabet):
        path = f"challengePolicy.alphabet[{index}]"
        text = _display_string(entry, path)
        key = _ambiguity_key(text)
        if key in seen_keys:
            _fail(
                "challengePolicy.alphabet",
                "must not contain visually or case equivalent entries",
            )
        seen_keys.add(key)
        normalized_alphabet.append(text)

    false_choices = _integer(
        _required(root, "falseChoicesPerDrum", "challengePolicy"),
        "challengePolicy.falseChoicesPerDrum",
        FALSE_CHOICES_PER_DRUM_MIN,
        FALSE_CHOICES_PER_DRUM_MAX,
    )

    return {
        "schemaVersion": SCHEMA_VERSION_ONE,
        "challengeType": CIPHER_CHALLENGE_TYPE,
        "drumCount": drum_count,
        "alphabet": normalized_alphabet,
        "falseChoicesPerDrum": false_choices,
    }


def validate_reward_policy(value: Any, *, max_attempts: int) -> dict[str, Any]:
    """Validate reward_policy_json against the sibling scalar max_attempts."""
    root = _mapping(value, "rewardPolicy")
    _only(root, _ALLOWED_REWARD_POLICY_KEYS, "rewardPolicy")
    _schema_version_one(
        _required(root, "schemaVersion", "rewardPolicy"),
        "rewardPolicy.schemaVersion",
    )

    multipliers = _multipliers(
        _required(root, "attemptMultipliers", "rewardPolicy"),
        "rewardPolicy.attemptMultipliers",
        max_attempts,
    )

    rewards = _required(root, "rewards", "rewardPolicy")
    if not isinstance(rewards, list) or len(rewards) > REWARDS_MAX:
        _fail(
            "rewardPolicy.rewards",
            f"must be a list of at most {REWARDS_MAX} entries",
        )

    normalized: list[dict[str, Any]] = []
    root_reward_seen = False
    item_ids: set[str] = set()

    for index, entry in enumerate(rewards):
        path = f"rewardPolicy.rewards[{index}]"
        reward = _mapping(entry, path)

        reward_type = _nonempty_text(
            _required(reward, "rewardType", path),
            f"{path}.rewardType",
            64,
        )
        if reward_type not in REWARD_TYPES:
            _fail(f"{path}.rewardType", "must be root or item")

        if reward_type == "root":
            _only(reward, _ALLOWED_ROOT_REWARD_KEYS, path)
            if root_reward_seen:
                _fail("rewardPolicy.rewards", "must contain at most one root entry")
            root_reward_seen = True
            amount = _integer(
                _required(reward, "amountAtomic", path),
                f"{path}.amountAtomic",
                REWARD_AMOUNT_MIN,
                ENTRY_ROOT_ATOMIC_MAX,
            )
            normalized.append({"rewardType": "root", "amountAtomic": amount})
            continue

        _only(reward, _ALLOWED_ITEM_REWARD_KEYS, path)
        item_id = _nonempty_text(
            _required(reward, "itemId", path),
            f"{path}.itemId",
            64,
        )
        if item_id in item_ids:
            _fail("rewardPolicy.rewards", "itemId values must be unique")
        item_ids.add(item_id)
        quantity = _integer(
            _required(reward, "quantity", path),
            f"{path}.quantity",
            REWARD_QUANTITY_MIN,
            ITEM_QUANTITY_MAX,
        )
        normalized.append(
            {"rewardType": "item", "itemId": item_id, "quantity": quantity}
        )

    return {
        "schemaVersion": SCHEMA_VERSION_ONE,
        # Exact decimal text; a float never enters stored configuration.
        "attemptMultipliers": [
            _canonical_multiplier_text(number) for number in multipliers
        ],
        "rewards": normalized,
    }


def scaled_attempt_multipliers(reward_policy: Mapping[str, Any]) -> list[int]:
    """Return integer ROOT scale factors for a validated reward policy.

    Attempt ``sequence_number`` values start at 1, so the factor for the first
    attempt is index 0.
    """
    multipliers = reward_policy["attemptMultipliers"]
    return [multiplier_scale_factor(Decimal(text)) for text in multipliers]


def validate_fallback_policy(value: Any) -> None:
    """Validate fallback_policy_json; only null is valid for version 1."""
    if value is not None:
        _fail("fallbackPolicy", "must be null for schemaVersion 1")


def validate_feature_flags(value: Any) -> dict[str, Any]:
    """Validate feature_flags_json; only an empty object is valid for v1."""
    root = _mapping(value, "featureFlags")
    if root:
        _fail(
            "featureFlags",
            "must be an empty object for schemaVersion 1; use System Settings",
        )
    return {}


def _normalize_challenge_policy(
    challenge_policy_json: Any,
    *,
    required: bool,
) -> Any:
    """Validate and normalize challenge_policy_json for the entry flow.

    Team missions must carry a cipher challenge, so a missing/empty value is
    rejected with an explicit "required" message. Solo / race / co-op missions
    may omit it entirely; the normalized snapshot then stores
    ``challengePolicy: None``. A non-empty object is always validated against
    the cipher scheme so existing callers that still pass a challenge keep
    working unchanged.
    """
    if challenge_policy_json is None or challenge_policy_json == {}:
        if required:
            _fail("challengePolicy", "challengePolicyJson required for team")
        return None
    return validate_challenge_policy(challenge_policy_json)


def validate_runtime_policy(
    *,
    mission_category: str | None = None,
    entry_root_atomic: Any,
    max_attempts: Any,
    repeatability_policy: Any,
    required_items_json: Any,
    challenge_policy_json: Any = None,
    reward_policy_json: Any,
    fallback_policy_json: Any,
    feature_flags_json: Any,
) -> dict[str, Any]:
    """Validate one full policy and return its normalized snapshot form.

    ``mission_category`` is the participation category (solo / team / race /
    co-op) that the policy is attached to. Every known category may carry the
    same entry/challenge policy: team/co-op use it in individual completion,
    solo — directly. ``None`` is accepted for legacy callers that predate the
    category (no gate).

    ``challenge_policy_json`` is optional: for solo / race / co-op missions it
    may be omitted (None) or an empty object, in which case the normalized
    snapshot stores ``challengePolicy: None``. Team missions still require a
    cipher challenge. A non-empty object is always validated against the cipher
    scheme.

    The result uses camelCase keys, contains no database identifier, and carries
    no lifecycle state. Row status and version belong to the admin API layer.
    """
    if mission_category is not None and not is_valid_category(mission_category):
        _fail("missionCategory", "unknown mission_category")

    entry_root = _integer(
        entry_root_atomic,
        "entryRootAtomic",
        ENTRY_ROOT_ATOMIC_MIN,
        ENTRY_ROOT_ATOMIC_MAX,
    )
    attempts = _integer(
        max_attempts,
        "maxAttempts",
        MAX_ATTEMPTS_MIN,
        MAX_ATTEMPTS_MAX,
    )

    repeatability = _nonempty_text(
        repeatability_policy,
        "repeatabilityPolicy",
        64,
    )
    if repeatability not in REPEATABILITY_POLICIES:
        _fail(
            "repeatabilityPolicy",
            "must be one_time, after_terminal or after_failure_only",
        )

    validate_fallback_policy(fallback_policy_json)

    return {
        "missionType": SOLO_MISSION_TYPE,
        "entryRootAtomic": entry_root,
        "maxAttempts": attempts,
        "repeatabilityPolicy": repeatability,
        "requiredItems": validate_required_items(required_items_json),
        "challengePolicy": _normalize_challenge_policy(
            challenge_policy_json,
            required=mission_category == MISSION_CATEGORY_TEAM,
        ),
        "rewardPolicy": validate_reward_policy(
            reward_policy_json,
            max_attempts=attempts,
        ),
        "fallbackPolicy": None,
        "featureFlags": validate_feature_flags(feature_flags_json),
    }
