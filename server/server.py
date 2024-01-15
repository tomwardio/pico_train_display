# Copyright (c) 2024 Tom Ward
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
"""Basic webserver to filter response and include calling at stations."""

import asyncio
from typing import Any

import aiohttp
import logging
import flask
from flask import Flask

_MAX_ATTEMPTS = 3
_RTT_ENDPOINT = 'https://api.rtt.io/api/v1/json'

app = Flask(__name__)


async def _get_calling_at(session: aiohttp.ClientSession, uid: str, date: str):
  yyyy, mm, dd = date.split('-')
  async with session.get(
      f'{_RTT_ENDPOINT}/service/{uid}/{yyyy}/{mm}/{dd}'
  ) as response:
    if response.status == 200:
      return uid, [
          location['crs'] for location in (await response.json())['locations']
      ]
  return uid, None


async def _get_calling_stations(session: aiohttp.ClientSession, search_result):
  services = search_result.get('services')
  tasks = {
      _get_calling_at(session, service['serviceUid'], service['runDate'])
      for service in services
  }
  calling_stations = {
      uid: stations for (uid, stations) in await asyncio.gather(*tasks)
  }
  for service in services:
    if stations := calling_stations.get(service['serviceUid']):
      service['callingAt'] = stations

  return search_result


async def _get_trains(
    session: aiohttp.ClientSession, station: str, destination: str
) -> tuple[Any, int, dict[str, Any]]:
  async with await session.get(
      f'{_RTT_ENDPOINT}/search/{station}/to/{destination}'
  ) as response:
    if response.status != 200:
      return await response.content.read(), response.status, response.headers
    input = await response.json()

    result = {'location': {'name': input['location']['name']}}
    for service in input.get('services', []):
      location = service['locationDetail']

      out_service = {
          'locationDetail': {
              'destination': [
                  {'description': d['description']}
                  for d in location['destination']
              ],
              'gbttBookedDeparture': location['gbttBookedDeparture'],
              'origin': [
                  {'publicTime': origin['publicTime']}
                  for origin in location['origin']
              ],
          },
          'serviceUid': service['serviceUid'],
          'runDate': service['runDate'],
      }

      if destination := service.get('destination'):
        out_service['destination'] = [
            {'description': d['description']} for d in location['destination']
        ]
      if cancelled := location.get('cancelReasonCode'):
        out_service['locationDetail']['cancelReasonCode'] = cancelled
      if realtime_departure := location.get('realtimeDeparture'):
        out_service['locationDetail']['realtimeDeparture'] = realtime_departure
      result.setdefault('services', []).append(out_service)

    return result, response.status, response.headers


@app.route('/api/v1/json/search/<station>/to/<destination>')
async def search(station: str, destination: str):
  auth = flask.request.authorization
  if auth and auth.type == 'basic':
    async with aiohttp.ClientSession(
        auth=aiohttp.BasicAuth(auth.username, auth.password)
    ) as session:
      for i in range(1, _MAX_ATTEMPTS + 1):
        try:
          result, status_code, headers = await _get_trains(
              session, station, destination
          )
          if status_code == 200:
            result = await _get_calling_stations(session, result)
          break
        except aiohttp.ClientConnectionError as e:
          logging.warning(f'Connection error {i} of 3! error: {e}')
          await asyncio.sleep(1)

      headers = headers.copy()
      del headers['content-length']
      return result, status_code, headers.items()
  else:
    return flask.Response(
        status=401, headers={'WWW-Authenticate': 'Basic realm="RTT API"'}
    )


if __name__ == '__main__':
  app.run(host='0.0.0.0', port=8000, debug=True)
