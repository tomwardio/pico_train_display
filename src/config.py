# Copyright (c) 2023 Tom Ward
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
# the Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""Configuration class for storing config options."""

import display
import time_range


class RttConfig:
  """Real-time trains configuration."""

  def __init__(self, username: str, password: str, update_interval: int):
    self.username = username
    self.password = password
    self.update_interval = update_interval

  def validate(self):
    if self.update_interval <= 0:
      raise ValueError(
          f'RTT update interval must be > 0! {self.update_interval=}'
      )


class WifiConfig:
  """WiFi configuration."""

  def __init__(self, ssid: str, password: str):
    self.ssid = ssid
    self.password = password

  def validate(self):
    pass


class DisplayConfig:
  """Display configuration."""

  def __init__(
      self,
      refresh: int,
      type: str,
      flip: bool = False,
      active_time: str | None = None,
  ):
    self.refresh = refresh
    self.type = type
    self.flip = flip
    self.active_time = time_range.parse(active_time) if active_time else None

  def validate(self):
    if self.refresh <= 0:
      raise ValueError(f'Display refresh must be > 0! refresh={self.refresh}')
    if self.type not in display.displays():
      raise ValueError(f'Unrecognized display name! type={self.type}')
    if not isinstance(self.flip, bool):
      raise ValueError(f'Display flip must be a boolean! flip={self.flip}')


class DebugConfig:
  """Debug configuration."""

  def __init__(self, log: bool = False):
    self.log = log

  def validate(self):
    if not isinstance(self.log, bool):
      raise ValueError(f'Debug log must be a boolean! log={self.log}')


class Config:
  """Main configuration class."""

  def __init__(
      self,
      *,
      destination: str,
      station: str,
      wifi: WifiConfig,
      rtt: RttConfig,
      display: DisplayConfig,
      min_departure_time: int = 0,
      debug: DebugConfig = DebugConfig(),
  ):
    self.destination = destination
    self.station = station
    self.wifi = wifi
    self.rtt = rtt
    self.display = display
    self.min_departure_time = min_departure_time
    self.debug = debug
    self.validate()

  def validate(self):
    if len(self.destination) != 3:
      raise ValueError(f'Invalid destination! destination={self.destination}')
    if len(self.station) != 3:
      raise ValueError(f'Invalid station! station={self.station}')
    self.wifi.validate()
    self.rtt.validate()
    self.display.validate()
    if self.min_departure_time < 0:
      raise ValueError(
          'Minimum departure time must be >= 0! '
          f'min_departure_time={self.min_departure_time}'
      )
    self.debug.validate()


def load(config_json) -> Config:
  kwargs = {}
  for k, v in config_json.items():
    if k == 'wifi':
      kwargs[k] = WifiConfig(**v)
    elif k == 'display':
      kwargs[k] = DisplayConfig(**v)
    elif k == 'rtt':
      kwargs[k] = RttConfig(**v)
    elif k == 'debug':
      kwargs[k] = DebugConfig(**v)
    else:
      kwargs[k] = v
  return Config(**kwargs)
