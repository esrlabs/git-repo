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
import fcntl
import re
import os
import select
import sys
import subprocess

from color import Coloring
from command import Command, MirrorSafeCommand

_CAN_COLOR = [
  'branch',
  'diff',
  'grep',
  'log',
]

class ForallColoring(Coloring):
  def __init__(self, config):
    Coloring.__init__(self, config, 'forall')
    self.project = self.printer('project', attr='bold')


class Forall(Command, MirrorSafeCommand):
  common = False
  helpSummary = "Run a shell command in each project"
  helpUsage = """
%prog [<project>...] -c <command> [<arg>...]
"""
  helpDescription = """
Executes the same shell command in each project.

Output Formatting
-----------------

The -p option causes '%prog' to bind pipes to the command's stdin,
stdout and stderr streams, and pipe all output into a continuous
stream that is displayed in a single pager session.  Project headings
are inserted before the output of each command is displayed.  If the
command produces no output in a project, no heading is displayed.

The formatting convention used by -p is very suitable for some
types of searching, e.g. `repo forall -p -c git log -SFoo` will
print all commits that add or remove references to Foo.

The -v option causes '%prog' to display stderr messages if a
command produces output only on stderr.  Normally the -p option
causes command output to be suppressed until the command produces
at least one byte of output on stdout.

Environment
-----------

pwd is the project's working directory.  If the current client is
a mirror client, then pwd is the Git repository.

REPO_PROJECT is set to the unique name of the project.

REPO_PATH is the path relative the the root of the client.

REPO_REMOTE is the name of the remote system from the manifest.

REPO_LREV is the name of the revision from the manifest, translated
to a local tracking branch.  If you need to pass the manifest
revision to a locally executed git command, use REPO_LREV.

REPO_RREV is the name of the revision from the manifest, exactly
as written in the manifest.

REPO__* are any extra environment variables, specified by the
"annotation" element under any project element.  This can be useful
for differentiating trees based on user-specific criteria, or simply
annotating tree details.

shell positional arguments ($1, $2, .., $#) are set to any arguments
following <command>.

Unless -p is used, stdin, stdout, stderr are inherited from the
terminal and are not redirected.

If -e is used, when a command exits unsuccessfully, '%prog' will abort
without iterating through the remaining projects.
"""

  def _Options(self, p):
    def cmd(option, opt_str, value, parser):
      setattr(parser.values, option.dest, list(parser.rargs))
      while parser.rargs:
        del parser.rargs[0]
    p.add_option('-c', '--command',
                 help='Command (and arguments) to execute',
                 dest='command',
                 action='callback',
                 callback=cmd)
    p.add_option('-e', '--abort-on-errors',
                 dest='abort_on_errors', action='store_true',
                 help='Abort if a command exits unsuccessfully')

    g = p.add_option_group('Output')
    g.add_option('-p',
                 dest='project_header', action='store_true',
                 help='Show project headers before output')
    g.add_option('-v', '--verbose',
                 dest='verbose', action='store_true',
                 help='Show command error messages')

  def WantPager(self, opt):
    return opt.project_header

  def Execute(self, opt, args):
    if not opt.command:
      self.Usage()

    cmd = [opt.command[0]]

    shell = True
    if re.compile(r'^[a-z0-9A-Z_/\.-]+$').match(cmd[0]):
      shell = False

    if shell:
      cmd.append(cmd[0])
    cmd.extend(opt.command[1:])

    if  opt.project_header \
    and not shell \
    and cmd[0] == 'git':
      # If this is a direct git command that can enable colorized
      # output and the user prefers coloring, add --color into the
      # command line because we are going to wrap the command into
      # a pipe and git won't know coloring should activate.
      #
      for cn in cmd[1:]:
        if not cn.startswith('-'):
          break
      else:
        cn = None
      # pylint: disable=W0631
      if cn and cn in _CAN_COLOR:
        class ColorCmd(Coloring):
          def __init__(self, config, cmd):
            Coloring.__init__(self, config, cmd)
        if ColorCmd(self.manifest.manifestProject.config, cn).is_on:
          cmd.insert(cmd.index(cn) + 1, '--color')
      # pylint: enable=W0631

    mirror = self.manifest.IsMirror
    out = ForallColoring(self.manifest.manifestProject.config)
    out.redirect(sys.stdout)

    rc = 0
    first = True

    for project in self.GetProjects(args):
      env = os.environ.copy()
      def setenv(name, val):
        if val is None:
          val = ''
        env[name] = val.encode()

      setenv('REPO_PROJECT', project.name)
      setenv('REPO_PATH', project.relpath)
      setenv('REPO_REMOTE', project.remote.name)
      setenv('REPO_LREV', project.GetRevisionId())
      setenv('REPO_RREV', project.revisionExpr)
      for a in project.annotations:
        setenv("REPO__%s" % (a.name), a.value)

      if mirror:
        setenv('GIT_DIR', project.gitdir)
        cwd = project.gitdir
      else:
        cwd = project.worktree

      if not os.path.exists(cwd):
        if (opt.project_header and opt.verbose) \
        or not opt.project_header:
          print('skipping %s/' % project.relpath, file=sys.stderr)
        continue

      if opt.project_header:
        stdin = subprocess.PIPE
        stdout = subprocess.PIPE
        stderr = subprocess.PIPE
      else:
        stdin = None
        stdout = None
        stderr = None

      p = subprocess.Popen(cmd,
                           cwd = cwd,
                           shell = shell,
                           env = env,
                           stdin = stdin,
                           stdout = stdout,
                           stderr = stderr)

      if opt.project_header:
        class sfd(object):
          def __init__(self, fd, dest):
            self.fd = fd
            self.dest = dest
          def fileno(self):
            return self.fd.fileno()

        empty = True
        errbuf = ''

        p.stdin.close()
        s_in = [sfd(p.stdout, sys.stdout),
                sfd(p.stderr, sys.stderr)]

        for s in s_in:
          flags = fcntl.fcntl(s.fd, fcntl.F_GETFL)
          fcntl.fcntl(s.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        while s_in:
          in_ready, _out_ready, _err_ready = select.select(s_in, [], [])
          for s in in_ready:
            buf = s.fd.read(4096)
            if not buf:
              s.fd.close()
              s_in.remove(s)
              continue

            if not opt.verbose:
              if s.fd != p.stdout:
                errbuf += buf
                continue

            if empty:
              if first:
                first = False
              else:
                out.nl()
              out.project('project %s/', project.relpath)
              out.nl()
              out.flush()
              if errbuf:
                sys.stderr.write(errbuf)
                sys.stderr.flush()
                errbuf = ''
              empty = False

            s.dest.write(buf)
            s.dest.flush()

      r = p.wait()
      if r != 0:
        if r != rc:
          rc = r
        if opt.abort_on_errors:
          print("error: %s: Aborting due to previous error" % project.relpath,
                file=sys.stderr)
          sys.exit(r)
    if rc != 0:
      sys.exit(rc)
