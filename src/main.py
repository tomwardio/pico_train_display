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
"""Main entrypoint for Pico train display."""

import asyncio
import errno
import gc
import json
import sys
import time
import _thread

import machine
import micropython
import network
import ntptime

import config as config_module
import display
import fonts
import logging
from setup import server
import time_range
import trains
import utils
import widgets


_WIFI_CONNECT = 'Connecting'
_LOADING_DEPARTURES = 'Loading train departures...'
_DISPLAY_NOT_ACTIVE = 'Outside active hours, going to sleep...'

_SETUP_WIFI_SSID = 'Pico Train Display'
_SETUP_WIFI_PASSWORD = '12345678'
_SETUP_MESSAGE = (
    'Welcome! To setup the display, join\n'
    'Wifi: {}\nPassword: {}\nThen visit http://{}'
)

_MAX_ATTEMPTS = 3
_CONNECT_TIMEOUT = 15

gc.collect()


def _connect(ssid: str, password: str, screen: display.Display) -> network.WLAN:
  widget = widgets.MessageWidget(screen, _WIFI_CONNECT, fonts.DEFAULT_FONT)
  logging.log('Connecting to SSID: {} PASSWORD: {}', ssid, '*' * len(password))

  wlan = network.WLAN(network.STA_IF)
  wlan.active(True)
  wlan.connect(ssid, password if password else None)

  for i in range(_CONNECT_TIMEOUT):
    if wlan.isconnected():
      logging.log('Connected!')
      logging.log(wlan.ifconfig())
      return wlan

    widget.render('{}{}'.format(_WIFI_CONNECT, '.' * (i % 4)))
    screen.flush()
    time.sleep(1)

  raise OSError(
      errno.ETIMEDOUT,
      'Failed to connect to wifi in {} secs'.format(_CONNECT_TIMEOUT),
  )


def _reconnect(wlan: network.WLAN, ssid: str, password: str):
  wlan.active(True)
  wlan.connect(ssid, password if password else None)
  for _ in range(_CONNECT_TIMEOUT):
    if wlan.isconnected():
      logging.log('Reconnected to wifi!')
      return

    time.sleep(1)
  raise TimeoutError(
      'Failed to reconnect to wifi in {} secs'.format(_CONNECT_TIMEOUT)
  )


def _configure_time():
  logging.log('Configure datetime.')
  while True:
    try:
      ntptime.settime()
      break
    except OSError:
      pass
  t = time.localtime()
  logging.log('Time set to UTC {}/{}/{} {}:{}', *t[:5])


# TODO: Make this an enum when micropython supports such a thing
class _ScreenState:
  ENTER_NON_ACTIVE = micropython.const(0)
  NON_ACTIVE = micropython.const(1)
  ACTIVE = micropython.const(2)


def _render_thread(
    screen: display.Display,
    departure_updater: trains.DepartureUpdater,
    config: config_module.Config,
    main_running: _thread.LockType,
    thread_running: _thread.LockType,
):
  with thread_running:
    main_display = widgets.MainWidget(
        screen,
        departure_updater,
        fonts.BOLD_FONT,
        fonts.TALL_FONT,
        fonts.DEFAULT_FONT,
        # Don't render seconds on e-paper displays.
        render_seconds=(config.display.type != 'epd29b'),
    )
    non_active = widgets.MessageWidget(
        screen, _DISPLAY_NOT_ACTIVE, fonts.DEFAULT_FONT
    )

    active_time = config.display.active_time
    refresh_rate_us = int((1 / config.display.refresh) / 1e-6)
    screen.fill(0)
    state = _ScreenState.ACTIVE

    while main_running.locked():
      now = utils.get_uk_time()
      start = time.ticks_us()

      sleep_time_us = refresh_rate_us
      if state == _ScreenState.ACTIVE:
        if active_time is not None and not active_time.in_range(now):
          state = _ScreenState.ENTER_NON_ACTIVE
        elif main_display.render(now):
          gc.collect()
          screen.flush()
      elif state == _ScreenState.ENTER_NON_ACTIVE:
        logging.log(
            'Detected non-active time {} sleeping...', utils.get_uk_time()
        )
        non_active.render()
        screen.flush()
        time.sleep(3)
        screen.fill(0)
        screen.flush()
        screen.sleep()
        state = _ScreenState.NON_ACTIVE
      elif state == _ScreenState.NON_ACTIVE:
        assert active_time is not None
        if active_time.in_range(now):
          logging.log('Awake from non-active time {}', utils.get_uk_time())
          screen.awake()
          state = _ScreenState.ACTIVE
        else:
          # Check again in 10s
          sleep_time_us = int(10 * 1e6)
      else:
        raise ValueError('Unrecognized screen state: {}'.format(state))

      gc.collect()
      elapsed = time.ticks_diff(time.ticks_us(), start)
      sleep_for = sleep_time_us - elapsed
      if sleep_for > 0:
        time.sleep_us(sleep_for)
    logging.log('Render thread closing...')


def run(config: config_module.Config):
  logging.log('Starting...')

  screen = display.create(config.display.type, config.display.flip)
  main_running = _thread.allocate_lock()
  thread_running = _thread.allocate_lock()
  try:
    main_running.acquire()
    slow_stations = set([config.slow_station]) if config.slow_station else None
    departure_updater = trains.DepartureUpdater(
        config.station,
        config.destination,
        config.rtt.endpoint,
        trains.make_basic_auth(
            username=config.rtt.username,
            password=config.rtt.password,
        ),
        slow_stations=slow_stations,
        min_departure_time=config.min_departure_time,
    )
    gc.collect()
    micropython.mem_info()
    gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())

    wlan = _connect(config.wifi.ssid, config.wifi.password, screen=screen)
    _configure_time()

    logging.log('Get initial train departures')
    # Don't show loading departures for e-Paper displays.
    if config.display.type != 'epd29b':
      widget = widgets.MessageWidget(
          screen, _LOADING_DEPARTURES, fonts.DEFAULT_FONT
      )
      widget.render()
      screen.flush()

    # Get first set of departures synchonously.
    departure_updater.update()
    gc.collect()

    logging.log('Start render loop')
    _ = _thread.start_new_thread(
        _render_thread,
        (screen, departure_updater, config, main_running, thread_running),
    )

    update_interval = config.rtt.update_interval
    logging.log('Start updating departures every {} seconds', update_interval)
    while True:
      for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
          departure_updater.update()
          gc.collect()
          break
        except (OSError, ValueError) as e:
          # Catch transient network or HTTP issues and retry
          if isinstance(e, OSError) and e.errno == errno.ECONNABORTED:
            logging.log('Received ECONNABORTED error, try reconnecting...')
            _reconnect(wlan, config.wifi.ssid, config.wifi.password)
          logging.log(
              'Train update attempt {}/{} failed!', attempt, _MAX_ATTEMPTS
          )
          if attempt < _MAX_ATTEMPTS:
            sys.print_exception(e)
          else:
            raise e

      for _ in range(update_interval):
        time.sleep(1)
  finally:
    logging.log('Main thread closing...')
    main_running.release()

    # Wait for thread lock to be released, which indicates the thread has
    # finished running (or was never started).
    with thread_running:
      screen.close()


async def _setup_access_point():
  ap = network.WLAN(network.AP_IF)
  ap.config(ssid=_SETUP_WIFI_SSID, password=_SETUP_WIFI_PASSWORD)
  ap.active(True)
  logging.log('Creating AP wifi with SSID: {}', _SETUP_WIFI_SSID)

  for _ in range(_CONNECT_TIMEOUT):
    if ap.isconnected():
      return ap
    await asyncio.sleep(1)

  raise OSError(
      'Failed to setup wifi access point in {} secs'.format(_CONNECT_TIMEOUT)
  )


async def setup(screen: display.Display):
  event = asyncio.Event()
  ap = await _setup_access_point()
  ip_address = ap.ifconfig()[0]

  setup_message = _SETUP_MESSAGE.format(
      _SETUP_WIFI_SSID, _SETUP_WIFI_PASSWORD, ip_address
  )
  logging.log(setup_message)

  widget = widgets.MessageWidget(screen, setup_message, fonts.DEFAULT_FONT)
  widget.render()
  screen.flush()

  def _write_config(cfg):
    _ = config_module.load(cfg)
    with open('config.json', 'w') as f:
      json.dump(cfg, f)

  web_server = await server.start(_write_config, event)
  await event.wait()
  web_server.close()
  screen.fill(0)
  screen.flush()
  await web_server.wait_closed()


def main():
  try:
    with open('config.json', 'r') as f:
      config = config_module.load(json.load(f))
  except OSError:
    screen = display.create()
    try:
      asyncio.run(setup(screen))
      machine.reset()
    finally:
      screen.close()

  if config.debug.log:
    logging.set_logging_file('debug.txt')
  run(config)


if __name__ == '__main__':
  try:
    main()
  except KeyboardInterrupt:
    logging.log('Keyboard interrupt!')
  except Exception as e:
    logging.log('Unhandled exception!')
    sys.print_exception(e)
    micropython.mem_info()
    raise e
  finally:
    logging.log('Shutdown')
    logging.on_exit()

    # Hard reset device to reset RAM. Although this should be unnecessary,
    # residual, fragmented memory seems to still exist.
    machine.reset()
