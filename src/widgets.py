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
"""Collection of UI widgets for rendering to a display."""

import display
import fonts
import glyphs
import trains


_WELCOME_TO = 'Welcome to'


def _time_to_str(hh_mm: int) -> str:
  """Helper to convert integer time [h]h[m]m to HH:mm string."""
  hh, mm = divmod(hh_mm, 100)
  return '{:0>2}:{:0>2}'.format(hh, mm)


class Widget:
  """Base class for all Widgets"""

  def __init__(self, screen: display.Display):
    self._screen = screen

  def render(self, x: int, y: int, w: int, h: int) -> bool:
    """Renders the widget to the display.

    Returns whether the display needs to flush the back buffer to the display.
    """
    ...


class ClockWidget(Widget):
  """Class that renders clock to a display."""

  def __init__(
      self,
      screen: display.Display,
      large_font: fonts.Font,
      small_font: fonts.Font,
      render_seconds: bool = True,
  ):
    super().__init__(screen)
    self._large_font = large_font
    self._small_font = small_font

    self._hh_mm_bounds = large_font.calculate_bounds('00:00')
    self._ss_bounds = small_font.calculate_bounds(':00')

    self._last_update = None
    self._render_seconds = render_seconds

  def bounds(self):
    if self._render_seconds:
      width = self._hh_mm_bounds[0] + self._ss_bounds[0]
      height = max(self._hh_mm_bounds[1], self._ss_bounds[1])
    else:
      width, height = self._hh_mm_bounds
    return width, height

  def render(self, now: tuple[int, ...], x: int, y: int, w: int, h: int):
    current_update = now[3:6] if self._render_seconds else now[3:5]
    if self._last_update is not None and self._last_update == current_update:
      return False

    self._screen.fill_rect(x, y, w, h, 0)
    hh_mm = '{:02d}:{:02d}'.format(now[3], now[4])

    w, h = self._large_font.calculate_bounds(hh_mm)
    x_offset = self._hh_mm_bounds[0] - w

    self._large_font.render_text(hh_mm, self._screen, x + x_offset, y)
    if self._render_seconds:
      ss = ':{:02d}'.format(now[5])
      self._small_font.render_text(
          ss,
          self._screen,
          x + self._hh_mm_bounds[0],
          y + self._ss_bounds[1] + 2,
      )  # TODO: Remove +2 bump to fix vertical alignment.

    self._last_update = current_update
    return True


class OutOfHoursWidget(Widget):

  def __init__(self, screen: display.Display, font: fonts.Font, station: str):
    super().__init__(screen)
    self._font = font
    self._station = station
    self._welcome_to_bounds = font.calculate_bounds(_WELCOME_TO)
    self._station_bounds = font.calculate_bounds(station)

  def bounds(self):
    width = max(self._welcome_to_bounds[0], self._station_bounds[0])
    height = self._welcome_to_bounds[1] + self._station_bounds[1]
    return width, height

  def render(self, x: int, y: int, w: int, h: int):
    x_offset = (w - self._welcome_to_bounds[0]) // 2
    self._font.render_text(_WELCOME_TO, self._screen, x + x_offset, y)
    y += self._welcome_to_bounds[1]

    x_offset = (w - self._station_bounds[0]) // 2
    self._font.render_text(self._station, self._screen, x + x_offset, y)
    return True


class MessageWidget(Widget):
  """Renders a message in the middle of screen."""

  def __init__(self, screen: display.Display, message: str, font: fonts.Font):
    super().__init__(screen)
    self._default_message = message
    self._font = font
    w, h = 0, 0
    for m in message.split('\n'):
      bounds = font.calculate_bounds(m)
      w = max(w, bounds[0])
      h += bounds[1]

    self._x = (screen.width - w) // 2
    self._y = (screen.height - h) // 2

  def render(self, message: str | None = None) -> bool:
    self._screen.fill(0)
    messages = (self._default_message if message is None else message).split(
        '\n'
    )
    for i, message in enumerate(messages):
      self._font.render_text(
          message,
          self._screen,
          self._x,
          self._y + (i * self._font.max_bounds()[1]),
      )
    return True


class DepartureWidget(Widget):
  """Class that renders a departure to provided display."""

  def __init__(
      self,
      screen: display.Display,
      font: fonts.Font,
      width: int,
      status_font: fonts.Font | None = None,
      fast_train_icon: glyphs.Glyph | None = None,
  ):
    super().__init__(screen)
    self._font = font
    self._width = width
    self._status_font = status_font if status_font else font
    self._fast_train_icon = fast_train_icon
    self._max_clock_width = self._font.calculate_bounds('00:00')[0]
    if self._fast_train_icon:
      # How far to offset fast train icon from right-hand side.
      self._fast_train_offset = self._fast_train_icon.max_bounds()[0] + max(
          self._status_font.calculate_bounds('Exp 00:00')[0],
          self._status_font.calculate_bounds('Cancelled')[0],
      )

    self._last_departure = None

  def bounds(self) -> tuple[int, int]:
    max_height = max(
        self._font.max_bounds()[1], self._status_font.max_bounds()[1]
    )
    if self._fast_train_icon:
      max_height = max(max_height, self._fast_train_icon.max_bounds()[1])
    return self._width, max_height

  def render(
      self, departure: trains.Departure | None, x: int, y: int, w: int, h: int
  ) -> bool:
    if self._last_departure == departure:
      return False

    self._last_departure = departure
    self._screen.fill_rect(x, y, w, self._font.max_bounds()[1], 0)

    if departure is None:
      return True

    departure_time = _time_to_str(departure.departure_time)
    self._font.render_text(departure_time, self._screen, x, y)

    x += self._max_clock_width + 2
    self._font.render_text(departure.destination, self._screen, x, y)

    if departure.cancelled:
      status = 'Cancelled'
      status_w, _ = self._status_font.calculate_bounds(status)
    elif departure.departure_time != departure.actual_departure_time:
      status = 'Exp {}'.format(_time_to_str(departure.actual_departure_time))
      status_w, _ = self._status_font.calculate_bounds(status)
    else:
      status = 'On time'
      status_w, _ = self._status_font.calculate_bounds(status)

    self._status_font.render_text(status, self._screen, w - status_w, y)

    if departure.fast_train and self._fast_train_icon:
      self._fast_train_icon.render_glyph(
          self._screen, w - self._fast_train_offset - 2, y
      )
    return True


class MainWidget(Widget):
  """Class for the main display rendering."""

  def __init__(
      self,
      screen: display.Display,
      departure_updater: trains.DepartureUpdater,
      bold_font: fonts.Font,
      tall_font: fonts.Font,
      default_font: fonts.Font,
      render_seconds: bool = True,
      fast_train_icon: glyphs.Glyph | None = None,
  ):
    super().__init__(screen)
    self._departure_updater = departure_updater
    self._departure_widgets = []

    self._clock_widget = ClockWidget(
        screen, tall_font, bold_font, render_seconds
    )
    self._out_of_hours_widget = OutOfHoursWidget(
        screen, bold_font, departure_updater.station()
    )
    self._departures_spacer = default_font.max_bounds()[1] + 2
    self._num_departures = -1

    num_departures = (
        screen.height - self._clock_widget.bounds()[1]
    ) // self._departures_spacer
    for i in range(num_departures):
      self._departure_widgets.append(
          DepartureWidget(
              screen,
              bold_font if i == 0 else default_font,
              screen.width,
              default_font,
              fast_train_icon,
          )
      )

  def render(self, now: tuple[int, ...]):
    """Render display. Currently assumes we're rendering entire display."""
    need_refresh = False
    departures = self._departure_updater.departures()
    if departures:
      y = 0
      for i, widget in enumerate(self._departure_widgets):
        departure = departures[i] if i < len(departures) else None
        need_refresh |= widget.render(departure, 0, y, *widget.bounds())
        y += self._departures_spacer
    else:
      out_of_hours_bounds = self._out_of_hours_widget.bounds()
      x = (self._screen.width - out_of_hours_bounds[0]) // 2
      self._out_of_hours_widget.render(x, 0, *out_of_hours_bounds)

    need_refresh |= self._num_departures != len(departures)
    self._num_departures = len(departures)

    clock_bounds = self._clock_widget.bounds()
    x = (self._screen.width - clock_bounds[0]) // 2
    y = self._screen.height - clock_bounds[1]

    need_refresh |= self._clock_widget.render(now, x, y, *clock_bounds)
    return need_refresh
