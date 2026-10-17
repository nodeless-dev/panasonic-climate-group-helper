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
    CONF_HUMIDITY_CURRENT_AVG,
    CONF_HUMIDITY_REFERENCE_ENTITY,
    CONF_REFERENCE_ENTITY,
    CONF_TEMP_CURRENT_AVG,
    CONF_TEMP_REFERENCE_ENTITY,
    ENTITY_SELECTOR_KEYS,
    CurrentAverageOption,
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


def set_reference(group, entity_id, domain=None):
    for measurement in ([domain] if domain else ['temp', 'humidity']):
        setattr(group, measurement + '_reference_entity_id', entity_id)
        setattr(group, '_' + measurement + '_current_avg_mode',
                CurrentAverageOption.REFERENCE if entity_id else CurrentAverageOption.MEAN)


def readings(group):
    return (group.aggregator._compute_temperature().current_temperature,
            group.aggregator._compute_humidity().current_humidity)


async def test_default_and_selected_readings_preserve_targets(group):
    assert readings(group) == (24, 55)
    original = group.aggregator._compute_temperature()
    for member, expected in [(MEMBERS[0], (21, 45)), (MEMBERS[1], (27, 65))]:
        set_reference(group, member)
        assert readings(group) == expected
        result = group.aggregator._compute_temperature()
        assert result.target_temperature == original.target_temperature == 23
        assert result.member_temp_avg == original.member_temp_avg == 24
        assert result.min_temp == original.min_temp
        assert result.max_temp == original.max_temp
    set_reference(group, None)
    assert readings(group) == (24, 55)


@pytest.mark.parametrize('state', ['off', 'heat'])
async def test_reference_kept_when_off_or_isolated(group, state):
    set_reference(group, MEMBERS[0])
    group._ignore_off_members_temperature = True
    group.hass.states.async_set(MEMBERS[0], state, {
        'current_temperature': 21, 'current_humidity': 45,
    })
    group.run_state = replace(group.run_state, isolated_members=frozenset({MEMBERS[0]}))
    group.aggregator.states, _ = group.aggregator._get_valid_member_states(MEMBERS)
    assert readings(group) == (21, 45)


@pytest.mark.parametrize('state', ['unknown', 'unavailable', None])
async def test_unavailable_reference_does_not_fall_back(group, state):
    set_reference(group, MEMBERS[0])
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
    set_reference(group, MEMBERS[0])
    group.hass.states.async_set(MEMBERS[0], 'heat', {
        'current_temperature': 21, 'current_humidity': value,
    })
    assert readings(group) == (21, None)


async def test_reference_has_priority_over_external_sensors_without_calibration(group):
    group.hass.states.async_set('sensor.room', '10')
    group.temp_sensor_entity_ids = ['sensor.room']
    group.humidity_sensor_entity_ids = ['sensor.room']
    assert readings(group) == (10, 10)
    set_reference(group, MEMBERS[0])
    assert readings(group) == (21, 45)
    assert not group.aggregator._compute_temperature().needs_calibration
    assert not group.aggregator._compute_humidity().needs_calibration
    set_reference(group, None)
    assert group.aggregator._compute_temperature().needs_calibration
    assert group.aggregator._compute_humidity().needs_calibration


async def test_removed_reference_cannot_read_outside_the_group(group):
    set_reference(group, 'climate.other')
    group.hass.states.async_set('climate.other', 'heat', {
        'current_temperature': 30, 'current_humidity': 90,
    })
    assert readings(group) == (None, None)


@pytest.mark.parametrize('advanced', [False, True])
async def test_reference_selectors_are_independent_and_conditional(group, advanced):
    options = {CONF_ENTITIES: MEMBERS, CONF_ADVANCED_MODE: advanced}
    flow = ClimateGroupHelperOptionsFlow(SimpleNamespace(options=options))
    flow.hass = group.hass
    def fields(factory, config):
        return next(iter(factory(config).values())).schema.schema
    assert CONF_TEMP_REFERENCE_ENTITY not in fields(flow._section_factory_temperature, options)
    assert CONF_HUMIDITY_REFERENCE_ENTITY not in fields(flow._section_factory_humidity, options)
    selected = {**options, CONF_TEMP_CURRENT_AVG: 'reference', CONF_TEMP_REFERENCE_ENTITY: MEMBERS[0]}
    assert CONF_TEMP_REFERENCE_ENTITY in fields(flow._section_factory_temperature, selected)
    assert CONF_HUMIDITY_REFERENCE_ENTITY not in fields(flow._section_factory_humidity, selected)
    selected.update({CONF_HUMIDITY_CURRENT_AVG: 'reference', CONF_HUMIDITY_REFERENCE_ENTITY: MEMBERS[1]})
    normalized = flow._normalize_options(selected)
    assert normalized[CONF_TEMP_REFERENCE_ENTITY] == MEMBERS[0]
    assert normalized[CONF_HUMIDITY_REFERENCE_ENTITY] == MEMBERS[1]
    assert CONF_REFERENCE_ENTITY not in fields(flow._section_factory_members, selected)


@pytest.mark.parametrize(('mode_key', 'entity_key', 'section'), [
    (CONF_TEMP_CURRENT_AVG, CONF_TEMP_REFERENCE_ENTITY, 'temperature_section'),
    (CONF_HUMIDITY_CURRENT_AVG, CONF_HUMIDITY_REFERENCE_ENTITY, 'humidity_section'),
])
async def test_reference_selection_refresh_then_validate_and_save(group, mode_key, entity_key, section):
    options = {CONF_ENTITIES: MEMBERS}
    flow = ClimateGroupHelperOptionsFlow(SimpleNamespace(options=options))
    flow.hass = group.hass
    selected = {'members_section': {CONF_ENTITIES: MEMBERS}, section: {mode_key: 'reference'}}
    result = await flow.async_step_init(selected)
    assert result['type'] == 'form'
    assert not result['errors']
    selected[section][entity_key] = 'climate.other'
    result = await flow.async_step_init(selected)
    assert result['errors'] == {section: 'reference_not_in_members'}
    selected[section][entity_key] = MEMBERS[0]
    result = await flow.async_step_init(selected)
    assert result['type'] == 'create_entry'
    assert result['data'][entity_key] == MEMBERS[0]
    flow._config_entry.options = result['data']
    selected[section] = {mode_key: 'mean'}
    result = await flow.async_step_init(selected)
    assert result['type'] == 'form'
    result = await flow.async_step_init(selected)
    assert result['type'] == 'create_entry'
    assert entity_key not in result['data']


def test_reference_migration_preserves_both_readings_and_is_idempotent():
    from custom_components.climate_group_helper.reference import (
        migrate_reference_options,
    )
    migrated = migrate_reference_options({CONF_REFERENCE_ENTITY: MEMBERS[0]})
    assert CONF_REFERENCE_ENTITY not in migrated
    for mode_key, entity_key in [
        (CONF_TEMP_CURRENT_AVG, CONF_TEMP_REFERENCE_ENTITY),
        (CONF_HUMIDITY_CURRENT_AVG, CONF_HUMIDITY_REFERENCE_ENTITY),
    ]:
        assert migrated[mode_key] == 'reference'
        assert migrated[entity_key] == MEMBERS[0]
        assert entity_key in VALID_CONFIG_KEYS
        assert entity_key in ENTITY_SELECTOR_KEYS
    assert migrate_reference_options(migrated) == migrated


async def test_different_references_and_single_domain_averaging(group):
    set_reference(group, MEMBERS[0], 'temp')
    assert readings(group) == (21, 55)
    set_reference(group, MEMBERS[1], 'humidity')
    assert readings(group) == (21, 65)
    set_reference(group, None, 'temp')
    assert readings(group) == (24, 65)


def test_panasonic_icons_cover_native_modes_and_preserve_existing_icons():
    icons = json.loads(Path('custom_components/climate_group_helper/icons.json').read_text())
    attrs = icons['entity']['climate']['climate_group_helper']['state_attributes']
    assert attrs['preset_mode']['state']['quiet'] == 'mdi:leaf'
    assert attrs['preset_mode']['state']['none'] == 'mdi:air-filter'
    assert attrs['fan_mode']['state']['mid'] == 'mdi:numeric-3-circle-outline'
    assert attrs['swing_mode']['state']['upmid'] == 'mdi:arrow-top-right-thin'
    assert attrs['swing_horizontal_mode']['state']['mid'] == 'mdi:arrow-down-thin'
    assert attrs['swing_mode']['state']['auto'] == 'mdi:shuffle'


async def test_calibration_heartbeat_cannot_write_reference_measurements(group):
    set_reference(group, MEMBERS[0])
    group.temp_update_target_entity_ids = ['number.calibration']
    group.humidity_update_target_entity_ids = ['number.humidity']
    group.aggregator._apply_temperature(group.aggregator._compute_temperature())
    group.aggregator._apply_humidity(group.aggregator._compute_humidity())
    assert not group.calibration_handler.bypassed
    group.calibration_handler._heartbeat(None)
    assert not group.calibration_handler._pending


@pytest.mark.parametrize(('attribute', 'native', 'displayed'), [
    ('fan_mode', 'Mid', 'mid'),
    ('swing_mode', 'UpMid', 'upmid'),
    ('swing_horizontal_mode', 'LeftMid', 'leftmid'),
])
async def test_icon_keys_display_lowercase_but_commands_keep_native_modes(group, attribute, native, displayed):
    setattr(group, f'_attr_{attribute}s', ['Auto', native])
    setattr(group, f'_attr_{attribute}', native)
    assert getattr(group, attribute) == displayed
    assert getattr(group, attribute + 's') == ['auto', displayed]
    group.climate_call_handler.call_debounced = AsyncMock()
    await getattr(group, f'async_set_{attribute}')(displayed)
    group.climate_call_handler.call_debounced.assert_awaited_once_with(data={attribute: native})
    assert getattr(group.shared_target_state, attribute) == native


def test_case_collisions_keep_distinct_native_options():
    from custom_components.climate_group_helper.mode_icons import (
        display_modes,
        native_mode,
    )
    assert display_modes(['Low', 'low']) == ['Low', 'low']
    assert native_mode('low', ['Low', 'low']) == 'low'
    assert display_modes(['Custom vendor mode']) == ['Custom vendor mode']


def test_icon_state_keys_follow_home_assistant_schema():
    import re
    icons = json.loads(Path('custom_components/climate_group_helper/icons.json').read_text())
    attrs = icons['entity']['climate']['climate_group_helper']['state_attributes']
    for attribute in attrs.values():
        for key in attribute.get('state', {}):
            assert re.fullmatch(r'[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?', key), key


async def test_reference_only_suspends_its_own_calibration(group):
    group.hass.states.async_set('sensor.room', '10')
    group.temp_sensor_entity_ids = ['sensor.room']
    group.humidity_sensor_entity_ids = ['sensor.room']
    set_reference(group, MEMBERS[0], 'temp')
    assert readings(group) == (21, 10)
    assert not group.aggregator._compute_temperature().needs_calibration
    assert group.aggregator._compute_humidity().needs_calibration
    set_reference(group, None, 'temp')
    set_reference(group, MEMBERS[1], 'humidity')
    assert readings(group) == (10, 65)
    assert group.aggregator._compute_temperature().needs_calibration
    assert not group.aggregator._compute_humidity().needs_calibration


async def test_legacy_config_migrates_before_constructing_group(group):
    migrated = ClimateGroupHelper(group.hass, 'legacy', 'Legacy', MEMBERS, {
        CONF_REFERENCE_ENTITY: MEMBERS[0],
    })
    assert migrated._temp_current_avg_mode == CurrentAverageOption.REFERENCE
    assert migrated._humidity_current_avg_mode == CurrentAverageOption.REFERENCE
    assert migrated.temp_reference_entity_id == migrated.humidity_reference_entity_id == MEMBERS[0]
