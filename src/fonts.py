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
"""Font class that wraps up a font_to_python module."""

import framebuf
import gc
import uctypes

import assets


class Font:
  """Helper class that wraps font_to_python module.

  Provides helper functions for rendering text into a given display."""

  def __init__(self, font, palette: framebuf.FrameBuffer):
    self._palette = palette

    # Cache per-character frame buffer to prevent re-allocs when rendering.
    self._chars_framebuf = []
    self._char_width = bytearray(font.max_ch() - font.min_ch() + 1)
    self._font = font

    for i in range(font.min_ch(), font.max_ch() + 1):
      buffer, height, width = font.get_ch(chr(i))
      self._chars_framebuf.append(
          framebuf.FrameBuffer(
              uctypes.bytearray_at(uctypes.addressof(buffer), len(buffer)),
              width,
              height,
              framebuf.MONO_HLSB,
              (width + 7) & -8,  # Round up to next multiple of 8.
          ),
      )
      self._char_width[i - font.min_ch()] = width

      # Need to call gc.collect() each loop to mitigate fragmentation.
      gc.collect()

  def render_text(
      self, text: str, framebuffer: framebuf.FrameBuffer, x: int, y: int
  ) -> None:
    """Renders text into the provided display at position [x, y]."""
    idx = 0
    for char in text:
      idx = ord(char) - self._font.min_ch()
      framebuffer.blit(self._chars_framebuf[idx], x, y, -1, self._palette)
      x += self._char_width[idx]

  def calculate_bounds(self, text: str) -> tuple[int, int]:
    """Calculates the bounds for a piece of text."""
    width, height = 0, 0
    for char in text:
      width += self._char_width[ord(char) - self._font.min_ch()]
      height = max(height, self._font.height())
    return width, height

  def max_bounds(self) -> tuple[int, int]:
    """Returns the max bounds for any given character."""
    return self._font.max_width(), self._font.height()


_PALETTE = framebuf.FrameBuffer(bytearray([0, 255]), 2, 1, framebuf.GS8)

DEFAULT_FONT = Font(assets.dot_matrix_regular, _PALETTE)
BOLD_FONT = Font(assets.dot_matrix_bold, _PALETTE)
TALL_FONT = Font(assets.dot_matrix_bold_tall, _PALETTE)
