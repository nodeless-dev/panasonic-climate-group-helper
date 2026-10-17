"""Reference measurements must not change group targets or silently fall back."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from homeassistant.const import CONF_ENTITIES
from homeassistant.core import HomeAssistant

from custom_components.climate_group_helper import VALID_CONFIG_KEYS
from custom_components.climate_group_helper.climate import ClimateGroupHelper
from custom_components.climate_group_helper.config_flow import (
    ClimateGroupHelperOptionsFlow,
)
from custom_components.climate_group_helper.const import (
    CONF_ADVANCED_MODE,
    CONF_REFERENCE_ENTITY,
    ENTITY_SELECTOR_KEYS,
)

MEMBERS = ['climate.clear', 'climate.shelf']


@pytest_asyncio.fixture
async def group(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    for entity_id, temperature, humidity, target in [
        (MEMBERS[0], 21, 45, 22), (MEMBERS[1], 27, 65, 24),
    ]:
        hass.states.async_set(entity_id, 'heat', {
            'current_temperature': temperature, 'current_humidity': humidity,
            'temperature': target, 'humidity': 50,
        })
    group = ClimateGroupHelper(hass, 'test', 'Test', MEMBERS, {})
    group.entity_id = 'climate.test'
    group.aggregator.states, _ = group.aggregator._get_valid_member_states(MEMBERS)
    group.aggregator.capability_states = group.aggregator.states
    yield group
    await hass.async_stop()


def readings(group):
    return (group.aggregator._compute_temperature().current_temperature,
            group.aggregator._compute_humidity().current_humidity)


async def test_default_and_selected_readings_preserve_targets(group):
    assert readings(group) == (24, 55)
    original = group.aggregator._compute_temperature()
    for member, expected in [(MEMBERS[0], (21, 45)), (MEMBERS[1], (27, 65))]:
        group.reference_entity_id = member
        assert readings(group) == expected
        result = group.aggregator._compute_temperature()
        assert result.target_temperature == original.target_temperature == 23
        assert result.member_temp_avg == original.member_temp_avg == 24
        assert result.min_temp == original.min_temp
        assert result.max_temp == original.max_temp
    group.reference_entity_id = None
    assert readings(group) == (24, 55)


@pytest.mark.parametrize('state', ['off', 'heat'])
async def test_reference_kept_when_off_or_isolated(group, state):
    group.reference_entity_id = MEMBERS[0]
    group._ignore_off_members_temperature = True
    group.hass.states.async_set(MEMBERS[0], state, {
        'current_temperature': 21, 'current_humidity': 45,
    })
    group.run_state = replace(group.run_state, isolated_members=frozenset({MEMBERS[0]}))
    group.aggregator.states, _ = group.aggregator._get_valid_member_states(MEMBERS)
    assert readings(group) == (21, 45)


@pytest.mark.parametrize('state', ['unknown', 'unavailable', None])
async def test_unavailable_reference_does_not_fall_back(group, state):
    group.reference_entity_id = MEMBERS[0]
    if state is None:
        group.hass.states.async_remove(MEMBERS[0])
    else:
        group.hass.states.async_set(MEMBERS[0], state, {
            'current_temperature': 21, 'current_humidity': 45,
        })
    assert readings(group) == (None, None)
    group.hass.states.async_set(MEMBERS[0], 'heat', {
        'current_temperature': 20, 'current_humidity': 42,
    })
    assert readings(group) == (20, 42)


@pytest.mark.parametrize('value', [None, 'unknown', 'bad', float('nan'), float('inf')])
async def test_missing_invalid_measurements_are_unknown(group, value):
    group.reference_entity_id = MEMBERS[0]
    group.hass.states.async_set(MEMBERS[0], 'heat', {
        'current_temperature': 21, 'current_humidity': value,
    })
    assert readings(group) == (21, None)


async def test_reference_has_priority_over_external_sensors_without_calibration(group):
    group.hass.states.async_set('sensor.room', '10')
    group.temp_sensor_entity_ids = ['sensor.room']
    group.humidity_sensor_entity_ids = ['sensor.room']
    assert readings(group) == (10, 10)
    group.reference_entity_id = MEMBERS[0]
    assert readings(group) == (21, 45)
    assert not group.aggregator._compute_temperature().needs_calibration
    assert not group.aggregator._compute_humidity().needs_calibration
    group.reference_entity_id = None
    assert group.aggregator._compute_temperature().needs_calibration
    assert group.aggregator._compute_humidity().needs_calibration


async def test_removed_reference_cannot_read_outside_the_group(group):
    group.reference_entity_id = 'climate.other'
    group.hass.states.async_set('climate.other', 'heat', {
        'current_temperature': 30, 'current_humidity': 90,
    })
    assert readings(group) == (None, None)


@pytest.mark.parametrize('advanced', [False, True])
async def test_option_can_be_selected_cleared_and_survives_refresh(group, advanced):
    flow = ClimateGroupHelperOptionsFlow(SimpleNamespace(options={
        CONF_ENTITIES: MEMBERS, CONF_REFERENCE_ENTITY: MEMBERS[0],
        CONF_ADVANCED_MODE: advanced,
    }))
    flow.hass = group.hass
    selected = {CONF_ENTITIES: MEMBERS, CONF_REFERENCE_ENTITY: MEMBERS[1],
                CONF_ADVANCED_MODE: advanced}
    assert flow._normalize_options(selected)[CONF_REFERENCE_ENTITY] == MEMBERS[1]
    cleared = {CONF_ENTITIES: MEMBERS, CONF_ADVANCED_MODE: advanced}
    assert CONF_REFERENCE_ENTITY not in flow._normalize_options(cleared)
    assert flow._normalize_options({}, refresh=True)[CONF_REFERENCE_ENTITY] == MEMBERS[0]
    schema = flow._section_factory_members(selected)
    members_section = next(iter(schema.values()))
    assert CONF_REFERENCE_ENTITY in members_section.schema.schema


async def test_options_reject_reference_outside_members(group):
    flow = ClimateGroupHelperOptionsFlow(SimpleNamespace(options={CONF_ENTITIES: MEMBERS}))
    flow.hass = group.hass
    flow._show_main_form = AsyncMock(return_value={'type': 'form'})
    await flow.async_step_init({'members_section': {
        CONF_ENTITIES: MEMBERS, CONF_REFERENCE_ENTITY: 'climate.other',
    }})
    assert flow._show_main_form.call_args.kwargs['form_errors'] == {
        'members_section': 'reference_not_in_members',
    }


def test_reference_option_survives_migration_and_is_not_portable_by_default():
    assert CONF_REFERENCE_ENTITY in VALID_CONFIG_KEYS
    assert CONF_REFERENCE_ENTITY in ENTITY_SELECTOR_KEYS


def test_panasonic_icons_cover_native_modes_and_preserve_existing_icons():
    icons = json.loads(Path('custom_components/climate_group_helper/icons.json').read_text())
    attrs = icons['entity']['climate']['climate_group_helper']['state_attributes']
    assert attrs['preset_mode']['state']['quiet'] == 'mdi:leaf'
    assert attrs['preset_mode']['state']['none'] == 'mdi:air-filter'
    assert attrs['fan_mode']['state']['Mid'] == 'mdi:numeric-3-circle-outline'
    assert attrs['swing_mode']['state']['UpMid'] == 'mdi:arrow-top-right-thin'
    assert attrs['swing_horizontal_mode']['state']['Mid'] == 'mdi:arrow-down-thin'
    assert attrs['swing_mode']['state']['auto'] == 'mdi:arrow-oscillating'


async def test_calibration_heartbeat_cannot_write_reference_measurements(group):
    group.reference_entity_id = MEMBERS[0]
    group.temp_update_target_entity_ids = ['number.calibration']
    group.humidity_update_target_entity_ids = ['number.humidity']
    group.aggregator._apply_temperature(group.aggregator._compute_temperature())
    group.aggregator._apply_humidity(group.aggregator._compute_humidity())
    assert group.calibration_handler.bypassed
    group.calibration_handler._heartbeat(None)
    assert not group.calibration_handler._pending


async def test_options_flow_saves_and_clears_reference(group):
    flow = ClimateGroupHelperOptionsFlow(SimpleNamespace(options={CONF_ENTITIES: MEMBERS}))
    flow.hass = group.hass
    result = await flow.async_step_init({'members_section': {
        CONF_ENTITIES: MEMBERS, CONF_REFERENCE_ENTITY: MEMBERS[0],
    }})
    assert result['type'] == 'create_entry'
    assert result['data'][CONF_REFERENCE_ENTITY] == MEMBERS[0]
    flow._config_entry.options = result['data']
    result = await flow.async_step_init({'members_section': {CONF_ENTITIES: MEMBERS}})
    assert result['type'] == 'create_entry'
    assert CONF_REFERENCE_ENTITY not in result['data']
