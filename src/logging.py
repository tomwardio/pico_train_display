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
"""Simple logging library that both logs to screen and file."""

import os
import time

_logging_file = None


def set_logging_file(path: str):
  # Open file in append mode so that we accumulate logs.
  global _logging_file
  _logging_file = open(path, 'a')
  os.dupterm(_logging_file)


def _log_message(prefix: str, msg, *args, **kwargs):
  args = args or []
  kwargs = kwargs or {}
  msg = '{} {}'.format(prefix, str(msg).format(*args, **kwargs))
  print(msg)


def log(msg, *args, **kwargs):
  now = time.localtime()
  prefix = '[{:0>2}:{:0>2}:{:0>2}]'.format(now[3], now[4], now[5])
  _log_message(prefix, msg, *args, **kwargs)


def on_exit():
  if _logging_file is not None:
    os.dupterm(None)
    _logging_file.flush()
    _logging_file.close()
