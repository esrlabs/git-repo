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
import sys

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

  def _Options(self, p):
    p.add_option('-r', '--regex',
                 dest='regex', action='store_true',
                 help="Filter the project list based on regex or wildcard matching of strings")
    p.add_option('-g', '--groups',
                 dest='groups',
                 help="Filter the project list based on the groups the project is in")
    p.add_option('-f', '--fullpath',
                 dest='fullpath', action='store_true',
                 help="Display the full work tree path instead of the relative path")
    p.add_option('-n', '--name-only',
                 dest='name_only', action='store_true',
                 help="Display only the name of the repository")
    p.add_option('-p', '--path-only',
                 dest='path_only', action='store_true',
                 help="Display only the path of the repository")

  def Execute(self, opt, args):
    """List all projects and the associated directories.

    This may be possible to do with 'repo forall', but repo newbies have
    trouble figuring that out.  The idea here is that it should be more
    discoverable.

    Args:
      opt: The options.
      args: Positional args.  Can be a list of projects to list, or empty.
    """

    if opt.fullpath and opt.name_only:
      print('error: cannot combine -f and -n', file=sys.stderr)
      sys.exit(1)

    if not opt.regex:
      projects = self.GetProjects(args, groups=opt.groups)
    else:
      projects = self.FindProjects(args)

    def _getpath(x):
      if opt.fullpath:
        return x.worktree
      return x.relpath

    lines = []
    for project in projects:
      if opt.name_only and not opt.path_only:
        lines.append("%s" % ( project.name))
      elif opt.path_only and not opt.name_only:
        lines.append("%s" % (_getpath(project)))
      else:
        lines.append("%s : %s" % (_getpath(project), project.name))

    lines.sort()
    print('\n'.join(lines))
