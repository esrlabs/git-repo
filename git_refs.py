#
# Copyright (C) 2009 The Android Open Source Project
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
from trace import Trace

HEAD    = 'HEAD'
R_HEADS = 'refs/heads/'
R_TAGS  = 'refs/tags/'
R_PUB   = 'refs/published/'
R_M     = 'refs/remotes/m/'


class GitRefs(object):
  def __init__(self, gitdir):
    self._gitdir = gitdir
    self._phyref = None
    self._symref = None
    self._mtime = {}

  @property
  def all(self):
    self._EnsureLoaded()
    return self._phyref

  def get(self, name):
    try:
      return self.all[name]
    except KeyError:
      return ''

  def deleted(self, name):
    if self._phyref is not None:
      if name in self._phyref:
        del self._phyref[name]

      if name in self._symref:
        del self._symref[name]

      if name in self._mtime:
        del self._mtime[name]

  def symref(self, name):
    try:
      self._EnsureLoaded()
      return self._symref[name]
    except KeyError:
      return ''

  def _EnsureLoaded(self):
    if self._phyref is None or self._NeedUpdate():
      self._LoadAll()

  def _NeedUpdate(self):
    Trace(': scan refs %s', self._gitdir)

    for name, mtime in self._mtime.items():
      try:
        if mtime != os.path.getmtime(os.path.join(self._gitdir, name)):
          return True
      except OSError:
        return True
    return False

  def _LoadAll(self):
    Trace(': load refs %s', self._gitdir)

    self._phyref = {}
    self._symref = {}
    self._mtime = {}

    self._ReadPackedRefs()
    self._ReadLoose('refs/')
    self._ReadLoose1(os.path.join(self._gitdir, HEAD), HEAD)

    scan = self._symref
    attempts = 0
    while scan and attempts < 5:
      scan_next = {}
      for name, dest in scan.items():
        if dest in self._phyref:
          self._phyref[name] = self._phyref[dest]
        else:
          scan_next[name] = dest
      scan = scan_next
      attempts += 1

  def _ReadPackedRefs(self):
    path = os.path.join(self._gitdir, 'packed-refs')
    try:
      fd = open(path, 'r')
      mtime = os.path.getmtime(path)
    except IOError:
      return
    except OSError:
      return
    try:
      for line in fd:
        line = str(line)
        if line[0] == '#':
          continue
        if line[0] == '^':
          continue

        line = line[:-1]
        p = line.split(' ')
        ref_id = p[0]
        name = p[1]

        self._phyref[name] = ref_id
    finally:
      fd.close()
    self._mtime['packed-refs'] = mtime

  def _ReadLoose(self, prefix):
    base = os.path.join(self._gitdir, prefix)
    for name in os.listdir(base):
      p = os.path.join(base, name)
      if os.path.isdir(p):
        self._mtime[prefix] = os.path.getmtime(base)
        self._ReadLoose(prefix + name + '/')
      elif name.endswith('.lock'):
        pass
      else:
        self._ReadLoose1(p, prefix + name)

  def _ReadLoose1(self, path, name):
    try:
      fd = open(path, 'rb')
    except IOError:
      return

    try:
      try:
        mtime = os.path.getmtime(path)
        ref_id = fd.readline()
      except (IOError, OSError):
        return
    finally:
      fd.close()

    try:
      ref_id = ref_id.decode()
    except AttributeError:
      pass
    if not ref_id:
      return
    ref_id = ref_id[:-1]

    if ref_id.startswith('ref: '):
      self._symref[name] = ref_id[5:]
    else:
      self._phyref[name] = ref_id
    self._mtime[name] = mtime
