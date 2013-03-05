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
import netrc
from optparse import SUPPRESS_HELP
import os
import pickle
import re
import shutil
import socket
import subprocess
import sys
import time
import urlparse
import xmlrpclib

try:
  import threading as _threading
except ImportError:
  import dummy_threading as _threading

try:
  import resource
  def _rlimit_nofile():
    return resource.getrlimit(resource.RLIMIT_NOFILE)
except ImportError:
  def _rlimit_nofile():
    return (256, 256)

try:
  import multiprocessing
except ImportError:
  multiprocessing = None

from git_command import GIT, git_require
from git_refs import R_HEADS, HEAD
from main import WrapperModule
from project import Project
from project import RemoteSpec
from command import Command, MirrorSafeCommand
from error import RepoChangedException, GitError, ManifestParseError
from project import SyncBuffer
from progress import Progress

_ONE_DAY_S = 24 * 60 * 60

class _FetchError(Exception):
  """Internal error thrown in _FetchHelper() when we don't want stack trace."""
  pass

class Sync(Command, MirrorSafeCommand):
  jobs = 1
  common = True
  helpSummary = "Update working tree to the latest revision"
  helpUsage = """
%prog [<project>...]
"""
  helpDescription = """
The '%prog' command synchronizes local project directories
with the remote repositories specified in the manifest.  If a local
project does not yet exist, it will clone a new local directory from
the remote repository and set up tracking branches as specified in
the manifest.  If the local project already exists, '%prog'
will update the remote branches and rebase any new local changes
on top of the new remote changes.

'%prog' will synchronize all projects listed at the command
line.  Projects can be specified either by name, or by a relative
or absolute path to the project's local directory. If no projects
are specified, '%prog' will synchronize all projects listed in
the manifest.

The -d/--detach option can be used to switch specified projects
back to the manifest revision.  This option is especially helpful
if the project is currently on a topic branch, but the manifest
revision is temporarily needed.

The -s/--smart-sync option can be used to sync to a known good
build as specified by the manifest-server element in the current
manifest. The -t/--smart-tag option is similar and allows you to
specify a custom tag/label.

The -u/--manifest-server-username and -p/--manifest-server-password
options can be used to specify a username and password to authenticate
with the manifest server when using the -s or -t option.

If -u and -p are not specified when using the -s or -t option, '%prog'
will attempt to read authentication credentials for the manifest server
from the user's .netrc file.

'%prog' will not use authentication credentials from -u/-p or .netrc
if the manifest server specified in the manifest file already includes
credentials.

The -f/--force-broken option can be used to proceed with syncing
other projects if a project sync fails.

The --no-clone-bundle option disables any attempt to use
$URL/clone.bundle to bootstrap a new Git repository from a
resumeable bundle file on a content delivery network. This
may be necessary if there are problems with the local Python
HTTP client or proxy configuration, but the Git binary works.

The --fetch-submodules option enables fetching Git submodules
of a project from server.

SSH Connections
---------------

If at least one project remote URL uses an SSH connection (ssh://,
git+ssh://, or user@host:path syntax) repo will automatically
enable the SSH ControlMaster option when connecting to that host.
This feature permits other projects in the same '%prog' session to
reuse the same SSH tunnel, saving connection setup overheads.

To disable this behavior on UNIX platforms, set the GIT_SSH
environment variable to 'ssh'.  For example:

  export GIT_SSH=ssh
  %prog

Compatibility
~~~~~~~~~~~~~

This feature is automatically disabled on Windows, due to the lack
of UNIX domain socket support.

This feature is not compatible with url.insteadof rewrites in the
user's ~/.gitconfig.  '%prog' is currently not able to perform the
rewrite early enough to establish the ControlMaster tunnel.

If the remote SSH daemon is Gerrit Code Review, version 2.0.10 or
later is required to fix a server side protocol bug.

"""

  def _Options(self, p, show_smart=True):
    try:
      self.jobs = self.manifest.default.sync_j
    except ManifestParseError:
      self.jobs = 1

    p.add_option('-f', '--force-broken',
                 dest='force_broken', action='store_true',
                 help="continue sync even if a project fails to sync")
    p.add_option('-l', '--local-only',
                 dest='local_only', action='store_true',
                 help="only update working tree, don't fetch")
    p.add_option('-n', '--network-only',
                 dest='network_only', action='store_true',
                 help="fetch only, don't update working tree")
    p.add_option('-d', '--detach',
                 dest='detach_head', action='store_true',
                 help='detach projects back to manifest revision')
    p.add_option('-c', '--current-branch',
                 dest='current_branch_only', action='store_true',
                 help='fetch only current branch from server')
    p.add_option('-q', '--quiet',
                 dest='quiet', action='store_true',
                 help='be more quiet')
    p.add_option('-j', '--jobs',
                 dest='jobs', action='store', type='int',
                 help="projects to fetch simultaneously (default %d)" % self.jobs)
    p.add_option('-m', '--manifest-name',
                 dest='manifest_name',
                 help='temporary manifest to use for this sync', metavar='NAME.xml')
    p.add_option('--no-clone-bundle',
                 dest='no_clone_bundle', action='store_true',
                 help='disable use of /clone.bundle on HTTP/HTTPS')
    p.add_option('-u', '--manifest-server-username', action='store',
                 dest='manifest_server_username',
                 help='username to authenticate with the manifest server')
    p.add_option('-p', '--manifest-server-password', action='store',
                 dest='manifest_server_password',
                 help='password to authenticate with the manifest server')
    p.add_option('--fetch-submodules',
                 dest='fetch_submodules', action='store_true',
                 help='fetch submodules from server')
    if show_smart:
      p.add_option('-s', '--smart-sync',
                   dest='smart_sync', action='store_true',
                   help='smart sync using manifest from a known good build')
      p.add_option('-t', '--smart-tag',
                   dest='smart_tag', action='store',
                   help='smart sync using manifest from a known tag')

    g = p.add_option_group('repo Version options')
    g.add_option('--no-repo-verify',
                 dest='no_repo_verify', action='store_true',
                 help='do not verify repo source code')
    g.add_option('--repo-upgraded',
                 dest='repo_upgraded', action='store_true',
                 help=SUPPRESS_HELP)

  def _FetchHelper(self, opt, project, lock, fetched, pm, sem, err_event):
    """Main function of the fetch threads when jobs are > 1.

    Args:
      opt: Program options returned from optparse.  See _Options().
      project: Project object for the project to fetch.
      lock: Lock for accessing objects that are shared amongst multiple
          _FetchHelper() threads.
      fetched: set object that we will add project.gitdir to when we're done
          (with our lock held).
      pm: Instance of a Project object.  We will call pm.update() (with our
          lock held).
      sem: We'll release() this semaphore when we exit so that another thread
          can be started up.
      err_event: We'll set this event in the case of an error (after printing
          out info about the error).
    """
    # We'll set to true once we've locked the lock.
    did_lock = False

    # Encapsulate everything in a try/except/finally so that:
    # - We always set err_event in the case of an exception.
    # - We always make sure we call sem.release().
    # - We always make sure we unlock the lock if we locked it.
    try:
      try:
        start = time.time()
        success = project.Sync_NetworkHalf(
          quiet=opt.quiet,
          current_branch_only=opt.current_branch_only,
          clone_bundle=not opt.no_clone_bundle)
        self._fetch_times.Set(project, time.time() - start)

        # Lock around all the rest of the code, since printing, updating a set
        # and Progress.update() are not thread safe.
        lock.acquire()
        did_lock = True

        if not success:
          print('error: Cannot fetch %s' % project.name, file=sys.stderr)
          if opt.force_broken:
            print('warn: --force-broken, continuing to sync',
                  file=sys.stderr)
          else:
            raise _FetchError()

        fetched.add(project.gitdir)
        pm.update()
      except _FetchError:
        err_event.set()
      except:
        err_event.set()
        raise
    finally:
      if did_lock:
        lock.release()
      sem.release()

  def _Fetch(self, projects, opt):
    fetched = set()
    pm = Progress('Fetching projects', len(projects))

    if self.jobs == 1:
      for project in projects:
        pm.update()
        if project.Sync_NetworkHalf(
            quiet=opt.quiet,
            current_branch_only=opt.current_branch_only,
            clone_bundle=not opt.no_clone_bundle):
          fetched.add(project.gitdir)
        else:
          print('error: Cannot fetch %s' % project.name, file=sys.stderr)
          if opt.force_broken:
            print('warn: --force-broken, continuing to sync', file=sys.stderr)
          else:
            sys.exit(1)
    else:
      threads = set()
      lock = _threading.Lock()
      sem = _threading.Semaphore(self.jobs)
      err_event = _threading.Event()
      for project in projects:
        # Check for any errors before starting any new threads.
        # ...we'll let existing threads finish, though.
        if err_event.isSet():
          break

        sem.acquire()
        t = _threading.Thread(target = self._FetchHelper,
                              args = (opt,
                                      project,
                                      lock,
                                      fetched,
                                      pm,
                                      sem,
                                      err_event))
        # Ensure that Ctrl-C will not freeze the repo process.
        t.daemon = True
        threads.add(t)
        t.start()

      for t in threads:
        t.join()

      # If we saw an error, exit with code 1 so that other scripts can check.
      if err_event.isSet():
        print('\nerror: Exited sync due to fetch errors', file=sys.stderr)
        sys.exit(1)

    pm.end()
    self._fetch_times.Save()

    self._GCProjects(projects)
    return fetched

  def _GCProjects(self, projects):
    has_dash_c = git_require((1, 7, 2))
    if multiprocessing and has_dash_c:
      cpu_count = multiprocessing.cpu_count()
    else:
      cpu_count = 1
    jobs = min(self.jobs, cpu_count)

    if jobs < 2:
      for project in projects:
        project.bare_git.gc('--auto')
      return

    config = {'pack.threads': cpu_count / jobs if cpu_count > jobs else 1}

    threads = set()
    sem = _threading.Semaphore(jobs)
    err_event = _threading.Event()

    def GC(project):
      try:
        try:
          project.bare_git.gc('--auto', config=config)
        except GitError:
          err_event.set()
        except:
          err_event.set()
          raise
      finally:
        sem.release()

    for project in projects:
      if err_event.isSet():
        break
      sem.acquire()
      t = _threading.Thread(target=GC, args=(project,))
      t.daemon = True
      threads.add(t)
      t.start()

    for t in threads:
      t.join()

    if err_event.isSet():
      print('\nerror: Exited sync due to gc errors', file=sys.stderr)
      sys.exit(1)

  def UpdateProjectList(self):
    new_project_paths = []
    for project in self.GetProjects(None, missing_ok=True):
      if project.relpath:
        new_project_paths.append(project.relpath)
    file_name = 'project.list'
    file_path = os.path.join(self.manifest.repodir, file_name)
    old_project_paths = []

    if os.path.exists(file_path):
      fd = open(file_path, 'r')
      try:
        old_project_paths = fd.read().split('\n')
      finally:
        fd.close()
      for path in old_project_paths:
        if not path:
          continue
        if path not in new_project_paths:
          # If the path has already been deleted, we don't need to do it
          if os.path.exists(self.manifest.topdir + '/' + path):
            project = Project(
                           manifest = self.manifest,
                           name = path,
                           remote = RemoteSpec('origin'),
                           gitdir = os.path.join(self.manifest.topdir,
                                                 path, '.git'),
                           worktree = os.path.join(self.manifest.topdir, path),
                           relpath = path,
                           revisionExpr = 'HEAD',
                           revisionId = None,
                           groups = None)

            if project.IsDirty():
              print('error: Cannot remove project "%s": uncommitted changes'
                    'are present' % project.relpath, file=sys.stderr)
              print('       commit changes, then run sync again',
                    file=sys.stderr)
              return -1
            else:
              print('Deleting obsolete path %s' % project.worktree,
                    file=sys.stderr)
              shutil.rmtree(project.worktree)
              # Try deleting parent subdirs if they are empty
              project_dir = os.path.dirname(project.worktree)
              while project_dir != self.manifest.topdir:
                try:
                  os.rmdir(project_dir)
                except OSError:
                  break
                project_dir = os.path.dirname(project_dir)

    new_project_paths.sort()
    fd = open(file_path, 'w')
    try:
      fd.write('\n'.join(new_project_paths))
      fd.write('\n')
    finally:
      fd.close()
    return 0

  def Execute(self, opt, args):
    if opt.jobs:
      self.jobs = opt.jobs
    if self.jobs > 1:
      soft_limit, _ = _rlimit_nofile()
      self.jobs = min(self.jobs, (soft_limit - 5) / 3)

    if opt.network_only and opt.detach_head:
      print('error: cannot combine -n and -d', file=sys.stderr)
      sys.exit(1)
    if opt.network_only and opt.local_only:
      print('error: cannot combine -n and -l', file=sys.stderr)
      sys.exit(1)
    if opt.manifest_name and opt.smart_sync:
      print('error: cannot combine -m and -s', file=sys.stderr)
      sys.exit(1)
    if opt.manifest_name and opt.smart_tag:
      print('error: cannot combine -m and -t', file=sys.stderr)
      sys.exit(1)
    if opt.manifest_server_username or opt.manifest_server_password:
      if not (opt.smart_sync or opt.smart_tag):
        print('error: -u and -p may only be combined with -s or -t',
              file=sys.stderr)
        sys.exit(1)
      if None in [opt.manifest_server_username, opt.manifest_server_password]:
        print('error: both -u and -p must be given', file=sys.stderr)
        sys.exit(1)

    if opt.manifest_name:
      self.manifest.Override(opt.manifest_name)

    if opt.smart_sync or opt.smart_tag:
      if not self.manifest.manifest_server:
        print('error: cannot smart sync: no manifest server defined in'
              'manifest', file=sys.stderr)
        sys.exit(1)

      manifest_server = self.manifest.manifest_server

      if not '@' in manifest_server:
        username = None
        password = None
        if opt.manifest_server_username and opt.manifest_server_password:
          username = opt.manifest_server_username
          password = opt.manifest_server_password
        else:
          try:
            info = netrc.netrc()
          except IOError:
            print('.netrc file does not exist or could not be opened',
                  file=sys.stderr)
          else:
            try:
              parse_result = urlparse.urlparse(manifest_server)
              if parse_result.hostname:
                username, _account, password = \
                  info.authenticators(parse_result.hostname)
            except TypeError:
              # TypeError is raised when the given hostname is not present
              # in the .netrc file.
              print('No credentials found for %s in .netrc'
                    % parse_result.hostname, file=sys.stderr)
            except netrc.NetrcParseError as e:
              print('Error parsing .netrc file: %s' % e, file=sys.stderr)

        if (username and password):
          manifest_server = manifest_server.replace('://', '://%s:%s@' %
                                                    (username, password),
                                                    1)

      try:
        server = xmlrpclib.Server(manifest_server)
        if opt.smart_sync:
          p = self.manifest.manifestProject
          b = p.GetBranch(p.CurrentBranch)
          branch = b.merge
          if branch.startswith(R_HEADS):
            branch = branch[len(R_HEADS):]

          env = os.environ.copy()
          if (env.has_key('TARGET_PRODUCT') and
              env.has_key('TARGET_BUILD_VARIANT')):
            target = '%s-%s' % (env['TARGET_PRODUCT'],
                                env['TARGET_BUILD_VARIANT'])
            [success, manifest_str] = server.GetApprovedManifest(branch, target)
          else:
            [success, manifest_str] = server.GetApprovedManifest(branch)
        else:
          assert(opt.smart_tag)
          [success, manifest_str] = server.GetManifest(opt.smart_tag)

        if success:
          manifest_name = "smart_sync_override.xml"
          manifest_path = os.path.join(self.manifest.manifestProject.worktree,
                                       manifest_name)
          try:
            f = open(manifest_path, 'w')
            try:
              f.write(manifest_str)
            finally:
              f.close()
          except IOError:
            print('error: cannot write manifest to %s' % manifest_path,
                  file=sys.stderr)
            sys.exit(1)
          self.manifest.Override(manifest_name)
        else:
          print('error: %s' % manifest_str, file=sys.stderr)
          sys.exit(1)
      except (socket.error, IOError, xmlrpclib.Fault) as e:
        print('error: cannot connect to manifest server %s:\n%s'
              % (self.manifest.manifest_server, e), file=sys.stderr)
        sys.exit(1)
      except xmlrpclib.ProtocolError as e:
        print('error: cannot connect to manifest server %s:\n%d %s'
              % (self.manifest.manifest_server, e.errcode, e.errmsg),
              file=sys.stderr)
        sys.exit(1)

    rp = self.manifest.repoProject
    rp.PreSync()

    mp = self.manifest.manifestProject
    mp.PreSync()

    if opt.repo_upgraded:
      _PostRepoUpgrade(self.manifest, quiet=opt.quiet)

    if not opt.local_only:
      mp.Sync_NetworkHalf(quiet=opt.quiet,
                          current_branch_only=opt.current_branch_only)

    if mp.HasChanges:
      syncbuf = SyncBuffer(mp.config)
      mp.Sync_LocalHalf(syncbuf)
      if not syncbuf.Finish():
        sys.exit(1)
      self.manifest._Unload()
      if opt.jobs is None:
        self.jobs = self.manifest.default.sync_j
    all_projects = self.GetProjects(args,
                                    missing_ok=True,
                                    submodules_ok=opt.fetch_submodules)

    self._fetch_times = _FetchTimes(self.manifest)
    if not opt.local_only:
      to_fetch = []
      now = time.time()
      if _ONE_DAY_S <= (now - rp.LastFetch):
        to_fetch.append(rp)
      to_fetch.extend(all_projects)
      to_fetch.sort(key=self._fetch_times.Get, reverse=True)

      fetched = self._Fetch(to_fetch, opt)
      _PostRepoFetch(rp, opt.no_repo_verify)
      if opt.network_only:
        # bail out now; the rest touches the working tree
        return

      # Iteratively fetch missing and/or nested unregistered submodules
      previously_missing_set = set()
      while True:
        self.manifest._Unload()
        all_projects = self.GetProjects(args,
                                        missing_ok=True,
                                        submodules_ok=opt.fetch_submodules)
        missing = []
        for project in all_projects:
          if project.gitdir not in fetched:
            missing.append(project)
        if not missing:
          break
        # Stop us from non-stopped fetching actually-missing repos: If set of
        # missing repos has not been changed from last fetch, we break.
        missing_set = set(p.name for p in missing)
        if previously_missing_set == missing_set:
          break
        previously_missing_set = missing_set
        fetched.update(self._Fetch(missing, opt))

    if self.manifest.IsMirror:
      # bail out now, we have no working tree
      return

    if self.UpdateProjectList():
      sys.exit(1)

    syncbuf = SyncBuffer(mp.config,
                         detach_head = opt.detach_head)
    pm = Progress('Syncing work tree', len(all_projects))
    for project in all_projects:
      pm.update()
      if project.worktree:
        project.Sync_LocalHalf(syncbuf)
    pm.end()
    print(file=sys.stderr)
    if not syncbuf.Finish():
      sys.exit(1)

    # If there's a notice that's supposed to print at the end of the sync, print
    # it now...
    if self.manifest.notice:
      print(self.manifest.notice)

def _PostRepoUpgrade(manifest, quiet=False):
  wrapper = WrapperModule()
  if wrapper.NeedSetupGnuPG():
    wrapper.SetupGnuPG(quiet)
  for project in manifest.projects.values():
    if project.Exists:
      project.PostRepoUpgrade()

def _PostRepoFetch(rp, no_repo_verify=False, verbose=False):
  if rp.HasChanges:
    print('info: A new version of repo is available', file=sys.stderr)
    print(file=sys.stderr)
    if no_repo_verify or _VerifyTag(rp):
      syncbuf = SyncBuffer(rp.config)
      rp.Sync_LocalHalf(syncbuf)
      if not syncbuf.Finish():
        sys.exit(1)
      print('info: Restarting repo with latest version', file=sys.stderr)
      raise RepoChangedException(['--repo-upgraded'])
    else:
      print('warning: Skipped upgrade to unverified version', file=sys.stderr)
  else:
    if verbose:
      print('repo version %s is current' % rp.work_git.describe(HEAD),
            file=sys.stderr)

def _VerifyTag(project):
  gpg_dir = os.path.expanduser('~/.repoconfig/gnupg')
  if not os.path.exists(gpg_dir):
    print('warning: GnuPG was not available during last "repo init"\n'
          'warning: Cannot automatically authenticate repo."""',
          file=sys.stderr)
    return True

  try:
    cur = project.bare_git.describe(project.GetRevisionId())
  except GitError:
    cur = None

  if not cur \
     or re.compile(r'^.*-[0-9]{1,}-g[0-9a-f]{1,}$').match(cur):
    rev = project.revisionExpr
    if rev.startswith(R_HEADS):
      rev = rev[len(R_HEADS):]

    print(file=sys.stderr)
    print("warning: project '%s' branch '%s' is not signed"
          % (project.name, rev), file=sys.stderr)
    return False

  env = os.environ.copy()
  env['GIT_DIR'] = project.gitdir.encode()
  env['GNUPGHOME'] = gpg_dir.encode()

  cmd = [GIT, 'tag', '-v', cur]
  proc = subprocess.Popen(cmd,
                          stdout = subprocess.PIPE,
                          stderr = subprocess.PIPE,
                          env = env)
  out = proc.stdout.read()
  proc.stdout.close()

  err = proc.stderr.read()
  proc.stderr.close()

  if proc.wait() != 0:
    print(file=sys.stderr)
    print(out, file=sys.stderr)
    print(err, file=sys.stderr)
    print(file=sys.stderr)
    return False
  return True

class _FetchTimes(object):
  _ALPHA = 0.5

  def __init__(self, manifest):
    self._path = os.path.join(manifest.repodir, '.repopickle_fetchtimes')
    self._times = None
    self._seen = set()

  def Get(self, project):
    self._Load()
    return self._times.get(project.name, _ONE_DAY_S)

  def Set(self, project, t):
    self._Load()
    name = project.name
    old = self._times.get(name, t)
    self._seen.add(name)
    a = self._ALPHA
    self._times[name] = (a*t) + ((1-a) * old)

  def _Load(self):
    if self._times is None:
      try:
        f = open(self._path)
      except IOError:
        self._times = {}
        return self._times
      try:
        try:
          self._times = pickle.load(f)
        except IOError:
          try:
            os.remove(self._path)
          except OSError:
            pass
          self._times = {}
      finally:
        f.close()
    return self._times

  def Save(self):
    if self._times is None:
      return

    to_delete = []
    for name in self._times:
      if name not in self._seen:
        to_delete.append(name)
    for name in to_delete:
      del self._times[name]

    try:
      f = open(self._path, 'wb')
      try:
        pickle.dump(self._times, f)
      except (IOError, OSError, pickle.PickleError):
        try:
          os.remove(self._path)
        except OSError:
          pass
    finally:
      f.close()
