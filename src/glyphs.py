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
"""Icons class that wraps up a font_to_python module."""

import framebuf
import uctypes

import assets


class Glyph:
  """Helper class that wraps data_to_py module.

  Provides helper functions for rendering glyphs into a given display."""

  def __init__(self, glyph):
    self._glyph = glyph
    self._framebuf = framebuf.FrameBuffer(
        uctypes.bytearray_at(
            uctypes.addressof(glyph.data()), len(glyph.data())
        ),
        glyph.width(),
        glyph.height(),
        framebuf.GS8,
    )

  def render_glyph(
      self, framebuffer: framebuf.FrameBuffer, x: int, y: int
  ) -> None:
    """Renders glyph into the provided display at position [x, y]."""
    framebuffer.blit(self._framebuf, x, y, -1)

  def max_bounds(self) -> tuple[int, int]:
    """Returns the max bounds for Glyph."""
    return self._glyph.width(), self._glyph.height()


FAST_TRAIN_ICON = Glyph(assets.fast_train_icon)
