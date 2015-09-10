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
import re
import sys

from command import Command
from error import GitError

CHANGE_RE = re.compile(r'^([1-9][0-9]*)(?:[/\.-]([1-9][0-9]*))?$')

class Download(Command):
  common = True
  helpSummary = "Download and checkout a change"
  helpUsage = """
%prog {project change[/patchset]}...
"""
  helpDescription = """
The '%prog' command downloads a change from the review system and
makes it available in your project's local working directory.
"""

  def _Options(self, p):
    p.add_option('-c', '--cherry-pick',
                 dest='cherrypick', action='store_true',
                 help="cherry-pick instead of checkout")
    p.add_option('-r', '--revert',
                 dest='revert', action='store_true',
                 help="revert instead of checkout")
    p.add_option('-f', '--ff-only',
                 dest='ffonly', action='store_true',
                 help="force fast-forward merge")

  def _ParseChangeIds(self, args):
    if not args:
      self.Usage()

    to_get = []
    project = None

    for a in args:
      m = CHANGE_RE.match(a)
      if m:
        if not project:
          self.Usage()
        chg_id = int(m.group(1))
        if m.group(2):
          ps_id = int(m.group(2))
        else:
          ps_id = 1
        to_get.append((project, chg_id, ps_id))
      else:
        project = self.GetProjects([a])[0]
    return to_get

  def Execute(self, opt, args):
    for project, change_id, ps_id in self._ParseChangeIds(args):
      dl = project.DownloadPatchSet(change_id, ps_id)
      if not dl:
        print('[%s] change %d/%d not found'
              % (project.name, change_id, ps_id),
              file=sys.stderr)
        sys.exit(1)

      if not opt.revert and not dl.commits:
        print('[%s] change %d/%d has already been merged'
              % (project.name, change_id, ps_id),
              file=sys.stderr)
        continue

      if len(dl.commits) > 1:
        print('[%s] %d/%d depends on %d unmerged changes:' \
              % (project.name, change_id, ps_id, len(dl.commits)),
              file=sys.stderr)
        for c in dl.commits:
          print('  %s' % (c), file=sys.stderr)
      if opt.cherrypick:
        try:
          project._CherryPick(dl.commit)
        except GitError:
          print('[%s] Could not complete the cherry-pick of %s' \
                % (project.name, dl.commit), file=sys.stderr)
          sys.exit(1)

      elif opt.revert:
        project._Revert(dl.commit)
      elif opt.ffonly:
        project._FastForward(dl.commit, ffonly=True)
      else:
        project._Checkout(dl.commit)
