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

import binascii
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


_RTT_ENDPOINT = 'https://api.rtt.io/api/v1/json'
_REQUEST_TIMEOUT = 10
_MAXRESPONSE_SIZE = 40 * 1024


def _calculate_departure_datetime(service) -> int:
  """Utility to calculate the full datetime in seconds.

  Because RTT only provides the service's origin date and not the date at the
  requested station, we have to calculate the date based on this origin date.

  We assume that services do not run for > 24hrs.
  """
  yyyy, month, dd = map(int, service['runDate'].split('-'))

  location = service['locationDetail']
  departure_time = int(location['gbttBookedDeparture'])
  if location.get('cancelReasonCode') is not None:
    departure_time = int(location.get('realtimeDeparture', departure_time))

  hh, mm = divmod(departure_time, 100)

  origin_hh, origin_mm = divmod(int(location['origin'][0]['publicTime']), 100)
  full_origin_departure_datetime = time.mktime(
      (yyyy, month, dd, origin_hh, origin_mm, 0, 0, 0)
  )

  full_departure_datetime = time.mktime((yyyy, month, dd, hh, mm, 0, 0, 0))
  if full_departure_datetime < full_origin_departure_datetime:
    # Iff we've wrapped around into the next day, add 24hrs to the departure
    # datetime.
    full_departure_datetime += 24 * 60 * 60  # 24hrs

  return full_departure_datetime


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


def make_basic_auth(username: str, password: str):
  auth = '{}:{}'.format(username, password)
  auth = str(binascii.b2a_base64(auth)[:-1], 'ascii')
  return auth


def _http_request(
    url: str,
    *,
    basic_auth: str | None = None,
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
    if basic_auth is not None:
      s.write('Authorization: Basic {}\r\n'.format(basic_auth))
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
          redirect = str(header[10:-2], 'utf-8')
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
    _http_request(
        redirect,
        basic_auth=basic_auth,
        timeout=timeout,
        buffer=buffer,
        ssl_context=ssl_context,
    )

  try:
    if buffer is not None:
      content_length = int(headers.get('Content-Length', -1))
      if content_length > -1 and len(buffer) < content_length:
        raise ValueError(
            'Content length > buffer! Content-length: {} Buffer {}'.format(
                content_length, len(buffer)
            )
        )
      else:
        length = s.readinto(buffer)
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
  ):
    self._destination = destination
    self._departure_time = departure_time
    self._actual_departure_time = actual_departure_time
    self._cancelled = cancelled

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

  def __repr__(self) -> str:
    return (
        'Departure(destination="{}", departure_time={},'
        'actual_departure_tume={}, cancelled={})'
    ).format(
        self.destination,
        self.departure_time,
        self.actual_departure_time,
        self.cancelled,
    )

  def __eq__(self, other: object) -> bool:
    return (
        isinstance(other, Departure)
        and self.departure_time == other.departure_time
        and self.actual_departure_time == other.actual_departure_time
        and self.cancelled == other.cancelled
        and self.destination == other.destination
    )


Station = collections.namedtuple('Station', ('name', 'departures'))


def get_departures(
    station: str,
    destination: str,
    basic_auth: str,
    min_departure_time: int = 0,
    buffer: memoryview | None = None,
    ssl_context: ssl.SSLContext | None = None,
) -> Station:
  """Requests set of departures from->to provided stations."""
  url = _RTT_ENDPOINT + '/search/{station}/to/{destination}'.format(
      station=station,
      destination=destination,
  )
  response = _http_request(
      url,
      basic_auth=basic_auth,
      timeout=_REQUEST_TIMEOUT,
      buffer=buffer,
      ssl_context=ssl_context,
  )
  if response.status_code != 200:
    raise ValueError('Error getting departure! {}'.format(response.status_code))

  # TODO: JSON decoding allocates a lot of small objects, which can put pressure
  # on memory fragmentation. Might be worth writing custom parsing of content.
  response_json = json.loads(response.content)
  services = response_json['services']
  services = [] if services is None else services

  departures = []
  for service in services:
    location = service['locationDetail']

    # We could have multiple destinations, so concatentate them together.
    destination = ','.join([d['description'] for d in location['destination']])
    departure_time = int(location['gbttBookedDeparture'])
    realtime_departure = int(location.get('realtimeDeparture', departure_time))
    cancelled = location.get('cancelReasonCode') is not None

    if min_departure_time > 0:
      full_departure_datetime = _calculate_departure_datetime(service)
      now = time.mktime(utils.get_uk_time())
      if now + (min_departure_time * 60) > full_departure_datetime:
        continue

    departures.append(
        Departure(destination, departure_time, realtime_departure, cancelled)
    )

  results = Station(response_json['location']['name'], departures)
  del response_json
  gc.collect()  # Explicitly delete and GC JSON objects.
  return results


class DepartureUpdater:
  """Class that updates departures for a given station periodically."""

  def __init__(
      self,
      station: str,
      destination: str,
      auth: str,
      min_departure_time: int,
  ):
    self._station = station
    self._destination = destination
    self._auth = auth
    self._min_departure_time = min_departure_time

    self._lock = _thread.allocate_lock()
    self._departures = Station(station, tuple())
    self._buffer = bytearray(_MAXRESPONSE_SIZE)
    self._memoryview = memoryview(self._buffer)
    self._ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

  def update(self):
    """Updates the set of departures for a given station."""
    departures = get_departures(
        self._station,
        self._destination,
        self._auth,
        self._min_departure_time,
        self._memoryview,
        self._ssl_context,
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
