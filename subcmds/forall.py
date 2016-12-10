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
import errno
#import fcntl
import multiprocessing
import re
import os
import select
import signal
import sys
import subprocess
import portable

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
%prog -r str1 [str2] ... -c <command> [<arg>...]"
"""
  helpDescription = """
Executes the same shell command in each project.

The -r option allows running the command only on projects matching
regex or wildcard expression.

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

REPO_COUNT is the total number of projects being iterated.

REPO_I is the current (1-based) iteration count. Can be used in
conjunction with REPO_COUNT to add a simple progress indicator to your
command.

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
    p.add_option('-r', '--regex',
                 dest='regex', action='store_true',
                 help="Execute the command only on projects matching regex or wildcard expression")
    p.add_option('-i', '--inverse-regex',
                 dest='inverse_regex', action='store_true',
                 help="Execute the command only on projects not matching regex or wildcard expression")
    p.add_option('-g', '--groups',
                 dest='groups',
                 help="Execute the command only on projects matching the specified groups")
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
    g.add_option('-j', '--jobs',
                 dest='jobs', action='store', type='int', default=1,
                 help='number of commands to execute simultaneously')

  def WantPager(self, opt):
    return opt.project_header and opt.jobs == 1

  def _SerializeProject(self, project):
    """ Serialize a project._GitGetByExec instance.

    project._GitGetByExec is not pickle-able. Instead of trying to pass it
    around between processes, make a dict ourselves containing only the
    attributes that we need.

    """
    if not self.manifest.IsMirror:
      lrev = project.GetRevisionId()
    else:
      lrev = None
    return {
      'name': project.name,
      'relpath': project.relpath,
      'remote_name': project.remote.name,
      'lrev': lrev,
      'rrev': project.revisionExpr,
      'annotations': dict((a.name, a.value) for a in project.annotations),
      'gitdir': project.gitdir,
      'worktree': project.worktree,
    }

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
    rc = 0

    smart_sync_manifest_name = "smart_sync_override.xml"
    smart_sync_manifest_path = os.path.join(
      self.manifest.manifestProject.worktree, smart_sync_manifest_name)

    if os.path.isfile(smart_sync_manifest_path):
      self.manifest.Override(smart_sync_manifest_path)

    if opt.regex:
      projects = self.FindProjects(args)
    elif opt.inverse_regex:
      projects = self.FindProjects(args, inverse=True)
    else:
      projects = self.GetProjects(args, groups=opt.groups)

    os.environ['REPO_COUNT'] = str(len(projects))

    pool = multiprocessing.Pool(opt.jobs, InitWorker)
    try:
      config = self.manifest.manifestProject.config
      results_it = pool.imap(
         DoWorkWrapper,
         self.ProjectArgs(projects, mirror, opt, cmd, shell, config))
      pool.close()
      for r in results_it:
        rc = rc or r
        if r != 0 and opt.abort_on_errors:
          raise Exception('Aborting due to previous error')
    except (KeyboardInterrupt, WorkerKeyboardInterrupt):
      # Catch KeyboardInterrupt raised inside and outside of workers
      print('Interrupted - terminating the pool')
      pool.terminate()
      rc = rc or errno.EINTR
    except Exception as e:
      # Catch any other exceptions raised
      print('Got an error, terminating the pool: %s: %s' %
              (type(e).__name__, e),
            file=sys.stderr)
      pool.terminate()
      rc = rc or getattr(e, 'errno', 1)
    finally:
      pool.join()
    if rc != 0:
      sys.exit(rc)

  def ProjectArgs(self, projects, mirror, opt, cmd, shell, config):
    for cnt, p in enumerate(projects):
      try:
        project = self._SerializeProject(p)
      except Exception as e:
        print('Project list error on project %s: %s: %s' %
                (p.name, type(e).__name__, e),
              file=sys.stderr)
        return
      except KeyboardInterrupt:
        print('Project list interrupted',
              file=sys.stderr)
        return
      yield [mirror, opt, cmd, shell, cnt, config, project]

class WorkerKeyboardInterrupt(Exception):
  """ Keyboard interrupt exception for worker processes. """
  pass


def InitWorker():
  signal.signal(signal.SIGINT, signal.SIG_IGN)

def DoWorkWrapper(args):
  """ A wrapper around the DoWork() method.

  Catch the KeyboardInterrupt exceptions here and re-raise them as a different,
  ``Exception``-based exception to stop it flooding the console with stacktraces
  and making the parent hang indefinitely.

  """
  project = args.pop()
  try:
    return DoWork(project, *args)
  except KeyboardInterrupt:
    print('%s: Worker interrupted' % project['name'])
    raise WorkerKeyboardInterrupt()


def DoWork(project, mirror, opt, cmd, shell, cnt, config):
  env = os.environ.copy()
  def setenv(name, val):
    if val is None:
      val = ''
    if hasattr(val, 'encode'):
      val = val.encode()
    env[name] = val

  setenv('REPO_PROJECT', project['name'])
  setenv('REPO_PATH', project['relpath'])
  setenv('REPO_REMOTE', project['remote_name'])
  setenv('REPO_LREV', project['lrev'])
  setenv('REPO_RREV', project['rrev'])
  setenv('REPO_I', str(cnt + 1))
  for name in project['annotations']:
    setenv("REPO__%s" % (name), project['annotations'][name])

  if mirror:
    setenv('GIT_DIR', project['gitdir'])
    cwd = project['gitdir']
  else:
    cwd = project['worktree']

  if not os.path.exists(cwd):
    if (opt.project_header and opt.verbose) \
    or not opt.project_header:
      print('skipping %s/' % project['relpath'], file=sys.stderr)
    return

  if opt.project_header:
    stdin = subprocess.PIPE
    stdout = subprocess.PIPE
    stderr = subprocess.PIPE
  else:
    stdin = None
    stdout = None
    stderr = None

  p = subprocess.Popen(cmd,
                       cwd=cwd,
                       shell=shell,
                       env=env,
                       stdin=stdin,
                       stdout=stdout,
                       stderr=stderr)

  if opt.project_header:
    out = ForallColoring(config)
    out.redirect(sys.stdout)
    # class sfd(object):
    #   def __init__(self, fd, dest):
    #     self.fd = fd
    #     self.dest = dest
    #   def fileno(self):
    #     return self.fd.fileno()

    empty = True
    errbuf = ''

    p.stdin.close()
    # s_in = [sfd(p.stdout, sys.stdout),
    #         sfd(p.stderr, sys.stderr)]
    s_in = [portable.input_reader(p.stdout, sys.stdout, 'stdout'),
            portable.input_reader(p.stderr, sys.stderr, 'stderr')]

    # for s in s_in:
    #   flags = fcntl.fcntl(s.fd, fcntl.F_GETFL)
    #   fcntl.fcntl(s.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    while s_in:
      in_ready, _out_ready, _err_ready = select.select(s_in, [], [])
      for s in in_ready:
        # buf = s.fd.read(4096)
        buf = s.read(4096)
        if not buf:
          # s.fd.close()
          s.close()
          s_in.remove(s)
          continue

        if not opt.verbose:
          # if s.fd != p.stdout:
          if s.src != p.stdout:
            errbuf += buf
            continue

        if empty and out:
          if not cnt == 0:
            out.nl()

          if mirror:
            project_header_path = project['name']
          else:
            project_header_path = project['relpath']
          out.project('project %s/', project_header_path)
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
  return r
