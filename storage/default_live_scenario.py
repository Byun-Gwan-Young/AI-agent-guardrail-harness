"""Project-owned, immutable metadata for ordinary live session linkage.

This is NOT an executable ScenarioV2. Only the bundled, version-controlled
storage-live-v1 definition is accepted. Authentication belongs to Backend;
user_id must come from its authenticated principal, never a request body.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from psycopg.types.json import Jsonb

from storage.db import get_connection
from storage.safety import assert_safe_storage_json


DEFAULT_LIVE_SCENARIO_PATH = Path(__file__).resolve().parent / "fixtures" / "default_live_scenario_v1.yaml"
_FIXED_FIELDS = {
    "schema_version": "storage-live-v1",
    "scenario_id": "live-default",
    "title": "Default Live Session",
    "task_kind": "live",
    "purpose": "session-linkage",
}


class _UniqueKeyLoader(yaml.SafeLoader):
    """Do not silently accept duplicate YAML keys or merge-key overrides."""


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ValueError("Invalid default live YAML mapping")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _load_definition() -> tuple[dict[str, Any], str]:
    # Read once: parsed content and hash must describe the very same bytes.
    raw = DEFAULT_LIVE_SCENARIO_PATH.read_bytes()
    if not raw or len(raw) > 16_384 or b"\r" in raw:
        raise ValueError("Default live YAML must be nonempty UTF-8 with LF newlines, at most 16 KiB")
    try:
        config = yaml.load(raw.decode("utf-8"), Loader=_UniqueKeyLoader)
    except (UnicodeError, yaml.YAMLError, ValueError, RecursionError):
        # Parser errors may echo source lines. Do not disclose fixture content.
        raise ValueError("Invalid default live YAML") from None
    if not isinstance(config, dict) or set(config) != {*_FIXED_FIELDS, "definition_version"}:
        raise ValueError("Invalid default live definition fields")
    if any(type(config[key]) is not str or config[key] != value
           for key, value in _FIXED_FIELDS.items()):
        raise ValueError("Unsupported default live definition")
    version = config["definition_version"]
    if type(version) is not int or not 1 <= version <= 2_147_483_647:
        raise ValueError("definition_version must be a positive integer")
    assert_safe_storage_json(config, "default_live_scenario")
    return config, hashlib.sha256(raw).hexdigest()


def _positive_id(value, name):
    if type(value) is not int or not 1 <= value <= 9_223_372_036_854_775_807:
        raise ValueError(f"{name} must be a positive BIGINT")


def ensure_default_live_scenario(project_id: int, *, user_id: int) -> dict[str, Any]:
    """Ensure the bundled metadata version for an authenticated owner's project.

    Returns scenario_id (numeric DB PK), scenario_key, scenario_hash,
    schema_version. Never changes an existing scenario or session.

    ValueError: invalid IDs/fixture or a conflicting stored definition.
    LookupError: missing/inaccessible/read-only/ownerless project or user.
    RuntimeError: pending account. DB/file errors propagate for Backend to map.
    Each call, including a cache-like repeat, requires an active owner.
    Existing session exact retries should reuse their original key/hash and
    call start_live_session directly, not re-resolve the latest definition.
    """
    _positive_id(project_id, "project_id")
    _positive_id(user_id, "user_id")
    config, digest = _load_definition()
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Supplied authenticated identity lets us lock user FIRST without
            # an unlocked ownership discovery query. Keep both locks to commit.
            cursor.execute(
                "SELECT account_status FROM users WHERE id = %s FOR SHARE", (user_id,)
            )
            user = cursor.fetchone()
            if user is None:
                raise LookupError("user not found")
            if user[0] != "active":
                raise RuntimeError("account is pending deletion")
            cursor.execute(
                """SELECT id FROM projects
                   WHERE id = %s AND owner_user_id = %s AND read_only = FALSE
                   FOR SHARE""", (project_id, user_id),
            )
            if cursor.fetchone() is None:
                # One response for missing, other-owner, read-only, ownerless.
                raise LookupError("writable owned project not found")
            cursor.execute(
                """INSERT INTO scenarios
                   (project_id, scenario_key, scenario_hash, schema_version, name, task_kind, config)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (project_id, scenario_key, scenario_hash) DO NOTHING""",
                (project_id, config["scenario_id"], digest, config["schema_version"],
                 config["title"], config["task_kind"], Jsonb(config)),
            )
            # A separate READ COMMITTED statement sees a concurrent winner after
            # ON CONFLICT waits for its commit. Lock the row during comparison.
            cursor.execute(
                """SELECT id, schema_version, name, task_kind, config FROM scenarios
                   WHERE project_id = %s AND scenario_key = %s AND scenario_hash = %s
                   FOR SHARE""", (project_id, config["scenario_id"], digest),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("default live scenario disappeared; retry operation")
            # JSON comparison is type-sensitive (True must not equal 1).
            same_config = json.dumps(row[4], sort_keys=True, allow_nan=False) == json.dumps(
                config, sort_keys=True, allow_nan=False
            )
            if row[1:4] != (config["schema_version"], config["title"], config["task_kind"]) or not same_config:
                raise ValueError("Stored default live scenario conflicts with bundled definition")
            return {
                "scenario_id": row[0],
                "scenario_key": config["scenario_id"],
                "scenario_hash": digest,
                "schema_version": config["schema_version"],
            }
