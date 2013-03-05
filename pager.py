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

from __future__ import print_function
import os
import select
import sys

active = False

def RunPager(globalConfig):
  global active

  if not os.isatty(0) or not os.isatty(1):
    return
  pager = _SelectPager(globalConfig)
  if pager == '' or pager == 'cat':
    return

  # This process turns into the pager; a child it forks will
  # do the real processing and output back to the pager. This
  # is necessary to keep the pager in control of the tty.
  #
  try:
    r, w = os.pipe()
    pid = os.fork()
    if not pid:
      os.dup2(w, 1)
      os.dup2(w, 2)
      os.close(r)
      os.close(w)
      active = True
      return

    os.dup2(r, 0)
    os.close(r)
    os.close(w)

    _BecomePager(pager)
  except Exception:
    print("fatal: cannot start pager '%s'" % pager, file=sys.stderr)
    sys.exit(255)

def _SelectPager(globalConfig):
  try:
    return os.environ['GIT_PAGER']
  except KeyError:
    pass

  pager = globalConfig.GetString('core.pager')
  if pager:
    return pager

  try:
    return os.environ['PAGER']
  except KeyError:
    pass

  return 'less'

def _BecomePager(pager):
  # Delaying execution of the pager until we have output
  # ready works around a long-standing bug in popularly
  # available versions of 'less', a better 'more'.
  #
  _a, _b, _c = select.select([0], [], [0])

  os.environ['LESS'] = 'FRSX'

  try:
    os.execvp(pager, [pager])
  except OSError:
    os.execv('/bin/sh', ['sh', '-c', pager])
