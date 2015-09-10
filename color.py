#
# Copyright (C) 2008 The Android Open Source Project
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

import os
import sys

import pager

COLORS = {None: -1,
          'normal': -1,
          'black': 0,
          'red': 1,
          'green': 2,
          'yellow': 3,
          'blue': 4,
          'magenta': 5,
          'cyan': 6,
          'white': 7}

ATTRS = {None: -1,
         'bold': 1,
         'dim': 2,
         'ul': 4,
         'blink': 5,
         'reverse': 7}

RESET = "\033[m"


def is_color(s):
  return s in COLORS


def is_attr(s):
  return s in ATTRS


def _Color(fg=None, bg=None, attr=None):
  fg = COLORS[fg]
  bg = COLORS[bg]
  attr = ATTRS[attr]

  if attr >= 0 or fg >= 0 or bg >= 0:
    need_sep = False
    code = "\033["

    if attr >= 0:
      code += chr(ord('0') + attr)
      need_sep = True

    if fg >= 0:
      if need_sep:
        code += ';'
      need_sep = True

      if fg < 8:
        code += '3%c' % (ord('0') + fg)
      else:
        code += '38;5;%d' % fg

    if bg >= 0:
      if need_sep:
        code += ';'

      if bg < 8:
        code += '4%c' % (ord('0') + bg)
      else:
        code += '48;5;%d' % bg
    code += 'm'
  else:
    code = ''
  return code

DEFAULT = None


def SetDefaultColoring(state):
  """Set coloring behavior to |state|.

  This is useful for overriding config options via the command line.
  """
  if state is None:
    # Leave it alone -- return quick!
    return

  global DEFAULT
  state = state.lower()
  if state in ('auto',):
    DEFAULT = state
  elif state in ('always', 'yes', 'true', True):
    DEFAULT = 'always'
  elif state in ('never', 'no', 'false', False):
    DEFAULT = 'never'


class Coloring(object):
  def __init__(self, config, section_type):
    self._section = 'color.%s' % section_type
    self._config = config
    self._out = sys.stdout

    on = DEFAULT
    if on is None:
      on = self._config.GetString(self._section)
      if on is None:
        on = self._config.GetString('color.ui')

    if on == 'auto':
      if pager.active or os.isatty(1):
        self._on = True
      else:
        self._on = False
    elif on in ('true', 'always'):
      self._on = True
    else:
      self._on = False

  def redirect(self, out):
    self._out = out

  @property
  def is_on(self):
    return self._on

  def write(self, fmt, *args):
    self._out.write(fmt % args)

  def flush(self):
    self._out.flush()

  def nl(self):
    self._out.write('\n')

  def printer(self, opt=None, fg=None, bg=None, attr=None):
    s = self
    c = self.colorer(opt, fg, bg, attr)

    def f(fmt, *args):
      s._out.write(c(fmt, *args))
    return f

  def nofmt_printer(self, opt=None, fg=None, bg=None, attr=None):
    s = self
    c = self.nofmt_colorer(opt, fg, bg, attr)

    def f(fmt):
      s._out.write(c(fmt))
    return f

  def colorer(self, opt=None, fg=None, bg=None, attr=None):
    if self._on:
      c = self._parse(opt, fg, bg, attr)

      def f(fmt, *args):
        output = fmt % args
        return ''.join([c, output, RESET])
      return f
    else:

      def f(fmt, *args):
        return fmt % args
      return f

  def nofmt_colorer(self, opt=None, fg=None, bg=None, attr=None):
    if self._on:
      c = self._parse(opt, fg, bg, attr)

      def f(fmt):
        return ''.join([c, fmt, RESET])
      return f
    else:
      def f(fmt):
        return fmt
      return f

  def _parse(self, opt, fg, bg, attr):
    if not opt:
      return _Color(fg, bg, attr)

    v = self._config.GetString('%s.%s' % (self._section, opt))
    if v is None:
      return _Color(fg, bg, attr)

    v = v.strip().lower()
    if v == "reset":
      return RESET
    elif v == '':
      return _Color(fg, bg, attr)

    have_fg = False
    for a in v.split(' '):
      if is_color(a):
        if have_fg:
          bg = a
        else:
          fg = a
      elif is_attr(a):
        attr = a

    return _Color(fg, bg, attr)
