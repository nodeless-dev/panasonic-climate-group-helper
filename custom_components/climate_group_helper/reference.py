"""Migrate the original shared measurement reference to independent sources."""

from typing import Any

from .const import (
    CONF_HUMIDITY_CURRENT_AVG,
    CONF_HUMIDITY_REFERENCE_ENTITY,
    CONF_REFERENCE_ENTITY,
    CONF_TEMP_CURRENT_AVG,
    CONF_TEMP_REFERENCE_ENTITY,
    CurrentAverageOption,
)


def migrate_reference_options(options: dict[str, Any]) -> dict[str, Any]:
    """Preserve the old shared reference for both measurements on upgrade."""
    migrated = dict(options)
    legacy = migrated.pop(CONF_REFERENCE_ENTITY, None)
    if legacy:
        for mode_key, entity_key in (
            (CONF_TEMP_CURRENT_AVG, CONF_TEMP_REFERENCE_ENTITY),
            (CONF_HUMIDITY_CURRENT_AVG, CONF_HUMIDITY_REFERENCE_ENTITY),
        ):
            if entity_key not in migrated:
                migrated[mode_key] = CurrentAverageOption.REFERENCE.value
                migrated[entity_key] = legacy
    return migrated
