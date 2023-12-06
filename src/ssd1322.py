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
"""Implementation of SSD 1322 display driver.

Datasheet: https://www.hpinfotech.ro/SSD1322.pdf
"""

import time

import framebuf
import machine

import display


class SSD1322(display.Display):
  """SSD1322 SPI-4 display driver."""

  def __init__(
      self,
      spi: machine.SPI,
      cs: machine.Pin,
      dc: machine.Pin,
      rst: machine.Pin,
      width: int = 256,
      height: int = 64,
      flip_display: bool = False,
  ):
    self.spi = spi
    self.cs = cs
    self.dc = dc
    self.rst = rst

    self.cs.init(self.cs.OUT, value=1)
    self.dc.init(self.dc.OUT, value=0)
    self.rst.init(self.rst.OUT, value=1)

    self._width = width
    self._height = height
    self._buffer = bytearray(self._width // 2 * self._height)

    super().__init__(self._buffer, width, height, framebuf.GS4_HMSB)
    self.fill(0)

    self._init_display(flip_display)

  def _init_display(self, flip_display: bool):
    self._reset()

    # fmt: off
    self.write_cmd(0xFD, 0x12)        # Unlock IC
    self.write_cmd(0xA4)              # Display off (all pixels off)
    self.write_cmd(0xB3, 0x91)        # Display divide clockratio/freq
    self.write_cmd(0xCA, 0x3F)        # Set MUX ratio
    self.write_cmd(0xA2, 0x00)        # Display offset
    self.write_cmd(0xA1, 0x00)        # Display start Line
    arg = 0x06 if flip_display else 0x14
    self.write_cmd(0xA0, arg, 0x11)   # Set remap & dual COM Line
    self.write_cmd(0xB5, 0x00)        # Set GPIO (disabled)
    self.write_cmd(0xAB, 0x01)        # Function select (internal Vdd)
    self.write_cmd(0xB4, 0xA0, 0xFD)  # Display enhancement A (External VSL)
    self.write_cmd(0xC1, 0x7F)        # Set contrast current (default)
    self.write_cmd(0xC7, 0x0F)        # Master contrast (reset)
    self.write_cmd(0xB9)              # Set default greyscale table
    self.write_cmd(0xB1, 0xF0)        # Phase length
    self.write_cmd(0xD1, 0x82, 0x20)  # Display enhancement B (reset)
    self.write_cmd(0xBB, 0x0D)        # Pre-charge voltage
    self.write_cmd(0xB6, 0x08)        # 2nd precharge period
    self.write_cmd(0xBE, 0x00)        # Set VcomH
    self.write_cmd(0xA6)              # Normal display (reset)
    self.write_cmd(0xA9)              # Exit partial display
    self.write_cmd(0xAF)              # Display on
    # fmt: on

    self.fill(0)
    self.flush()

  def _reset(self):
    self.rst(0)
    time.sleep_ms(50)
    self.rst(1)
    time.sleep_ms(100)

  @property
  def width(self) -> int:
    return self._width

  @property
  def height(self) -> int:
    return self._height

  def close(self):
    self.fill(0)
    self.sleep()
    self.write_cmd(0xA4)  # Display off

  def sleep(self):
    self.write_cmd(0xAE)
    self.write_cmd(0xAB, 0x00)

  def awake(self):
    self.write_cmd(0xAB, 0x01)
    self.write_cmd(0xAF)

  def write_cmd(self, cmd, *args):
    self.dc(0)
    self.cs(0)
    self.spi.write(bytearray([cmd]))
    self.cs(1)

    if len(args) > 0:
      self.write_data(bytearray(args))

  def write_data(self, data):
    self.dc(1)
    self.cs(0)
    self.spi.write(data)
    self.cs(1)

  def flush(self):
    offset = (480 - self._width) // 2
    col_start = offset // 4
    col_end = col_start + self.width // 4 - 1
    self.write_cmd(0x15, col_start, col_end)
    self.write_cmd(0x75, 0, self._height - 1)
    self.write_cmd(0x5C)
    self.write_data(self._buffer)
