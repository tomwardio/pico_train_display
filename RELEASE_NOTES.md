# Release Notes

## v2.0.0

This is a major update to support the new Realtime Trains API. See https://api-portal.rtt.io/ for details.

### Added

- Holding the bootsel button during startup will now clear the configuration, allowing users to re-configure witout flashing the device.

### Changed

- Updated to use new RTT API
- Upgraded to MicroPython v1.29.0

### Removed

- Obsolete server component. This is no longer needed as we no longer need to use detailed responses to determine fast trains.

## v1.1.0

- Added optional supoprt for "slow stations".

  Trains that don't stop at a slow station are marked as "fast", showing a small
  icon.

  NB: To use this feature you need to run a the custom web server below to get
  the calling stations.

- Implemented custom web server.

  This is so that we can reduce the JSON response message from RTT to only the
  fields we're interested in, and to add additional calling-at stations that are
  too memory-intensive to run on-device.

- Fixed incorrect destination station for cancelled trains.

## v1.0.0

- Initial release
