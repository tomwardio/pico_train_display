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
"""Implementation of e-Paper 2.9" display driver.

Datasheet: https://files.waveshare.com/upload/a/af/2.9inch-e-paper-b-v3-specification.pdf
"""

import math
import time

import framebuf
import machine
import micropython

import display


def _set_array(buffer: memoryview, value: int):
  """Helper to set all bytes in an array to a certain value."""

  @micropython.viper
  def _set_array_impl(x: ptr8, length: int, v: int):  # type: ignore
    for i in range(length):
      x[i] = v

  _set_array_impl(buffer, len(buffer), value)


def _invert_array(buffer: memoryview):
  """Helper to invert all bits in a byte array."""

  @micropython.viper
  def _invert_array_impl(x: ptr8, length: int):  # type: ignore
    for i in range(length):
      x[i] ^= 0xFF

  _invert_array_impl(buffer, len(buffer))


def _set_pixel(buf: memoryview, x: int, y: int, bytes_per_row: int):
  """Helper to set bit for a pixel and position (x, y)."""
  buf[y * bytes_per_row + (x // 8)] |= 1 << 7 - (x % 8)


def _is_pixel_set(buf: memoryview, x: int, y: int, bytes_per_row: int) -> bool:
  """Helper to determine whether a pixel bit is set or not."""
  return buf[y * bytes_per_row + (x // 8)] & (1 << 7 - (x % 8)) != 0


class EPD29B(display.Display):
  """E-paper display 2.9inch model B."""

  def __init__(
      self,
      spi: machine.SPI,
      cs: machine.Pin,
      dc: machine.Pin,
      rst: machine.Pin,
      busy: machine.Pin,
      width: int = 296,
      height: int = 128,
      rotate: bool = True,
  ):
    self.spi = spi
    self.cs = cs
    self.dc = dc
    self.rst = rst
    self.busy = busy

    self.cs.init(self.cs.OUT, value=1)
    self.dc.init(self.dc.OUT, value=0)
    self.rst.init(self.rst.OUT, value=1)
    self.busy.init(self.busy.IN, value=1)

    self._width = width
    self._height = height

    self._black_buffer = bytearray(self._width * self._height // 8)
    self._black_memoryview = memoryview(self._black_buffer)
    super().__init__(self._black_buffer, width, height, framebuf.MONO_HLSB)

    self._red_buffer = bytearray(self._width * self._height // 8)
    self._red_memoryview = memoryview(self._red_buffer)
    self._red = framebuf.FrameBuffer(
        self._red_memoryview, width, height, framebuf.MONO_HLSB
    )

    self._rotate = rotate
    self._buffer = bytearray(self._width * self._height // 8)
    self._memory_view = memoryview(self._buffer)

    self.clear()
    self._init_display()

  def _init_display(self):
    self._reset()

    self.write_cmd(0x04)
    self._wait_busy()

    self.write_cmd(0x00, 0x0F, 0x89)  # Panel configuration
    self.write_cmd(0x50, 0x77)  # Set VCOM and data interval.
    self.write_cmd(0x61, 0x80, 0x01, 0x28)  # Display resolution start and end.

  def clear(self):
    self.fill(0)
    self.red.fill(0)

  def _reset(self):
    self.rst(1)
    time.sleep_ms(50)
    self.rst(0)
    time.sleep_ms(2)
    self.rst(1)
    time.sleep_ms(50)

  @micropython.native
  def _wait_busy(self):
    cmd = bytearray([0x71])
    self.write_cmd(cmd)
    while self.busy.value() == 0:
      self.write_cmd(cmd)
      time.sleep_ms(10)

  @property
  def width(self) -> int:
    return self._width

  @property
  def height(self) -> int:
    return self._height

  @property
  def red(self) -> framebuf.FrameBuffer:
    return self._red

  def close(self):
    self.clear()
    self.flush()
    self.sleep()

  def sleep(self):
    self.write_cmd(0x02)
    self._wait_busy()
    self.write_cmd(0x07, 0xA5)

  def awake(self):
    self._init_display()

  def write_cmd(self, cmd: int | bytearray | memoryview, *args):
    self.dc(0)
    self.cs(0)
    cmd = bytearray([cmd]) if isinstance(cmd, int) else cmd
    self.spi.write(cmd)
    self.cs(1)

    if len(args) > 0:
      self.write_data(bytearray(args))

  def write_data(self, data):
    self.dc(1)
    self.cs(0)
    self.spi.write(data)
    self.cs(1)

  def flush(self):
    self.write_cmd(0x10)
    self.write_data(self._convert(self._black_memoryview))

    self.write_cmd(0x13)
    self.write_data(self._convert(self._red_memoryview))
    self._refresh()

  def _refresh(self):
    self.write_cmd(0x12)
    self._wait_busy()

  @micropython.native
  def _convert(self, src: memoryview) -> memoryview:
    """Converts an internal frame buffer to ePaper format.

    This typically means rotating if we're rendering in landscape, and inverting
    colors so that 0 == black, 255 = white/red.
    """
    if self._rotate:
      dst = self._memory_view
      _set_array(dst, 0)

      src_bytes_per_row = int(math.ceil(self._width / 8))
      dst_bytes_per_row = int(math.ceil(self._height / 8))

      for x in range(self._width):
        for y in range(self._height):
          if _is_pixel_set(src, x, y, src_bytes_per_row):
            _set_pixel(dst, self._height - y - 1, x, dst_bytes_per_row)
      _invert_array(dst)
      return memoryview(self._buffer)
    else:
      dst = self._memory_view
      for i in range(len(src)):
        dst[i] = src[i]
      _invert_array(dst)
      return dst
