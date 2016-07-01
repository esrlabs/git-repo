#
# Copyright (C) 2010 The Android Open Source Project
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

from command import Command
from git_command import GitCommand

class Rebase(Command):
  common = True
  helpSummary = "Rebase local branches on upstream branch"
  helpUsage = """
%prog {[<project>...] | -i <project>...}
"""
  helpDescription = """
'%prog' uses git rebase to move local changes in the current topic branch to
the HEAD of the upstream history, useful when you have made commits in a topic
branch but need to incorporate new upstream changes "underneath" them.
"""

  def _Options(self, p):
    p.add_option('-i', '--interactive',
                dest="interactive", action="store_true",
                help="interactive rebase (single project only)")

    p.add_option('-f', '--force-rebase',
                 dest='force_rebase', action='store_true',
                 help='Pass --force-rebase to git rebase')
    p.add_option('--no-ff',
                 dest='no_ff', action='store_true',
                 help='Pass --no-ff to git rebase')
    p.add_option('-q', '--quiet',
                 dest='quiet', action='store_true',
                 help='Pass --quiet to git rebase')
    p.add_option('--autosquash',
                 dest='autosquash', action='store_true',
                 help='Pass --autosquash to git rebase')
    p.add_option('--whitespace',
                 dest='whitespace', action='store', metavar='WS',
                 help='Pass --whitespace to git rebase')
    p.add_option('--auto-stash',
                 dest='auto_stash', action='store_true',
                 help='Stash local modifications before starting')
    p.add_option('-m', '--onto-manifest',
                 dest='onto_manifest', action='store_true',
                 help='Rebase onto the manifest version instead of upstream '
                      'HEAD.  This helps to make sure the local tree stays '
                      'consistent if you previously synced to a manifest.')

  def Execute(self, opt, args):
    all_projects = self.GetProjects(args)
    one_project = len(all_projects) == 1

    if opt.interactive and not one_project:
      print('error: interactive rebase not supported with multiple projects',
            file=sys.stderr)
      if len(args) == 1:
        print('note: project %s is mapped to more than one path' % (args[0],),
            file=sys.stderr)
      return -1

    for project in all_projects:
      cb = project.CurrentBranch
      if not cb:
        if one_project:
          print("error: project %s has a detached HEAD" % project.relpath,
                file=sys.stderr)
          return -1
        # ignore branches with detatched HEADs
        continue

      upbranch = project.GetBranch(cb)
      if not upbranch.LocalMerge:
        if one_project:
          print("error: project %s does not track any remote branches"
                % project.relpath, file=sys.stderr)
          return -1
        # ignore branches without remotes
        continue

      args = ["rebase"]

      if opt.whitespace:
        args.append('--whitespace=%s' % opt.whitespace)

      if opt.quiet:
        args.append('--quiet')

      if opt.force_rebase:
        args.append('--force-rebase')

      if opt.no_ff:
        args.append('--no-ff')

      if opt.autosquash:
        args.append('--autosquash')

      if opt.interactive:
        args.append("-i")

      if opt.onto_manifest:
        args.append('--onto')
        args.append(project.revisionExpr)

      args.append(upbranch.LocalMerge)

      print('# %s: rebasing %s -> %s'
            % (project.relpath, cb, upbranch.LocalMerge), file=sys.stderr)

      needs_stash = False
      if opt.auto_stash:
        stash_args = ["update-index", "--refresh", "-q"]

        if GitCommand(project, stash_args).Wait() != 0:
          needs_stash = True
          # Dirty index, requires stash...
          stash_args = ["stash"]

          if GitCommand(project, stash_args).Wait() != 0:
            return -1

      if GitCommand(project, args).Wait() != 0:
        return -1

      if needs_stash:
        stash_args.append('pop')
        stash_args.append('--quiet')
        if GitCommand(project, stash_args).Wait() != 0:
          return -1
