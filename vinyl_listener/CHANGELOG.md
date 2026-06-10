# Changelog

## [1.2.1] - 2026-06-10
### Added
- English translations

## [1.2.0] - 2026-06-10
### Added
- Last.fm integration for automatic track scrobbling.
- Dynamic auto-calibration feature to sample ambient noise and set the volume threshold automatically when the turntable is turned on.
### Changed
- Replaced the hardcoded volume threshold with a dynamic variable managed by the auto-calibration system.

## [1.1.3] - 2026-06-10
### Added
- Custom idle image for Now Playing.

## [1.1.2] - 2026-06-10
### Fixed
- Resolved an issue where MQTT retained the last track data indefinitely; sensors now wipe to "Idle" when the turntable turns off.

## [1.1.1] - 2026-06-10
### Added
- Custom icon and banner logo for the Home Assistant UI.

## [1.0.9] - 2026-06-10
### Added
- User-configurable silence gap parameter for track detection.
### Changed
- Implemented regex validation for the `turntable_entity` configuration to ensure valid switch domains are used.

## [1.0.6] - 2026-06-10
### Fixed
- Added `libasound2-plugins` and forced ALSA to route through the Home Assistant PulseAudio socket, resolving "No such device" microphone hardware errors.

## [1.0.0] - 2026-06-10
### Added
- Initial release.
- Hybrid local Shazam and ACRCloud audio fingerprinting.
- Auto-discovery payload for automatic MQTT sensor creation in Home Assistant.
