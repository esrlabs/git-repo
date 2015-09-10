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
from command import Command
from git_command import git
from progress import Progress

class Abandon(Command):
  common = True
  helpSummary = "Permanently abandon a development branch"
  helpUsage = """
%prog <branchname> [<project>...]

This subcommand permanently abandons a development branch by
deleting it (and all its history) from your local repository.

It is equivalent to "git branch -D <branchname>".
"""

  def Execute(self, opt, args):
    if not args:
      self.Usage()

    nb = args[0]
    if not git.check_ref_format('heads/%s' % nb):
      print("error: '%s' is not a valid name" % nb, file=sys.stderr)
      sys.exit(1)

    nb = args[0]
    err = []
    success = []
    all_projects = self.GetProjects(args[1:])

    pm = Progress('Abandon %s' % nb, len(all_projects))
    for project in all_projects:
      pm.update()

      status = project.AbandonBranch(nb)
      if status is not None:
        if status:
          success.append(project)
        else:
          err.append(project)
    pm.end()

    if err:
      for p in err:
        print("error: %s/: cannot abandon %s" % (p.relpath, nb),
              file=sys.stderr)
      sys.exit(1)
    elif not success:
      print('error: no project has branch %s' % nb, file=sys.stderr)
      sys.exit(1)
    else:
      print('Abandoned in %d project(s):\n  %s'
            % (len(success), '\n  '.join(p.relpath for p in success)),
            file=sys.stderr)
