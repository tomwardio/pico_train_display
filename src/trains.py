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
"""Module for communicating with RTT API."""

import collections
import errno
import json
import gc
import select
import socket
import ssl
import time
import _thread

import utils
import logging


_REQUEST_TIMEOUT = 10
_MAXRESPONSE_SIZE = 40 * 1024
_TOKEN_REFRESH_MARGIN = 60


def _parse_iso_datetime(dt: str) -> int:
  """Parses an ISO 8601 / RFC3339 datetime string into UTC epoch seconds."""
  yyyy = int(dt[0:4])
  month = int(dt[5:7])
  dd = int(dt[8:10])
  hh = int(dt[11:13])
  mm = int(dt[14:16])
  ss = int(dt[17:19])

  tz_offset = 0
  rest = dt[19:]
  if rest.startswith('.'):
    i = 1
    while i < len(rest) and '0' <= rest[i] <= '9':
      i += 1
    rest = rest[i:]

  if rest and rest != 'Z' and rest != 'z':
    sign = 1 if rest[0] == '+' else -1
    tz_parts = rest[1:].replace(':', '')
    tz_hh = int(tz_parts[0:2])
    tz_mm = int(tz_parts[2:4]) if len(tz_parts) >= 4 else 0
    tz_offset = sign * (tz_hh * 3600 + tz_mm * 60)

  return int(time.mktime((yyyy, month, dd, hh, mm, ss, 0, 0, 0))) - tz_offset


def _utc_to_uk_hhmm(utc_seconds: int) -> int:
  """Converts UTC epoch seconds to a UK local time HHMM integer."""
  uk_time = utils.get_uk_time(utc_seconds)
  return uk_time[3] * 100 + uk_time[4]


# TODO: Make this a dataclass when MicroPython supports it.
class Response:

  def __init__(self, status_code: int, headers: dict[str, str], content):
    self._status_code = status_code
    self._headers = headers
    self._content = content

  @property
  def status_code(self):
    return self._status_code

  @property
  def content(self):
    return self._content

  @property
  def headers(self):
    return self._headers

  def __repr__(self) -> str:
    return 'Response(status_code={}, headers={}, content={}'.format(
        self.status_code, self.headers, self.content
    )


def _http_request(
    url: str,
    *,
    bearer_token: str | None = None,
    timeout: int | None = None,
    buffer: memoryview | None = None,
    ssl_context: ssl.SSLContext | None = None,
) -> Response:
  """Send HTTP GET request and return Response.

  This is heavily influenced by urequests.get(), with a couple of modifications:
    - Simplify code by not supporting sending params with GET
    - Support passing a pre-allocated buffer for response body, to help
      alleviate memory fragmentation.
    - Fix for transient EINPROGRESS error thrown from connect when using
      timeouts.
  """
  proto, _, host, path = url.split('/', 3)
  redirect = None

  if proto == 'http:':
    port = 80
  elif proto == 'https:':
    port = 443
  else:
    raise ValueError('Unsupported protocol: ' + proto)

  if ':' in host:
    host, port = host.split(':', 1)
    port = int(port)

  addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0]

  s = socket.socket(addr[0], socket.SOCK_STREAM, addr[2])

  try:
    s.connect(addr[-1])

    p = select.poll()
    p.register(s, select.POLLOUT)
    result = p.poll(timeout if timeout is not None else -1)
    if not result:
      raise OSError(errno.ETIMEDOUT, 'Timed out connecting to socket.')

    if timeout is not None:
      s.settimeout(timeout)

    if proto == 'https:':
      if ssl_context is not None:
        s = ssl_context.wrap_socket(s, server_hostname=host)
      else:
        s = ssl.wrap_socket(s, server_hostname=host)

    s.write('GET /{} HTTP/1.0\r\n'.format(path))
    s.write('Host: {}\r\n'.format(host))
    if bearer_token is not None:
      s.write('Authorization: Bearer {}\r\n'.format(bearer_token))
    s.write('Connection: close\r\n\r\n')

    http_status = s.readline().split(None, 2)
    if len(http_status) < 2:
      raise ValueError('HTTP error: bad status "{}"'.format(http_status))

    status = int(http_status[1])

    # Parse response headers.
    headers = {}
    while True:
      header = s.readline()
      if not header or header == b'\r\n':
        break
      if header.startswith(b'Location:') and not 200 <= status <= 299:
        if status in [301, 302, 303, 307, 308]:
          redirect = str(header[9:].strip(), 'utf-8')
        else:
          raise NotImplementedError('Redirect %d not yet supported!' % status)
      else:
        header = str(header, 'utf-8')
        k, v = header.split(':', 1)
        headers[k] = v.strip()

  except Exception:
    # Always close socket on any exception
    s.close()
    raise

  if redirect is not None:
    s.close()
    return _http_request(
        redirect,
        bearer_token=bearer_token,
        timeout=timeout,
        buffer=buffer,
        ssl_context=ssl_context,
    )

  try:
    if status == 204:
      content = b''
    elif buffer is not None:
      content_length = int(headers.get('content-length', -1))
      if content_length > -1 and len(buffer) < content_length:
        raise ValueError(
            'Content length > buffer! Content-length: {} Buffer {}'.format(
                content_length, len(buffer)
            )
        )
      else:
        length = s.readinto(buffer) or 0
        content = buffer[:length]
    else:
      content = s.read()
  finally:
    s.close()

  return Response(status, headers, content)


# TODO: Make this a dataclass when MicroPython supports dataclasses
class Departure:
  """Class that encapsulates a train departure's data to be displayed."""

  def __init__(
      self,
      destination: str,
      departure_time: int,
      actual_departure_time: int,
      cancelled: bool,
      fast_train: bool,
  ):
    self._destination = destination
    self._departure_time = departure_time
    self._actual_departure_time = actual_departure_time
    self._cancelled = cancelled
    self._fast_train = fast_train

  @property
  def destination(self) -> str:
    return self._destination

  @property
  def departure_time(self) -> int:
    return self._departure_time

  @property
  def actual_departure_time(self) -> int:
    return self._actual_departure_time

  @property
  def cancelled(self) -> bool:
    return self._cancelled

  @property
  def fast_train(self) -> bool:
    return self._fast_train

  def __repr__(self) -> str:
    return (
        'Departure(destination="{}", departure_time={},'
        'actual_departure_tume={}, cancelled={}, fast={})'
    ).format(
        self.destination,
        self.departure_time,
        self.actual_departure_time,
        self.cancelled,
        self.fast_train,
    )

  def __eq__(self, other: object) -> bool:
    return (
        isinstance(other, Departure)
        and self.departure_time == other.departure_time
        and self.actual_departure_time == other.actual_departure_time
        and self.cancelled == other.cancelled
        and self.destination == other.destination
        and self.fast_train == other.fast_train
    )


Station = collections.namedtuple('Station', ('name', 'departures'))


def get_access_token(
    refresh_token: str,
    endpoint: str,
    *,
    buffer: memoryview | None = None,
    ssl_context: ssl.SSLContext | None = None,
) -> tuple[str, int]:
  """Requests a short-lived bearer access token using a refresh token."""
  url = endpoint.rstrip('/') + '/api/get_access_token'
  response = _http_request(
      url,
      bearer_token=refresh_token,
      timeout=_REQUEST_TIMEOUT,
      buffer=buffer,
      ssl_context=ssl_context,
  )
  if response.status_code != 200:
    raise ValueError(
        'Error getting access token! {}'.format(response.status_code)
    )

  response_json = json.loads(response.content)
  token = response_json['token']
  valid_until_str = response_json.get('validUntil')
  valid_until = _parse_iso_datetime(valid_until_str) if valid_until_str else 0
  del response_json
  gc.collect()
  return token, valid_until


def _get_service_ids(
    station: str,
    destination: str,
    bearer_token: str,
    endpoint: str,
    *,
    buffer: memoryview | None = None,
    ssl_context: ssl.SSLContext | None = None,
) -> set[str]:
  """Returns uniqueIdentity set for services from station calling at destination."""
  url = (
      endpoint.rstrip('/')
      + '/gb-nr/location?code={station}&filterTo={destination}'.format(
          station=station,
          destination=destination,
      )
  )
  response = _http_request(
      url,
      bearer_token=bearer_token,
      timeout=_REQUEST_TIMEOUT,
      buffer=buffer,
      ssl_context=ssl_context,
  )
  if response.status_code == 204:
    return set()
  if response.status_code == 401:
    raise ValueError('Unauthorized getting departure! 401')
  if response.status_code != 200:
    raise ValueError('Error getting departure! {}'.format(response.status_code))

  response_json = json.loads(response.content)
  service_ids = set()
  for service in response_json.get('services') or []:
    uid = (service.get('scheduleMetadata') or {}).get('uniqueIdentity')
    if uid:
      service_ids.add(uid)
  del response_json
  gc.collect()
  return service_ids


def get_departures(
    station: str,
    destination: str,
    bearer_token: str,
    endpoint: str,
    *,
    min_departure_time: int = 0,
    buffer: memoryview | None = None,
    ssl_context: ssl.SSLContext | None = None,
    slow_stations: set[str] | None = None,
) -> Station:
  """Requests set of departures from->to provided stations."""
  url = endpoint + '/gb-nr/location?code={station}&filterTo={destination}'.format(
      station=station,
      destination=destination,
  )
  response = _http_request(
      url,
      bearer_token=bearer_token,
      timeout=_REQUEST_TIMEOUT,
      buffer=buffer,
      ssl_context=ssl_context,
  )
  if response.status_code == 204:
    return Station(station, [])
  if response.status_code == 401:
    raise ValueError('Unauthorized getting departure! 401')
  if response.status_code != 200:
    raise ValueError('Error getting departure! {}'.format(response.status_code))

  limit = response.headers.get('x-ratelimit-limit-minute', -1)
  remaining = response.headers.get('x-ratelimit-remaining-minute', -1)
  logging.log('Rate limit {}/min, remaining: {}'.format(limit, remaining))

  # TODO: JSON decoding allocates a lot of small objects, which can put pressure
  # on memory fragmentation. Might be worth writing custom parsing of content.
  response_json = json.loads(response.content)
  services = response_json.get('services') or []

  results = []
  for service in services:
    temporal_data = service.get('temporalData') or {}
    departure = temporal_data.get('departure')
    if not departure or not departure.get('scheduleAdvertised'):
      continue

    scheduled_str = departure['scheduleAdvertised']
    realtime_str = (
        departure.get('realtimeActual')
        or departure.get('realtimeForecast')
        or departure.get('realtimeEstimate')
        or scheduled_str
    )
    cancelled = (
        bool(departure.get('isCancelled'))
        or temporal_data.get('displayAs') in ('CANCELLED', 'DIVERTED')
    )

    scheduled_utc = _parse_iso_datetime(scheduled_str)
    realtime_utc = (
        _parse_iso_datetime(realtime_str)
        if realtime_str != scheduled_str
        else scheduled_utc
    )

    if min_departure_time > 0:
      effective_utc = scheduled_utc if cancelled else realtime_utc
      if time.time() + (min_departure_time * 60) > effective_utc:
        continue

    departure_time = _utc_to_uk_hhmm(scheduled_utc)
    realtime_departure = _utc_to_uk_hhmm(realtime_utc)

    # We could have multiple destinations, so concatenate them together.
    destinations = service.get('destination') or []
    dest_name = ','.join([d['location']['description'] for d in destinations])
    uid = (service.get('scheduleMetadata') or {}).get('uniqueIdentity')

    results.append(
        (uid, dest_name, departure_time, realtime_departure, cancelled)
    )

  station_name = (
      response_json.get('query', {}).get('location', {}).get('description')
      or station
  )
  del response_json
  gc.collect()  # Explicitly delete and GC JSON objects before reusing buffer.

  slow_service_ids = set()
  if slow_stations and results:
    for slow_station in slow_stations:
      slow_service_ids.update(
          _get_service_ids(
              station,
              slow_station,
              bearer_token,
              endpoint,
              buffer=buffer,
              ssl_context=ssl_context,
          )
      )

  departures = [
      Departure(
          dest_name,
          departure_time,
          realtime_departure,
          cancelled,
          bool(slow_stations and uid and uid not in slow_service_ids),
      )
      for uid, dest_name, departure_time, realtime_departure, cancelled in results
  ]
  return Station(station_name, departures)


class DepartureUpdater:
  """Class that updates departures for a given station periodically."""

  def __init__(
      self,
      station: str,
      destination: str,
      endpoint: str,
      token: str,
      min_departure_time: int,
      *,
      slow_stations: set[str] | None = None,
  ):
    self._station = station
    self._destination = destination
    self._endpoint = endpoint
    self._refresh_token = token
    self._access_token = None
    self._token_valid_until = 0
    self._min_departure_time = min_departure_time
    self._slow_stations = slow_stations

    self._lock = _thread.allocate_lock()
    self._departures = Station(station, tuple())
    self._buffer = bytearray(_MAXRESPONSE_SIZE)
    self._memoryview = memoryview(self._buffer)
    self._ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

  def _get_access_token(self, force: bool = False) -> str:
    if (
        force
        or self._access_token is None
        or time.time() >= self._token_valid_until - _TOKEN_REFRESH_MARGIN
    ):
      self._access_token, self._token_valid_until = get_access_token(
          self._refresh_token,
          self._endpoint,
          buffer=self._memoryview,
          ssl_context=self._ssl_context,
      )
    return self._access_token

  def update(self):
    """Updates the set of departures for a given station."""
    access_token = self._get_access_token()
    departures = get_departures(
        self._station,
        self._destination,
        access_token,
        self._endpoint,
        slow_stations=self._slow_stations,
        min_departure_time=self._min_departure_time,
        buffer=self._memoryview,
        ssl_context=self._ssl_context,
    )
    with self._lock:
      self._departures = departures

  def departures(self) -> tuple[Departure, ...]:
    """Returns tuple of departures."""
    with self._lock:
      return self._departures.departures

  def station(self) -> str:
    with self._lock:
      return self._departures.name
