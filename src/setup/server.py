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

# Copyright 2023 Tom Ward
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Basic HTTP server for setting up train display."""

import asyncio
import json
import re

from setup import content


# Basic regex to extract key, an optional sub-key, and optional type. Examples:
# "foo" => key=foo, sub-key=None, type=None
# "foo[bar] => key=foo, sub-key=bar, type=None"
# "foo[bar]:int => key=foo, sub-key=bar, type=int"
_JSON_KEY_REGEX = re.compile(r'(\w+)\[?(\w*)\]?:?(\w*)')


def _parse_json_request(data: dict[str, str]):
  """Parse dictionary keys to create sub-keys and value types."""
  result = {}
  for k, v in data.items():
    match = _JSON_KEY_REGEX.match(k)
    if match is None:
      raise ValueError(f'Failed to parse key! key={k}')
    key, sub_key, value_type = match.group(1), match.group(2), match.group(3)
    if value_type:
      if value_type == 'int':
        v = int(v)
      elif value_type == 'bool':
        if v.lower() in {'on', 'true'}:
          v = True
        elif v.lower() in {'off', 'false'}:
          v = False
        else:
          ValueError(f'Unrecognized boolean value for key {k}, {v=}')
      else:
        raise ValueError(f'Unrecognized value type for key "{k}"')

    if sub_key:
      result.setdefault(key, {})[sub_key] = v
    else:
      result[key] = v
  return result


async def _parse_headers(reader: asyncio.StreamReader):
  """Helper to parse HTML headers."""
  headers = {}
  while True:
    header = await reader.readline()
    if header == b'\r\n':
      break
    name, value = header.decode().strip().split(': ', 1)
    headers[name.lower()] = value
  return headers


async def _read_request(reader: asyncio.StreamReader):
  """Helper to request HTML request."""
  headers = await _parse_headers(reader)

  content_length = int(headers.get('content-length', 0))
  content_type = headers.get('content-type')

  content = None
  if content_length > 0:
    content = await reader.readexactly(content_length)
    if content_type == 'application/json':
      content = _parse_json_request(json.loads(content.decode()))
    else:
      raise ValueError(f'Unrecognized request content! {content_type=}')

  return content


_STATUS_TO_MESSAGE = {
    200: 'OK',
    201: 'Created',
    202: 'Accepted',
    203: 'Non-Authoritative Information',
    204: 'No Content',
    205: 'Reset Content',
    206: 'Partial Content',
    300: 'Multiple Choices',
    301: 'Moved Permanently',
    302: 'Found',
    303: 'See Other',
    304: 'Not Modified',
    305: 'Use Proxy',
    306: 'Switch Proxy',
    307: 'Temporary Redirect',
    308: 'Permanent Redirect',
    400: 'Bad Request',
    401: 'Unauthorized',
    403: 'Forbidden',
    404: 'Not Found',
    405: 'Method Not Allowed',
    406: 'Not Acceptable',
    408: 'Request Timeout',
    409: 'Conflict',
    410: 'Gone',
    414: 'URI Too Long',
    415: 'Unsupported Media Type',
    416: 'Range Not Satisfiable',
    500: 'Internal Server Error',
    501: 'Not Implemented',
}


async def _write_response(
    writer: asyncio.StreamWriter,
    status: int,
    *,
    headers={},
    content: bytes | None = None,
    content_type: str | None = None,
):
  status_message = _STATUS_TO_MESSAGE[status]
  writer.write(f'HTTP/1.1 {status} {status_message}\r\n'.encode('utf8'))
  for k, v in headers.items():
    writer.write(f'{k}: {v}\r\n'.encode('utf8'))

  if content is not None:
    if content_type is None:
      raise ValueError('Must provide content_type if the response has content')

    writer.write(f'Content-Type: {type}\r\n'.encode('utf8'))
    writer.write(f'Content-Length: {len(content)}\r\n'.encode('utf8'))
    writer.write('\r\n'.encode('utf8'))
    writer.write(content)
  else:
    writer.write('\r\n'.encode('utf8'))
    await writer.drain()

  writer.close()
  await writer.wait_closed()


async def _server_request(
    close_event: asyncio.Event,
    callback,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
):
  request = await reader.readline()
  try:
    method, uri, _ = request.decode().split()
  except:
    await _write_response(
        writer, 500, content='Error parsing request!'.encode('utf8')
    )
    raise

  request_content = await _read_request(reader)
  if uri == '/':
    await _write_response(
        writer, 200, content=content.data(), content_type='text/html'
    )
  elif uri == '/submit' and method == 'POST':
    try:
      callback(request_content)
      await _write_response(writer, 200)
      close_event.set()
    except ValueError as e:
      await _write_response(
          writer, 404, content=str(e).encode('utf8'), content_type='text/plain'
      )
    except:
      await _write_response(writer, 500)
      raise


async def start(callback, event: asyncio.Event) -> asyncio.Server:
  # TODO: Use functools.partial when supported in MicroPython.
  func = lambda reader, writer: _server_request(event, callback, reader, writer)
  return await asyncio.start_server(func, '0.0.0.0', 80)
