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
"""Module for parsing active times."""

import re
import time

import micropython


_ACTIVE_TIMES_REGEX = re.compile(r'(daily|weekdays|weekend):(\d+)-(\d+)$')


# TODO: Make this an enum when micropython supports such a thing
class Dates:
  DAILY = micropython.const(0)
  WEEKDAYS = micropython.const(1)
  WEEKEND = micropython.const(2)


class TimeRange:

  def __init__(self, dates: Dates, start_hhmm: int, end_hhmm: int):
    self._dates = dates
    self._start_hh, self._start_mm = divmod(start_hhmm, 100)
    self._end_hh, self._end_mm = divmod(end_hhmm, 100)

  def in_range(self, t: tuple[int, ...]) -> bool:
    day = t[6]
    if self._dates == Dates.WEEKDAYS and day > 5:
      return False
    elif self._dates == Dates.WEEKEND and day <= 5:
      return False

    start_time = time.mktime(
        (t[0], t[1], t[2], self._start_hh, self._start_mm, 0, 0, 0)
    )
    end_time = time.mktime(
        (t[0], t[1], t[2], self._end_hh, self._end_mm, 0, 0, 0)
    )

    now_time = time.mktime(t)
    return now_time >= start_time and now_time <= end_time


def parse(config: str) -> TimeRange:
  m = _ACTIVE_TIMES_REGEX.match(config)
  if m is None:
    raise ValueError('Failed to parse active time! value={}'.format(config))

  date_cfg = m.group(1).lower()
  if date_cfg == 'daily':
    dates = Dates.DAILY
  elif date_cfg == 'weekdays':
    dates = Dates.WEEKDAYS
  elif date_cfg == 'weekend':
    dates = Dates.WEEKEND
  else:
    raise ValueError('Unrecognized dates configuration! "{}"'.format(date_cfg))

  return TimeRange(dates, int(m.group(2)), int(m.group(3)))
