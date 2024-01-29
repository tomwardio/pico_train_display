# Release Notes

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
