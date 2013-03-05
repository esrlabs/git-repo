#
# Copyright (C) 2011 The Android Open Source Project
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
import re

from command import Command, MirrorSafeCommand

class List(Command, MirrorSafeCommand):
  common = True
  helpSummary = "List projects and their associated directories"
  helpUsage = """
%prog [-f] [<project>...]
%prog [-f] -r str1 [str2]..."
"""
  helpDescription = """
List all projects; pass '.' to list the project for the cwd.

This is similar to running: repo forall -c 'echo "$REPO_PATH : $REPO_PROJECT"'.
"""

  def _Options(self, p, show_smart=True):
    p.add_option('-r', '--regex',
                 dest='regex', action='store_true',
                 help="Filter the project list based on regex or wildcard matching of strings")
    p.add_option('-f', '--fullpath',
                 dest='fullpath', action='store_true',
                 help="Display the full work tree path instead of the relative path")

  def Execute(self, opt, args):
    """List all projects and the associated directories.

    This may be possible to do with 'repo forall', but repo newbies have
    trouble figuring that out.  The idea here is that it should be more
    discoverable.

    Args:
      opt: The options.
      args: Positional args.  Can be a list of projects to list, or empty.
    """
    if not opt.regex:
      projects = self.GetProjects(args)
    else:
      projects = self.FindProjects(args)

    def _getpath(x):
      if opt.fullpath:
        return x.worktree
      return x.relpath

    lines = []
    for project in projects:
      lines.append("%s : %s" % (_getpath(project), project.name))

    lines.sort()
    print('\n'.join(lines))

  def FindProjects(self, args):
    result = []
    for project in self.GetProjects(''):
      for arg in args:
        pattern = re.compile(r'%s' % arg, re.IGNORECASE)
        if pattern.search(project.name) or pattern.search(project.relpath):
          result.append(project)
          break
    result.sort(key=lambda project: project.relpath)
    return result
