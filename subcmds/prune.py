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
from color import Coloring
from command import PagedCommand

class Prune(PagedCommand):
  common = True
  helpSummary = "Prune (delete) already merged topics"
  helpUsage = """
%prog [<project>...]
"""

  def Execute(self, opt, args):
    all_branches = []
    for project in self.GetProjects(args):
      all_branches.extend(project.PruneHeads())

    if not all_branches:
      return

    class Report(Coloring):
      def __init__(self, config):
        Coloring.__init__(self, config, 'status')
        self.project = self.printer('header', attr='bold')

    out = Report(all_branches[0].project.config)
    out.project('Pending Branches')
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
