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
import sys

from color import Coloring
from command import InteractiveCommand
from git_command import GitCommand

class _ProjectList(Coloring):
  def __init__(self, gc):
    Coloring.__init__(self, gc, 'interactive')
    self.prompt = self.printer('prompt', fg='blue', attr='bold')
    self.header = self.printer('header', attr='bold')
    self.help = self.printer('help', fg='red', attr='bold')

class Stage(InteractiveCommand):
  common = True
  helpSummary = "Stage file(s) for commit"
  helpUsage = """
%prog -i [<project>...]
"""
  helpDescription = """
The '%prog' command stages files to prepare the next commit.
"""

  def _Options(self, p):
    p.add_option('-i', '--interactive',
                 dest='interactive', action='store_true',
                 help='use interactive staging')

  def Execute(self, opt, args):
    if opt.interactive:
      self._Interactive(opt, args)
    else:
      self.Usage()

  def _Interactive(self, opt, args):
    all_projects = [p for p in self.GetProjects(args) if p.IsDirty()]
    if not all_projects:
      print('no projects have uncommitted modifications', file=sys.stderr)
      return

    out = _ProjectList(self.manifest.manifestProject.config)
    while True:
      out.header('        %s', 'project')
      out.nl()

      for i in range(len(all_projects)):
        p = all_projects[i]
        out.write('%3d:    %s', i + 1, p.relpath + '/')
        out.nl()
      out.nl()

      out.write('%3d: (', 0)
      out.prompt('q')
      out.write('uit)')
      out.nl()

      out.prompt('project> ')
      try:
        a = sys.stdin.readline()
      except KeyboardInterrupt:
        out.nl()
        break
      if a == '':
        out.nl()
        break

      a = a.strip()
      if a.lower() in ('q', 'quit', 'exit'):
        break
      if not a:
        continue

      try:
        a_index = int(a)
      except ValueError:
        a_index = None

      if a_index is not None:
        if a_index == 0:
          break
        if 0 < a_index and a_index <= len(all_projects):
          _AddI(all_projects[a_index - 1])
          continue

      projects = [p for p in all_projects if a in [p.name, p.relpath]]
      if len(projects) == 1:
        _AddI(projects[0])
        continue
    print('Bye.')

def _AddI(project):
  p = GitCommand(project, ['add', '--interactive'], bare=False)
  p.Wait()
