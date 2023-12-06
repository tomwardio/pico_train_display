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
"""Collection of utility functions used by multiple modules."""

import time


def get_uk_time() -> tuple[int, ...]:
  """Calculate UK time, taking into account daylight savings."""
  year = time.localtime()[0]
  bst_start = time.mktime(
      (year, 3, 31 - ((5 * year // 4 + 4) % 7), 1, 0, 0, 0, 0, 0)
  )
  bst_end = time.mktime(
      (year, 10, 31 - ((5 * year // 4 + 1) % 7), 1, 0, 0, 0, 0, 0)
  )
  now = time.time()
  if now >= bst_start and now < bst_end:
    return time.localtime(now + 3600)
  else:
    return time.localtime(now)
