#
# Copyright (C) 2012 The Android Open Source Project
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
from color import Coloring
from command import PagedCommand


class Overview(PagedCommand):
  common = True
  helpSummary = "Display overview of unmerged project branches"
  helpUsage = """
%prog [--current-branch] [<project>...]
"""
  helpDescription = """
The '%prog' command is used to display an overview of the projects branches,
and list any local commits that have not yet been merged into the project.

The -b/--current-branch option can be used to restrict the output to only
branches currently checked out in each project.  By default, all branches
are displayed.
"""

  def _Options(self, p):
    p.add_option('-b', '--current-branch',
                 dest="current_branch", action="store_true",
                 help="Consider only checked out branches")

  def Execute(self, opt, args):
    all_branches = []
    for project in self.GetProjects(args):
      br = [project.GetUploadableBranch(x)
            for x in project.GetBranches()]
      br = [x for x in br if x]
      if opt.current_branch:
        br = [x for x in br if x.name == project.CurrentBranch]
      all_branches.extend(br)

    if not all_branches:
      return

    class Report(Coloring):
      def __init__(self, config):
        Coloring.__init__(self, config, 'status')
        self.project = self.printer('header', attr='bold')
        self.text = self.printer('text')

    out = Report(all_branches[0].project.config)
    out.text("Deprecated. See repo info -o.")
    out.nl()
    out.project('Projects Overview')
    out.nl()

    project = None

    for branch in all_branches:
      if project != branch.project:
        project = branch.project
        out.nl()
        out.project('project %s/' % project.relpath)
        out.nl()

      commits = branch.commits
      date = branch.date
      print('%s %-33s (%2d commit%s, %s)' % (
            branch.name == project.CurrentBranch and '*' or ' ',
            branch.name,
            len(commits),
            len(commits) != 1 and 's' or ' ',
            date))
      for commit in commits:
        print('%-35s   - %s' % ('', commit))
