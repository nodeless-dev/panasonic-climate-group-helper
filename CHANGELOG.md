# Panasonic Climate Group Helper Changelog

This fork has its own release numbering, starting at v1.0.0. It is based on
[Climate Group Helper 1.15.0](https://github.com/bjrnptrsn/climate_group_helper).
Earlier project history is preserved in [UPSTREAM_CHANGELOG.md](UPSTREAM_CHANGELOG.md).

## 1.0.1 - 2026-10-17

- Move Reference Climate into each current-measurement calculation dropdown.
- Show a member selector only when Reference Climate is selected, independently
  for temperature and humidity. Submit once to reveal a newly selected reference.
- Migrate the old shared reference to both measurements on upgrade.
- Keep external sensors and calibration working for the other measurement.

## 1.0.0 - 2026-10-17

- Add Panasonic Comfort Cloud icons for preset, fan, and vertical/horizontal swing controls.
- Add a selectable reference member for current temperature and humidity in both
  Simple and Advanced Mode, without changing group targets or command dispatch.
- Keep missing or unavailable reference readings unknown instead of switching units.
- Suspend external-sensor calibration while reference measurements are selected.
- Publish under a separate repository and HACS name, Panasonic Climate Group Helper.
- Retain the Home Assistant integration name, domain, and all existing translations.
- Provide English repository documentation and remove duplicate German documents and diagrams.
- Retain upstream features, licensing, and attribution.
- Add 25 regression tests against Home Assistant 2026.10.2.
