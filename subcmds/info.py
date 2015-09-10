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

from command import PagedCommand
from color import Coloring
from error import NoSuchProjectError
from git_refs import R_M

class _Coloring(Coloring):
  def __init__(self, config):
    Coloring.__init__(self, config, "status")

class Info(PagedCommand):
  common = True
  helpSummary = "Get info on the manifest branch, current branch or unmerged branches"
  helpUsage = "%prog [-dl] [-o [-b]] [<project>...]"

  def _Options(self, p):
    p.add_option('-d', '--diff',
                 dest='all', action='store_true',
                 help="show full info and commit diff including remote branches")
    p.add_option('-o', '--overview',
                 dest='overview', action='store_true',
                 help='show overview of all local commits')
    p.add_option('-b', '--current-branch',
                 dest="current_branch", action="store_true",
                 help="consider only checked out branches")
    p.add_option('-l', '--local-only',
                 dest="local", action="store_true",
                 help="Disable all remote operations")


  def Execute(self, opt, args):
    self.out = _Coloring(self.manifest.globalConfig)
    self.heading = self.out.printer('heading', attr = 'bold')
    self.headtext = self.out.printer('headtext', fg = 'yellow')
    self.redtext = self.out.printer('redtext', fg = 'red')
    self.sha = self.out.printer("sha", fg = 'yellow')
    self.text = self.out.nofmt_printer('text')
    self.dimtext = self.out.printer('dimtext', attr = 'dim')

    self.opt = opt

    manifestConfig = self.manifest.manifestProject.config
    mergeBranch = manifestConfig.GetBranch("default").merge
    manifestGroups = (manifestConfig.GetString('manifest.groups')
                      or 'all,-notdefault')

    self.heading("Manifest branch: ")
    if self.manifest.default.revisionExpr:
        self.headtext(self.manifest.default.revisionExpr)
    self.out.nl()
    self.heading("Manifest merge branch: ")
    self.headtext(mergeBranch)
    self.out.nl()
    self.heading("Manifest groups: ")
    self.headtext(manifestGroups)
    self.out.nl()

    self.printSeparator()

    if not opt.overview:
      self.printDiffInfo(args)
    else:
      self.printCommitOverview(args)

  def printSeparator(self):
    self.text("----------------------------")
    self.out.nl()

  def printDiffInfo(self, args):
    try:
      projs = self.GetProjects(args)
    except NoSuchProjectError:
      return

    for p in projs:
      self.heading("Project: ")
      self.headtext(p.name)
      self.out.nl()

      self.heading("Mount path: ")
      self.headtext(p.worktree)
      self.out.nl()

      self.heading("Current revision: ")
      self.headtext(p.revisionExpr)
      self.out.nl()

      localBranches = p.GetBranches().keys()
      self.heading("Local Branches: ")
      self.redtext(str(len(localBranches)))
      if len(localBranches) > 0:
        self.text(" [")
        self.text(", ".join(localBranches))
        self.text("]")
      self.out.nl()

      if self.opt.all:
        self.findRemoteLocalDiff(p)

      self.printSeparator()

  def findRemoteLocalDiff(self, project):
    #Fetch all the latest commits
    if not self.opt.local:
      project.Sync_NetworkHalf(quiet=True, current_branch_only=True)

    logTarget = R_M + self.manifest.manifestProject.config.GetBranch("default").merge

    bareTmp = project.bare_git._bare
    project.bare_git._bare = False
    localCommits = project.bare_git.rev_list(
        '--abbrev=8',
        '--abbrev-commit',
        '--pretty=oneline',
        logTarget + "..",
        '--')

    originCommits = project.bare_git.rev_list(
        '--abbrev=8',
        '--abbrev-commit',
        '--pretty=oneline',
        ".." + logTarget,
        '--')
    project.bare_git._bare = bareTmp

    self.heading("Local Commits: ")
    self.redtext(str(len(localCommits)))
    self.dimtext(" (on current branch)")
    self.out.nl()

    for c in localCommits:
      split = c.split()
      self.sha(split[0] + " ")
      self.text(" ".join(split[1:]))
      self.out.nl()

    self.printSeparator()

    self.heading("Remote Commits: ")
    self.redtext(str(len(originCommits)))
    self.out.nl()

    for c in originCommits:
      split = c.split()
      self.sha(split[0] + " ")
      self.text(" ".join(split[1:]))
      self.out.nl()

  def printCommitOverview(self, args):
    all_branches = []
    for project in self.GetProjects(args):
      br = [project.GetUploadableBranch(x)
            for x in project.GetBranches()]
      br = [x for x in br if x]
      if self.opt.current_branch:
        br = [x for x in br if x.name == project.CurrentBranch]
      all_branches.extend(br)

    if not all_branches:
      return

    self.out.nl()
    self.heading('Projects Overview')
    project = None

    for branch in all_branches:
      if project != branch.project:
        project = branch.project
        self.out.nl()
        self.headtext(project.relpath)
        self.out.nl()

      commits = branch.commits
      date = branch.date
      self.text('%s %-33s (%2d commit%s, %s)' % (
        branch.name == project.CurrentBranch and '*' or ' ',
        branch.name,
        len(commits),
        len(commits) != 1 and 's' or '',
        date))
      self.out.nl()

      for commit in commits:
        split = commit.split()
        self.text('{0:38}{1} '.format('','-'))
        self.sha(split[0] + " ")
        self.text(" ".join(split[1:]))
        self.out.nl()
