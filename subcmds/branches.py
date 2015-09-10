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

from __future__ import print_function
import sys
from color import Coloring
from command import Command

class BranchColoring(Coloring):
  def __init__(self, config):
    Coloring.__init__(self, config, 'branch')
    self.current = self.printer('current', fg='green')
    self.local   = self.printer('local')
    self.notinproject = self.printer('notinproject', fg='red')

class BranchInfo(object):
  def __init__(self, name):
    self.name = name
    self.current = 0
    self.published = 0
    self.published_equal = 0
    self.projects = []

  def add(self, b):
    if b.current:
      self.current += 1
    if b.published:
      self.published += 1
    if b.revision == b.published:
      self.published_equal += 1
    self.projects.append(b)

  @property
  def IsCurrent(self):
    return self.current > 0

  @property
  def IsSplitCurrent(self):
    return self.current != 0 and self.current != len(self.projects)

  @property
  def IsPublished(self):
    return self.published > 0

  @property
  def IsPublishedEqual(self):
    return self.published_equal == len(self.projects)


class Branches(Command):
  common = True
  helpSummary = "View current topic branches"
  helpUsage = """
%prog [<project>...]

Summarizes the currently available topic branches.

Branch Display
--------------

The branch display output by this command is organized into four
columns of information; for example:

 *P nocolor                   | in repo
    repo2                     |

The first column contains a * if the branch is the currently
checked out branch in any of the specified projects, or a blank
if no project has the branch checked out.

The second column contains either blank, p or P, depending upon
the upload status of the branch.

 (blank): branch not yet published by repo upload
       P: all commits were published by repo upload
       p: only some commits were published by repo upload

The third column contains the branch name.

The fourth column (after the | separator) lists the projects that
the branch appears in, or does not appear in.  If no project list
is shown, then the branch appears in all projects.

"""

  def Execute(self, opt, args):
    projects = self.GetProjects(args)
    out = BranchColoring(self.manifest.manifestProject.config)
    all_branches = {}
    project_cnt = len(projects)

    for project in projects:
      for name, b in project.GetBranches().items():
        b.project = project
        if name not in all_branches:
          all_branches[name] = BranchInfo(name)
        all_branches[name].add(b)

    names = list(sorted(all_branches))

    if not names:
      print('   (no branches)', file=sys.stderr)
      return

    width = 25
    for name in names:
      if width < len(name):
        width = len(name)

    for name in names:
      i = all_branches[name]
      in_cnt = len(i.projects)

      if i.IsCurrent:
        current = '*'
        hdr = out.current
      else:
        current = ' '
        hdr = out.local

      if i.IsPublishedEqual:
        published = 'P'
      elif i.IsPublished:
        published = 'p'
      else:
        published = ' '

      hdr('%c%c %-*s' % (current, published, width, name))
      out.write(' |')

      if in_cnt < project_cnt:
        fmt = out.write
        paths = []
        non_cur_paths = []
        if i.IsSplitCurrent or (in_cnt < project_cnt - in_cnt):
          in_type = 'in'
          for b in i.projects:
            if not i.IsSplitCurrent or b.current:
              paths.append(b.project.relpath)
            else:
              non_cur_paths.append(b.project.relpath)
        else:
          fmt = out.notinproject
          in_type = 'not in'
          have = set()
          for b in i.projects:
            have.add(b.project)
          for p in projects:
            if not p in have:
              paths.append(p.relpath)

        s = ' %s %s' % (in_type, ', '.join(paths))
        if not i.IsSplitCurrent and (width + 7 + len(s) < 80):
          fmt = out.current if i.IsCurrent else fmt
          fmt(s)
        else:
          fmt(' %s:' % in_type)
          fmt = out.current if i.IsCurrent else out.write
          for p in paths:
            out.nl()
            fmt(width*' ' + '          %s' % p)
          fmt = out.write
          for p in non_cur_paths:
            out.nl()
            fmt(width*' ' + '          %s' % p)
      else:
        out.write(' in all projects')
      out.nl()
