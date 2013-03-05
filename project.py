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
import traceback
import errno
import filecmp
import os
import random
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

from color import Coloring
from git_command import GitCommand, git_require
from git_config import GitConfig, IsId, GetSchemeFromUrl, ID_RE
from error import GitError, HookError, UploadError
from error import ManifestInvalidRevisionError
from error import NoManifestException
from trace import IsTrace, Trace

from git_refs import GitRefs, HEAD, R_HEADS, R_TAGS, R_PUB, R_M

def _lwrite(path, content):
  lock = '%s.lock' % path

  fd = open(lock, 'wb')
  try:
    fd.write(content)
  finally:
    fd.close()

  try:
    os.rename(lock, path)
  except OSError:
    os.remove(lock)
    raise

def _error(fmt, *args):
  msg = fmt % args
  print('error: %s' % msg, file=sys.stderr)

def not_rev(r):
  return '^' + r

def sq(r):
  return "'" + r.replace("'", "'\''") + "'"

_project_hook_list = None
def _ProjectHooks():
  """List the hooks present in the 'hooks' directory.

  These hooks are project hooks and are copied to the '.git/hooks' directory
  of all subprojects.

  This function caches the list of hooks (based on the contents of the
  'repo/hooks' directory) on the first call.

  Returns:
    A list of absolute paths to all of the files in the hooks directory.
  """
  global _project_hook_list
  if _project_hook_list is None:
    d = os.path.abspath(os.path.dirname(__file__))
    d = os.path.join(d , 'hooks')
    _project_hook_list = map(lambda x: os.path.join(d, x), os.listdir(d))
  return _project_hook_list


class DownloadedChange(object):
  _commit_cache = None

  def __init__(self, project, base, change_id, ps_id, commit):
    self.project = project
    self.base = base
    self.change_id = change_id
    self.ps_id = ps_id
    self.commit = commit

  @property
  def commits(self):
    if self._commit_cache is None:
      self._commit_cache = self.project.bare_git.rev_list(
        '--abbrev=8',
        '--abbrev-commit',
        '--pretty=oneline',
        '--reverse',
        '--date-order',
        not_rev(self.base),
        self.commit,
        '--')
    return self._commit_cache


class ReviewableBranch(object):
  _commit_cache = None

  def __init__(self, project, branch, base):
    self.project = project
    self.branch = branch
    self.base = base

  @property
  def name(self):
    return self.branch.name

  @property
  def commits(self):
    if self._commit_cache is None:
      self._commit_cache = self.project.bare_git.rev_list(
        '--abbrev=8',
        '--abbrev-commit',
        '--pretty=oneline',
        '--reverse',
        '--date-order',
        not_rev(self.base),
        R_HEADS + self.name,
        '--')
    return self._commit_cache

  @property
  def unabbrev_commits(self):
    r = dict()
    for commit in self.project.bare_git.rev_list(
        not_rev(self.base),
        R_HEADS + self.name,
        '--'):
      r[commit[0:8]] = commit
    return r

  @property
  def date(self):
    return self.project.bare_git.log(
      '--pretty=format:%cd',
      '-n', '1',
      R_HEADS + self.name,
      '--')

  def UploadForReview(self, people, auto_topic=False, draft=False):
    self.project.UploadForReview(self.name,
                                 people,
                                 auto_topic=auto_topic,
                                 draft=draft)

  def GetPublishedRefs(self):
    refs = {}
    output = self.project.bare_git.ls_remote(
      self.branch.remote.SshReviewUrl(self.project.UserEmail),
      'refs/changes/*')
    for line in output.split('\n'):
      try:
        (sha, ref) = line.split()
        refs[sha] = ref
      except ValueError:
        pass

    return refs

class StatusColoring(Coloring):
  def __init__(self, config):
    Coloring.__init__(self, config, 'status')
    self.project   = self.printer('header',    attr = 'bold')
    self.branch    = self.printer('header',    attr = 'bold')
    self.nobranch  = self.printer('nobranch',  fg = 'red')
    self.important = self.printer('important', fg = 'red')

    self.added     = self.printer('added',     fg = 'green')
    self.changed   = self.printer('changed',   fg = 'red')
    self.untracked = self.printer('untracked', fg = 'red')


class DiffColoring(Coloring):
  def __init__(self, config):
    Coloring.__init__(self, config, 'diff')
    self.project   = self.printer('header',    attr = 'bold')

class _Annotation:
  def __init__(self, name, value, keep):
    self.name = name
    self.value = value
    self.keep = keep

class _CopyFile:
  def __init__(self, src, dest, abssrc, absdest):
    self.src = src
    self.dest = dest
    self.abs_src = abssrc
    self.abs_dest = absdest

  def _Copy(self):
    src = self.abs_src
    dest = self.abs_dest
    # copy file if it does not exist or is out of date
    if not os.path.exists(dest) or not filecmp.cmp(src, dest):
      try:
        # remove existing file first, since it might be read-only
        if os.path.exists(dest):
          os.remove(dest)
        else:
          dest_dir = os.path.dirname(dest)
          if not os.path.isdir(dest_dir):
            os.makedirs(dest_dir)
        shutil.copy(src, dest)
        # make the file read-only
        mode = os.stat(dest)[stat.ST_MODE]
        mode = mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        os.chmod(dest, mode)
      except IOError:
        _error('Cannot copy file %s to %s', src, dest)

class RemoteSpec(object):
  def __init__(self,
               name,
               url = None,
               review = None):
    self.name = name
    self.url = url
    self.review = review

class RepoHook(object):
  """A RepoHook contains information about a script to run as a hook.

  Hooks are used to run a python script before running an upload (for instance,
  to run presubmit checks).  Eventually, we may have hooks for other actions.

  This shouldn't be confused with files in the 'repo/hooks' directory.  Those
  files are copied into each '.git/hooks' folder for each project.  Repo-level
  hooks are associated instead with repo actions.

  Hooks are always python.  When a hook is run, we will load the hook into the
  interpreter and execute its main() function.
  """
  def __init__(self,
               hook_type,
               hooks_project,
               topdir,
               abort_if_user_denies=False):
    """RepoHook constructor.

    Params:
      hook_type: A string representing the type of hook.  This is also used
          to figure out the name of the file containing the hook.  For
          example: 'pre-upload'.
      hooks_project: The project containing the repo hooks.  If you have a
          manifest, this is manifest.repo_hooks_project.  OK if this is None,
          which will make the hook a no-op.
      topdir: Repo's top directory (the one containing the .repo directory).
          Scripts will run with CWD as this directory.  If you have a manifest,
          this is manifest.topdir
      abort_if_user_denies: If True, we'll throw a HookError() if the user
          doesn't allow us to run the hook.
    """
    self._hook_type = hook_type
    self._hooks_project = hooks_project
    self._topdir = topdir
    self._abort_if_user_denies = abort_if_user_denies

    # Store the full path to the script for convenience.
    if self._hooks_project:
      self._script_fullpath = os.path.join(self._hooks_project.worktree,
                                           self._hook_type + '.py')
    else:
      self._script_fullpath = None

  def _GetHash(self):
    """Return a hash of the contents of the hooks directory.

    We'll just use git to do this.  This hash has the property that if anything
    changes in the directory we will return a different has.

    SECURITY CONSIDERATION:
      This hash only represents the contents of files in the hook directory, not
      any other files imported or called by hooks.  Changes to imported files
      can change the script behavior without affecting the hash.

    Returns:
      A string representing the hash.  This will always be ASCII so that it can
      be printed to the user easily.
    """
    assert self._hooks_project, "Must have hooks to calculate their hash."

    # We will use the work_git object rather than just calling GetRevisionId().
    # That gives us a hash of the latest checked in version of the files that
    # the user will actually be executing.  Specifically, GetRevisionId()
    # doesn't appear to change even if a user checks out a different version
    # of the hooks repo (via git checkout) nor if a user commits their own revs.
    #
    # NOTE: Local (non-committed) changes will not be factored into this hash.
    # I think this is OK, since we're really only worried about warning the user
    # about upstream changes.
    return self._hooks_project.work_git.rev_parse('HEAD')

  def _GetMustVerb(self):
    """Return 'must' if the hook is required; 'should' if not."""
    if self._abort_if_user_denies:
      return 'must'
    else:
      return 'should'

  def _CheckForHookApproval(self):
    """Check to see whether this hook has been approved.

    We'll look at the hash of all of the hooks.  If this matches the hash that
    the user last approved, we're done.  If it doesn't, we'll ask the user
    about approval.

    Note that we ask permission for each individual hook even though we use
    the hash of all hooks when detecting changes.  We'd like the user to be
    able to approve / deny each hook individually.  We only use the hash of all
    hooks because there is no other easy way to detect changes to local imports.

    Returns:
      True if this hook is approved to run; False otherwise.

    Raises:
      HookError: Raised if the user doesn't approve and abort_if_user_denies
          was passed to the consturctor.
    """
    hooks_config = self._hooks_project.config
    git_approval_key = 'repo.hooks.%s.approvedhash' % self._hook_type

    # Get the last hash that the user approved for this hook; may be None.
    old_hash = hooks_config.GetString(git_approval_key)

    # Get the current hash so we can tell if scripts changed since approval.
    new_hash = self._GetHash()

    if old_hash is not None:
      # User previously approved hook and asked not to be prompted again.
      if new_hash == old_hash:
        # Approval matched.  We're done.
        return True
      else:
        # Give the user a reason why we're prompting, since they last told
        # us to "never ask again".
        prompt = 'WARNING: Scripts have changed since %s was allowed.\n\n' % (
            self._hook_type)
    else:
      prompt = ''

    # Prompt the user if we're not on a tty; on a tty we'll assume "no".
    if sys.stdout.isatty():
      prompt += ('Repo %s run the script:\n'
                 '  %s\n'
                 '\n'
                 'Do you want to allow this script to run '
                 '(yes/yes-never-ask-again/NO)? ') % (
                 self._GetMustVerb(), self._script_fullpath)
      response = raw_input(prompt).lower()
      print()

      # User is doing a one-time approval.
      if response in ('y', 'yes'):
        return True
      elif response == 'yes-never-ask-again':
        hooks_config.SetString(git_approval_key, new_hash)
        return True

    # For anything else, we'll assume no approval.
    if self._abort_if_user_denies:
      raise HookError('You must allow the %s hook or use --no-verify.' %
                      self._hook_type)

    return False

  def _ExecuteHook(self, **kwargs):
    """Actually execute the given hook.

    This will run the hook's 'main' function in our python interpreter.

    Args:
      kwargs: Keyword arguments to pass to the hook.  These are often specific
          to the hook type.  For instance, pre-upload hooks will contain
          a project_list.
    """
    # Keep sys.path and CWD stashed away so that we can always restore them
    # upon function exit.
    orig_path = os.getcwd()
    orig_syspath = sys.path

    try:
      # Always run hooks with CWD as topdir.
      os.chdir(self._topdir)

      # Put the hook dir as the first item of sys.path so hooks can do
      # relative imports.  We want to replace the repo dir as [0] so
      # hooks can't import repo files.
      sys.path = [os.path.dirname(self._script_fullpath)] + sys.path[1:]

      # Exec, storing global context in the context dict.  We catch exceptions
      # and  convert to a HookError w/ just the failing traceback.
      context = {}
      try:
        execfile(self._script_fullpath, context)
      except Exception:
        raise HookError('%s\nFailed to import %s hook; see traceback above.' % (
                        traceback.format_exc(), self._hook_type))

      # Running the script should have defined a main() function.
      if 'main' not in context:
        raise HookError('Missing main() in: "%s"' % self._script_fullpath)


      # Add 'hook_should_take_kwargs' to the arguments to be passed to main.
      # We don't actually want hooks to define their main with this argument--
      # it's there to remind them that their hook should always take **kwargs.
      # For instance, a pre-upload hook should be defined like:
      #   def main(project_list, **kwargs):
      #
      # This allows us to later expand the API without breaking old hooks.
      kwargs = kwargs.copy()
      kwargs['hook_should_take_kwargs'] = True

      # Call the main function in the hook.  If the hook should cause the
      # build to fail, it will raise an Exception.  We'll catch that convert
      # to a HookError w/ just the failing traceback.
      try:
        context['main'](**kwargs)
      except Exception:
        raise HookError('%s\nFailed to run main() for %s hook; see traceback '
                        'above.' % (
                        traceback.format_exc(), self._hook_type))
    finally:
      # Restore sys.path and CWD.
      sys.path = orig_syspath
      os.chdir(orig_path)

  def Run(self, user_allows_all_hooks, **kwargs):
    """Run the hook.

    If the hook doesn't exist (because there is no hooks project or because
    this particular hook is not enabled), this is a no-op.

    Args:
      user_allows_all_hooks: If True, we will never prompt about running the
          hook--we'll just assume it's OK to run it.
      kwargs: Keyword arguments to pass to the hook.  These are often specific
          to the hook type.  For instance, pre-upload hooks will contain
          a project_list.

    Raises:
      HookError: If there was a problem finding the hook or the user declined
          to run a required hook (from _CheckForHookApproval).
    """
    # No-op if there is no hooks project or if hook is disabled.
    if ((not self._hooks_project) or
        (self._hook_type not in self._hooks_project.enabled_repo_hooks)):
      return

    # Bail with a nice error if we can't find the hook.
    if not os.path.isfile(self._script_fullpath):
      raise HookError('Couldn\'t find repo hook: "%s"' % self._script_fullpath)

    # Make sure the user is OK with running the hook.
    if (not user_allows_all_hooks) and (not self._CheckForHookApproval()):
      return

    # Run the hook with the same version of python we're using.
    self._ExecuteHook(**kwargs)


class Project(object):
  def __init__(self,
               manifest,
               name,
               remote,
               gitdir,
               worktree,
               relpath,
               revisionExpr,
               revisionId,
               rebase = True,
               groups = None,
               sync_c = False,
               sync_s = False,
               upstream = None,
               parent = None,
               is_derived = False):
    """Init a Project object.

    Args:
      manifest: The XmlManifest object.
      name: The `name` attribute of manifest.xml's project element.
      remote: RemoteSpec object specifying its remote's properties.
      gitdir: Absolute path of git directory.
      worktree: Absolute path of git working tree.
      relpath: Relative path of git working tree to repo's top directory.
      revisionExpr: The `revision` attribute of manifest.xml's project element.
      revisionId: git commit id for checking out.
      rebase: The `rebase` attribute of manifest.xml's project element.
      groups: The `groups` attribute of manifest.xml's project element.
      sync_c: The `sync-c` attribute of manifest.xml's project element.
      sync_s: The `sync-s` attribute of manifest.xml's project element.
      upstream: The `upstream` attribute of manifest.xml's project element.
      parent: The parent Project object.
      is_derived: False if the project was explicitly defined in the manifest;
                  True if the project is a discovered submodule.
    """
    self.manifest = manifest
    self.name = name
    self.remote = remote
    self.gitdir = gitdir.replace('\\', '/')
    if worktree:
      self.worktree = worktree.replace('\\', '/')
    else:
      self.worktree = None
    self.relpath = relpath
    self.revisionExpr = revisionExpr

    if   revisionId is None \
     and revisionExpr \
     and IsId(revisionExpr):
      self.revisionId = revisionExpr
    else:
      self.revisionId = revisionId

    self.rebase = rebase
    self.groups = groups
    self.sync_c = sync_c
    self.sync_s = sync_s
    self.upstream = upstream
    self.parent = parent
    self.is_derived = is_derived
    self.subprojects = []

    self.snapshots = {}
    self.copyfiles = []
    self.annotations = []
    self.config = GitConfig.ForRepository(
                    gitdir = self.gitdir,
                    defaults =  self.manifest.globalConfig)

    if self.worktree:
      self.work_git = self._GitGetByExec(self, bare=False)
    else:
      self.work_git = None
    self.bare_git = self._GitGetByExec(self, bare=True)
    self.bare_ref = GitRefs(gitdir)

    # This will be filled in if a project is later identified to be the
    # project containing repo hooks.
    self.enabled_repo_hooks = []

  @property
  def Derived(self):
    return self.is_derived

  @property
  def Exists(self):
    return os.path.isdir(self.gitdir)

  @property
  def CurrentBranch(self):
    """Obtain the name of the currently checked out branch.
       The branch name omits the 'refs/heads/' prefix.
       None is returned if the project is on a detached HEAD.
    """
    b = self.work_git.GetHead()
    if b.startswith(R_HEADS):
      return b[len(R_HEADS):]
    return None

  def IsRebaseInProgress(self):
    w = self.worktree
    g = os.path.join(w, '.git')
    return os.path.exists(os.path.join(g, 'rebase-apply')) \
        or os.path.exists(os.path.join(g, 'rebase-merge')) \
        or os.path.exists(os.path.join(w, '.dotest'))

  def IsDirty(self, consider_untracked=True):
    """Is the working directory modified in some way?
    """
    self.work_git.update_index('-q',
                               '--unmerged',
                               '--ignore-missing',
                               '--refresh')
    if self.work_git.DiffZ('diff-index', '-M', '--cached', HEAD):
      return True
    if self.work_git.DiffZ('diff-files'):
      return True
    if consider_untracked and self.work_git.LsOthers():
      return True
    return False

  _userident_name = None
  _userident_email = None

  @property
  def UserName(self):
    """Obtain the user's personal name.
    """
    if self._userident_name is None:
      self._LoadUserIdentity()
    return self._userident_name

  @property
  def UserEmail(self):
    """Obtain the user's email address.  This is very likely
       to be their Gerrit login.
    """
    if self._userident_email is None:
      self._LoadUserIdentity()
    return self._userident_email

  def _LoadUserIdentity(self):
    u = self.bare_git.var('GIT_COMMITTER_IDENT')
    m = re.compile("^(.*) <([^>]*)> ").match(u)
    if m:
      self._userident_name = m.group(1)
      self._userident_email = m.group(2)
    else:
      self._userident_name = ''
      self._userident_email = ''

  def GetRemote(self, name):
    """Get the configuration for a single remote.
    """
    return self.config.GetRemote(name)

  def GetBranch(self, name):
    """Get the configuration for a single branch.
    """
    return self.config.GetBranch(name)

  def GetBranches(self):
    """Get all existing local branches.
    """
    current = self.CurrentBranch
    all_refs = self._allrefs
    heads = {}

    for name, ref_id in all_refs.iteritems():
      if name.startswith(R_HEADS):
        name = name[len(R_HEADS):]
        b = self.GetBranch(name)
        b.current = name == current
        b.published = None
        b.revision = ref_id
        heads[name] = b

    for name, ref_id in all_refs.iteritems():
      if name.startswith(R_PUB):
        name = name[len(R_PUB):]
        b = heads.get(name)
        if b:
          b.published = ref_id

    return heads

  def MatchesGroups(self, manifest_groups):
    """Returns true if the manifest groups specified at init should cause
       this project to be synced.
       Prefixing a manifest group with "-" inverts the meaning of a group.
       All projects are implicitly labelled with "all".

       labels are resolved in order.  In the example case of
       project_groups: "all,group1,group2"
       manifest_groups: "-group1,group2"
       the project will be matched.
    """
    expanded_manifest_groups = manifest_groups or ['all', '-notdefault']
    expanded_project_groups = ['all'] + (self.groups or [])

    matched = False
    for group in expanded_manifest_groups:
      if group.startswith('-') and group[1:] in expanded_project_groups:
        matched = False
      elif group in expanded_project_groups:
        matched = True

    return matched

## Status Display ##

  def HasChanges(self):
    """Returns true if there are uncommitted changes.
    """
    self.work_git.update_index('-q',
                               '--unmerged',
                               '--ignore-missing',
                               '--refresh')
    if self.IsRebaseInProgress():
      return True

    if self.work_git.DiffZ('diff-index', '--cached', HEAD):
      return True

    if self.work_git.DiffZ('diff-files'):
      return True

    if self.work_git.LsOthers():
      return True

    return False

  def PrintWorkTreeStatus(self, output_redir=None):
    """Prints the status of the repository to stdout.

    Args:
      output: If specified, redirect the output to this object.
    """
    if not os.path.isdir(self.worktree):
      if output_redir == None:
        output_redir = sys.stdout
      print(file=output_redir)
      print('project %s/' % self.relpath, file=output_redir)
      print('  missing (run "repo sync")', file=output_redir)
      return

    self.work_git.update_index('-q',
                               '--unmerged',
                               '--ignore-missing',
                               '--refresh')
    rb = self.IsRebaseInProgress()
    di = self.work_git.DiffZ('diff-index', '-M', '--cached', HEAD)
    df = self.work_git.DiffZ('diff-files')
    do = self.work_git.LsOthers()
    if not rb and not di and not df and not do and not self.CurrentBranch:
      return 'CLEAN'

    out = StatusColoring(self.config)
    if not output_redir == None:
      out.redirect(output_redir)
    out.project('project %-40s', self.relpath + '/')

    branch = self.CurrentBranch
    if branch is None:
      out.nobranch('(*** NO BRANCH ***)')
    else:
      out.branch('branch %s', branch)
    out.nl()

    if rb:
      out.important('prior sync failed; rebase still in progress')
      out.nl()

    paths = list()
    paths.extend(di.keys())
    paths.extend(df.keys())
    paths.extend(do)

    paths = list(set(paths))
    paths.sort()

    for p in paths:
      try:
        i = di[p]
      except KeyError:
        i = None

      try:
        f = df[p]
      except KeyError:
        f = None

      if i:
        i_status = i.status.upper()
      else:
        i_status = '-'

      if f:
        f_status = f.status.lower()
      else:
        f_status = '-'

      if i and i.src_path:
        line = ' %s%s\t%s => %s (%s%%)' % (i_status, f_status,
                                        i.src_path, p, i.level)
      else:
        line = ' %s%s\t%s' % (i_status, f_status, p)

      if i and not f:
        out.added('%s', line)
      elif (i and f) or (not i and f):
        out.changed('%s', line)
      elif not i and not f:
        out.untracked('%s', line)
      else:
        out.write('%s', line)
      out.nl()

    return 'DIRTY'

  def PrintWorkTreeDiff(self, absolute_paths=False):
    """Prints the status of the repository to stdout.
    """
    out = DiffColoring(self.config)
    cmd = ['diff']
    if out.is_on:
      cmd.append('--color')
    cmd.append(HEAD)
    if absolute_paths:
      cmd.append('--src-prefix=a/%s/' % self.relpath)
      cmd.append('--dst-prefix=b/%s/' % self.relpath)
    cmd.append('--')
    p = GitCommand(self,
                   cmd,
                   capture_stdout = True,
                   capture_stderr = True)
    has_diff = False
    for line in p.process.stdout:
      if not has_diff:
        out.nl()
        out.project('project %s/' % self.relpath)
        out.nl()
        has_diff = True
      print(line[:-1])
    p.Wait()


## Publish / Upload ##

  def WasPublished(self, branch, all_refs=None):
    """Was the branch published (uploaded) for code review?
       If so, returns the SHA-1 hash of the last published
       state for the branch.
    """
    key = R_PUB + branch
    if all_refs is None:
      try:
        return self.bare_git.rev_parse(key)
      except GitError:
        return None
    else:
      try:
        return all_refs[key]
      except KeyError:
        return None

  def CleanPublishedCache(self, all_refs=None):
    """Prunes any stale published refs.
    """
    if all_refs is None:
      all_refs = self._allrefs
    heads = set()
    canrm = {}
    for name, ref_id in all_refs.iteritems():
      if name.startswith(R_HEADS):
        heads.add(name)
      elif name.startswith(R_PUB):
        canrm[name] = ref_id

    for name, ref_id in canrm.iteritems():
      n = name[len(R_PUB):]
      if R_HEADS + n not in heads:
        self.bare_git.DeleteRef(name, ref_id)

  def GetUploadableBranches(self, selected_branch=None):
    """List any branches which can be uploaded for review.
    """
    heads = {}
    pubed = {}

    for name, ref_id in self._allrefs.iteritems():
      if name.startswith(R_HEADS):
        heads[name[len(R_HEADS):]] = ref_id
      elif name.startswith(R_PUB):
        pubed[name[len(R_PUB):]] = ref_id

    ready = []
    for branch, ref_id in heads.iteritems():
      if branch in pubed and pubed[branch] == ref_id:
        continue
      if selected_branch and branch != selected_branch:
        continue

      rb = self.GetUploadableBranch(branch)
      if rb:
        ready.append(rb)
    return ready

  def GetUploadableBranch(self, branch_name):
    """Get a single uploadable branch, or None.
    """
    branch = self.GetBranch(branch_name)
    base = branch.LocalMerge
    if branch.LocalMerge:
      rb = ReviewableBranch(self, branch, base)
      if rb.commits:
        return rb
    return None

  def UploadForReview(self, branch=None,
                      people=([],[]),
                      auto_topic=False,
                      draft=False):
    """Uploads the named branch for code review.
    """
    if branch is None:
      branch = self.CurrentBranch
    if branch is None:
      raise GitError('not currently on a branch')

    branch = self.GetBranch(branch)
    if not branch.LocalMerge:
      raise GitError('branch %s does not track a remote' % branch.name)
    if not branch.remote.review:
      raise GitError('remote %s has no review url' % branch.remote.name)

    dest_branch = branch.merge
    if not dest_branch.startswith(R_HEADS):
      dest_branch = R_HEADS + dest_branch

    if not branch.remote.projectname:
      branch.remote.projectname = self.name
      branch.remote.Save()

    url = branch.remote.ReviewUrl(self.UserEmail)
    if url is None:
      raise UploadError('review not configured')
    cmd = ['push']

    if url.startswith('ssh://'):
      rp = ['gerrit receive-pack']
      for e in people[0]:
        rp.append('--reviewer=%s' % sq(e))
      for e in people[1]:
        rp.append('--cc=%s' % sq(e))
      cmd.append('--receive-pack=%s' % " ".join(rp))

    cmd.append(url)

    if dest_branch.startswith(R_HEADS):
      dest_branch = dest_branch[len(R_HEADS):]

    upload_type = 'for'
    if draft:
      upload_type = 'drafts'

    ref_spec = '%s:refs/%s/%s' % (R_HEADS + branch.name, upload_type,
                                  dest_branch)
    if auto_topic:
      ref_spec = ref_spec + '/' + branch.name
    cmd.append(ref_spec)

    if GitCommand(self, cmd, bare = True).Wait() != 0:
      raise UploadError('Upload failed')

    msg = "posted to %s for %s" % (branch.remote.review, dest_branch)
    self.bare_git.UpdateRef(R_PUB + branch.name,
                            R_HEADS + branch.name,
                            message = msg)


## Sync ##

  def Sync_NetworkHalf(self,
      quiet=False,
      is_new=None,
      current_branch_only=False,
      clone_bundle=True):
    """Perform only the network IO portion of the sync process.
       Local working directory/branch state is not affected.
    """
    if is_new is None:
      is_new = not self.Exists
    if is_new:
      self._InitGitDir()
    self._InitRemote()

    if is_new:
      alt = os.path.join(self.gitdir, 'objects/info/alternates')
      try:
        fd = open(alt, 'rb')
        try:
          alt_dir = fd.readline().rstrip()
        finally:
          fd.close()
      except IOError:
        alt_dir = None
    else:
      alt_dir = None

    if clone_bundle \
    and alt_dir is None \
    and self._ApplyCloneBundle(initial=is_new, quiet=quiet):
      is_new = False

    if not current_branch_only:
      if self.sync_c:
        current_branch_only = True
      elif not self.manifest._loaded:
        # Manifest cannot check defaults until it syncs.
        current_branch_only = False
      elif self.manifest.default.sync_c:
        current_branch_only = True

    if not self._RemoteFetch(initial=is_new, quiet=quiet, alt_dir=alt_dir,
                             current_branch_only=current_branch_only):
      return False

    if self.worktree:
      self._InitMRef()
    else:
      self._InitMirrorHead()
      try:
        os.remove(os.path.join(self.gitdir, 'FETCH_HEAD'))
      except OSError:
        pass
    return True

  def PostRepoUpgrade(self):
    self._InitHooks()

  def _CopyFiles(self):
    for copyfile in self.copyfiles:
      copyfile._Copy()

  def GetRevisionId(self, all_refs=None):
    if self.revisionId:
      return self.revisionId

    rem = self.GetRemote(self.remote.name)
    rev = rem.ToLocal(self.revisionExpr)

    if all_refs is not None and rev in all_refs:
      return all_refs[rev]

    try:
      return self.bare_git.rev_parse('--verify', '%s^0' % rev)
    except GitError:
      raise ManifestInvalidRevisionError(
        'revision %s in %s not found' % (self.revisionExpr,
                                         self.name))

  def Sync_LocalHalf(self, syncbuf):
    """Perform only the local IO portion of the sync process.
       Network access is not required.
    """
    all_refs = self.bare_ref.all
    self.CleanPublishedCache(all_refs)
    revid = self.GetRevisionId(all_refs)

    def _doff():
      self._FastForward(revid)
      self._CopyFiles()

    self._InitWorkTree()
    head = self.work_git.GetHead()
    if head.startswith(R_HEADS):
      branch = head[len(R_HEADS):]
      try:
        head = all_refs[head]
      except KeyError:
        head = None
    else:
      branch = None

    if branch is None or syncbuf.detach_head:
      # Currently on a detached HEAD.  The user is assumed to
      # not have any local modifications worth worrying about.
      #
      if self.IsRebaseInProgress():
        syncbuf.fail(self, _PriorSyncFailedError())
        return

      if head == revid:
        # No changes; don't do anything further.
        # Except if the head needs to be detached
        #
        if not syncbuf.detach_head:
          return
      else:
        lost = self._revlist(not_rev(revid), HEAD)
        if lost:
          syncbuf.info(self, "discarding %d commits", len(lost))

      try:
        self._Checkout(revid, quiet=True)
      except GitError as e:
        syncbuf.fail(self, e)
        return
      self._CopyFiles()
      return

    if head == revid:
      # No changes; don't do anything further.
      #
      return

    branch = self.GetBranch(branch)

    if not branch.LocalMerge:
      # The current branch has no tracking configuration.
      # Jump off it to a detached HEAD.
      #
      syncbuf.info(self,
                   "leaving %s; does not track upstream",
                   branch.name)
      try:
        self._Checkout(revid, quiet=True)
      except GitError as e:
        syncbuf.fail(self, e)
        return
      self._CopyFiles()
      return

    upstream_gain = self._revlist(not_rev(HEAD), revid)
    pub = self.WasPublished(branch.name, all_refs)
    if pub:
      not_merged = self._revlist(not_rev(revid), pub)
      if not_merged:
        if upstream_gain:
          # The user has published this branch and some of those
          # commits are not yet merged upstream.  We do not want
          # to rewrite the published commits so we punt.
          #
          syncbuf.fail(self,
                       "branch %s is published (but not merged) and is now %d commits behind"
                       % (branch.name, len(upstream_gain)))
        return
      elif pub == head:
        # All published commits are merged, and thus we are a
        # strict subset.  We can fast-forward safely.
        #
        syncbuf.later1(self, _doff)
        return

    # Examine the local commits not in the remote.  Find the
    # last one attributed to this user, if any.
    #
    local_changes = self._revlist(not_rev(revid), HEAD, format='%H %ce')
    last_mine = None
    cnt_mine = 0
    for commit in local_changes:
      commit_id, committer_email = commit.split(' ', 1)
      if committer_email == self.UserEmail:
        last_mine = commit_id
        cnt_mine += 1

    if not upstream_gain and cnt_mine == len(local_changes):
      return

    if self.IsDirty(consider_untracked=False):
      syncbuf.fail(self, _DirtyError())
      return

    # If the upstream switched on us, warn the user.
    #
    if branch.merge != self.revisionExpr:
      if branch.merge and self.revisionExpr:
        syncbuf.info(self,
                     'manifest switched %s...%s',
                     branch.merge,
                     self.revisionExpr)
      elif branch.merge:
        syncbuf.info(self,
                     'manifest no longer tracks %s',
                     branch.merge)

    if cnt_mine < len(local_changes):
      # Upstream rebased.  Not everything in HEAD
      # was created by this user.
      #
      syncbuf.info(self,
                   "discarding %d commits removed from upstream",
                   len(local_changes) - cnt_mine)

    branch.remote = self.GetRemote(self.remote.name)
    if not ID_RE.match(self.revisionExpr):
      # in case of manifest sync the revisionExpr might be a SHA1
      branch.merge = self.revisionExpr
    branch.Save()

    if cnt_mine > 0 and self.rebase:
      def _dorebase():
        self._Rebase(upstream = '%s^1' % last_mine, onto = revid)
        self._CopyFiles()
      syncbuf.later2(self, _dorebase)
    elif local_changes:
      try:
        self._ResetHard(revid)
        self._CopyFiles()
      except GitError as e:
        syncbuf.fail(self, e)
        return
    else:
      syncbuf.later1(self, _doff)

  def AddCopyFile(self, src, dest, absdest):
    # dest should already be an absolute path, but src is project relative
    # make src an absolute path
    abssrc = os.path.join(self.worktree, src)
    self.copyfiles.append(_CopyFile(src, dest, abssrc, absdest))

  def AddAnnotation(self, name, value, keep):
    self.annotations.append(_Annotation(name, value, keep))

  def DownloadPatchSet(self, change_id, patch_id):
    """Download a single patch set of a single change to FETCH_HEAD.
    """
    remote = self.GetRemote(self.remote.name)

    cmd = ['fetch', remote.name]
    cmd.append('refs/changes/%2.2d/%d/%d' \
               % (change_id % 100, change_id, patch_id))
    cmd.extend(map(str, remote.fetch))
    if GitCommand(self, cmd, bare=True).Wait() != 0:
      return None
    return DownloadedChange(self,
                            self.GetRevisionId(),
                            change_id,
                            patch_id,
                            self.bare_git.rev_parse('FETCH_HEAD'))


## Branch Management ##

  def StartBranch(self, name):
    """Create a new branch off the manifest's revision.
    """
    head = self.work_git.GetHead()
    if head == (R_HEADS + name):
      return True

    all_refs = self.bare_ref.all
    if (R_HEADS + name) in all_refs:
      return GitCommand(self,
                        ['checkout', name, '--'],
                        capture_stdout = True,
                        capture_stderr = True).Wait() == 0

    branch = self.GetBranch(name)
    branch.remote = self.GetRemote(self.remote.name)
    branch.merge = self.revisionExpr
    revid = self.GetRevisionId(all_refs)

    if head.startswith(R_HEADS):
      try:
        head = all_refs[head]
      except KeyError:
        head = None

    if revid and head and revid == head:
      ref = os.path.join(self.gitdir, R_HEADS + name)
      try:
        os.makedirs(os.path.dirname(ref))
      except OSError:
        pass
      _lwrite(ref, '%s\n' % revid)
      _lwrite(os.path.join(self.worktree, '.git', HEAD),
              'ref: %s%s\n' % (R_HEADS, name))
      branch.Save()
      return True

    if GitCommand(self,
                  ['checkout', '-b', branch.name, revid],
                  capture_stdout = True,
                  capture_stderr = True).Wait() == 0:
      branch.Save()
      return True
    return False

  def CheckoutBranch(self, name):
    """Checkout a local topic branch.

        Args:
          name: The name of the branch to checkout.

        Returns:
          True if the checkout succeeded; False if it didn't; None if the branch
          didn't exist.
    """
    rev = R_HEADS + name
    head = self.work_git.GetHead()
    if head == rev:
      # Already on the branch
      #
      return True

    all_refs = self.bare_ref.all
    try:
      revid = all_refs[rev]
    except KeyError:
      # Branch does not exist in this project
      #
      return None

    if head.startswith(R_HEADS):
      try:
        head = all_refs[head]
      except KeyError:
        head = None

    if head == revid:
      # Same revision; just update HEAD to point to the new
      # target branch, but otherwise take no other action.
      #
      _lwrite(os.path.join(self.worktree, '.git', HEAD),
              'ref: %s%s\n' % (R_HEADS, name))
      return True

    return GitCommand(self,
                      ['checkout', name, '--'],
                      capture_stdout = True,
                      capture_stderr = True).Wait() == 0

  def AbandonBranch(self, name):
    """Destroy a local topic branch.

    Args:
      name: The name of the branch to abandon.

    Returns:
      True if the abandon succeeded; False if it didn't; None if the branch
      didn't exist.
    """
    rev = R_HEADS + name
    all_refs = self.bare_ref.all
    if rev not in all_refs:
      # Doesn't exist
      return None

    head = self.work_git.GetHead()
    if head == rev:
      # We can't destroy the branch while we are sitting
      # on it.  Switch to a detached HEAD.
      #
      head = all_refs[head]

      revid = self.GetRevisionId(all_refs)
      if head == revid:
        _lwrite(os.path.join(self.worktree, '.git', HEAD),
                '%s\n' % revid)
      else:
        self._Checkout(revid, quiet=True)

    return GitCommand(self,
                      ['branch', '-D', name],
                      capture_stdout = True,
                      capture_stderr = True).Wait() == 0

  def PruneHeads(self):
    """Prune any topic branches already merged into upstream.
    """
    cb = self.CurrentBranch
    kill = []
    left = self._allrefs
    for name in left.keys():
      if name.startswith(R_HEADS):
        name = name[len(R_HEADS):]
        if cb is None or name != cb:
          kill.append(name)

    rev = self.GetRevisionId(left)
    if cb is not None \
       and not self._revlist(HEAD + '...' + rev) \
       and not self.IsDirty(consider_untracked = False):
      self.work_git.DetachHead(HEAD)
      kill.append(cb)

    if kill:
      old = self.bare_git.GetHead()
      if old is None:
        old = 'refs/heads/please_never_use_this_as_a_branch_name'

      try:
        self.bare_git.DetachHead(rev)

        b = ['branch', '-d']
        b.extend(kill)
        b = GitCommand(self, b, bare=True,
                       capture_stdout=True,
                       capture_stderr=True)
        b.Wait()
      finally:
        self.bare_git.SetHead(old)
        left = self._allrefs

      for branch in kill:
        if (R_HEADS + branch) not in left:
          self.CleanPublishedCache()
          break

    if cb and cb not in kill:
      kill.append(cb)
    kill.sort()

    kept = []
    for branch in kill:
      if (R_HEADS + branch) in left:
        branch = self.GetBranch(branch)
        base = branch.LocalMerge
        if not base:
          base = rev
        kept.append(ReviewableBranch(self, branch, base))
    return kept


## Submodule Management ##

  def GetRegisteredSubprojects(self):
    result = []
    def rec(subprojects):
      if not subprojects:
        return
      result.extend(subprojects)
      for p in subprojects:
        rec(p.subprojects)
    rec(self.subprojects)
    return result

  def _GetSubmodules(self):
    # Unfortunately we cannot call `git submodule status --recursive` here
    # because the working tree might not exist yet, and it cannot be used
    # without a working tree in its current implementation.

    def get_submodules(gitdir, rev):
      # Parse .gitmodules for submodule sub_paths and sub_urls
      sub_paths, sub_urls = parse_gitmodules(gitdir, rev)
      if not sub_paths:
        return []
      # Run `git ls-tree` to read SHAs of submodule object, which happen to be
      # revision of submodule repository
      sub_revs = git_ls_tree(gitdir, rev, sub_paths)
      submodules = []
      for sub_path, sub_url in zip(sub_paths, sub_urls):
        try:
          sub_rev = sub_revs[sub_path]
        except KeyError:
          # Ignore non-exist submodules
          continue
        submodules.append((sub_rev, sub_path, sub_url))
      return submodules

    re_path = re.compile(r'^submodule\.([^.]+)\.path=(.*)$')
    re_url = re.compile(r'^submodule\.([^.]+)\.url=(.*)$')
    def parse_gitmodules(gitdir, rev):
      cmd = ['cat-file', 'blob', '%s:.gitmodules' % rev]
      try:
        p = GitCommand(None, cmd, capture_stdout = True, capture_stderr = True,
                       bare = True, gitdir = gitdir)
      except GitError:
        return [], []
      if p.Wait() != 0:
        return [], []

      gitmodules_lines = []
      fd, temp_gitmodules_path = tempfile.mkstemp()
      try:
        os.write(fd, p.stdout)
        os.close(fd)
        cmd = ['config', '--file', temp_gitmodules_path, '--list']
        p = GitCommand(None, cmd, capture_stdout = True, capture_stderr = True,
                       bare = True, gitdir = gitdir)
        if p.Wait() != 0:
          return [], []
        gitmodules_lines = p.stdout.split('\n')
      except GitError:
        return [], []
      finally:
        os.remove(temp_gitmodules_path)

      names = set()
      paths = {}
      urls = {}
      for line in gitmodules_lines:
        if not line:
          continue
        m = re_path.match(line)
        if m:
          names.add(m.group(1))
          paths[m.group(1)] = m.group(2)
          continue
        m = re_url.match(line)
        if m:
          names.add(m.group(1))
          urls[m.group(1)] = m.group(2)
          continue
      names = sorted(names)
      return ([paths.get(name, '') for name in names],
              [urls.get(name, '') for name in names])

    def git_ls_tree(gitdir, rev, paths):
      cmd = ['ls-tree', rev, '--']
      cmd.extend(paths)
      try:
        p = GitCommand(None, cmd, capture_stdout = True, capture_stderr = True,
                       bare = True, gitdir = gitdir)
      except GitError:
        return []
      if p.Wait() != 0:
        return []
      objects = {}
      for line in p.stdout.split('\n'):
        if not line.strip():
          continue
        object_rev, object_path = line.split()[2:4]
        objects[object_path] = object_rev
      return objects

    try:
      rev = self.GetRevisionId()
    except GitError:
      return []
    return get_submodules(self.gitdir, rev)

  def GetDerivedSubprojects(self):
    result = []
    if not self.Exists:
      # If git repo does not exist yet, querying its submodules will
      # mess up its states; so return here.
      return result
    for rev, path, url in self._GetSubmodules():
      name = self.manifest.GetSubprojectName(self, path)
      project = self.manifest.projects.get(name)
      if project:
        result.extend(project.GetDerivedSubprojects())
        continue
      relpath, worktree, gitdir = self.manifest.GetSubprojectPaths(self, path)
      remote = RemoteSpec(self.remote.name,
                          url = url,
                          review = self.remote.review)
      subproject = Project(manifest = self.manifest,
                           name = name,
                           remote = remote,
                           gitdir = gitdir,
                           worktree = worktree,
                           relpath = relpath,
                           revisionExpr = self.revisionExpr,
                           revisionId = rev,
                           rebase = self.rebase,
                           groups = self.groups,
                           sync_c = self.sync_c,
                           sync_s = self.sync_s,
                           parent = self,
                           is_derived = True)
      result.append(subproject)
      result.extend(subproject.GetDerivedSubprojects())
    return result


## Direct Git Commands ##

  def _RemoteFetch(self, name=None,
                   current_branch_only=False,
                   initial=False,
                   quiet=False,
                   alt_dir=None):

    is_sha1 = False
    tag_name = None

    def CheckForSha1():
      try:
        # if revision (sha or tag) is not present then following function
        # throws an error.
        self.bare_git.rev_parse('--verify', '%s^0' % self.revisionExpr)
        return True
      except GitError:
        # There is no such persistent revision. We have to fetch it.
        return False

    if current_branch_only:
      if ID_RE.match(self.revisionExpr) is not None:
        is_sha1 = True
      elif self.revisionExpr.startswith(R_TAGS):
        # this is a tag and its sha1 value should never change
        tag_name = self.revisionExpr[len(R_TAGS):]

      if is_sha1 or tag_name is not None:
        if CheckForSha1():
          return True
      if is_sha1 and (not self.upstream or ID_RE.match(self.upstream)):
        current_branch_only = False

    if not name:
      name = self.remote.name

    ssh_proxy = False
    remote = self.GetRemote(name)
    if remote.PreConnectFetch():
      ssh_proxy = True

    if initial:
      if alt_dir and 'objects' == os.path.basename(alt_dir):
        ref_dir = os.path.dirname(alt_dir)
        packed_refs = os.path.join(self.gitdir, 'packed-refs')
        remote = self.GetRemote(name)

        all_refs = self.bare_ref.all
        ids = set(all_refs.values())
        tmp = set()

        for r, ref_id in GitRefs(ref_dir).all.iteritems():
          if r not in all_refs:
            if r.startswith(R_TAGS) or remote.WritesTo(r):
              all_refs[r] = ref_id
              ids.add(ref_id)
              continue

          if ref_id in ids:
            continue

          r = 'refs/_alt/%s' % ref_id
          all_refs[r] = ref_id
          ids.add(ref_id)
          tmp.add(r)

        ref_names = list(all_refs.keys())
        ref_names.sort()

        tmp_packed = ''
        old_packed = ''

        for r in ref_names:
          line = '%s %s\n' % (all_refs[r], r)
          tmp_packed += line
          if r not in tmp:
            old_packed += line

        _lwrite(packed_refs, tmp_packed)
      else:
        alt_dir = None

    cmd = ['fetch']

    # The --depth option only affects the initial fetch; after that we'll do
    # full fetches of changes.
    depth = self.manifest.manifestProject.config.GetString('repo.depth')
    if depth and initial:
      cmd.append('--depth=%s' % depth)

    if quiet:
      cmd.append('--quiet')
    if not self.worktree:
      cmd.append('--update-head-ok')
    cmd.append(name)

    if not current_branch_only:
      # Fetch whole repo
      cmd.append('--tags')
      cmd.append((u'+refs/heads/*:') + remote.ToLocal('refs/heads/*'))
    elif tag_name is not None:
      cmd.append('tag')
      cmd.append(tag_name)
    else:
      branch = self.revisionExpr
      if is_sha1:
        branch = self.upstream
      if branch.startswith(R_HEADS):
        branch = branch[len(R_HEADS):]
      cmd.append((u'+refs/heads/%s:' % branch) + remote.ToLocal('refs/heads/%s' % branch))

    ok = False
    for _i in range(2):
      ret = GitCommand(self, cmd, bare=True, ssh_proxy=ssh_proxy).Wait()
      if ret == 0:
        ok = True
        break
      elif current_branch_only and is_sha1 and ret == 128:
        # Exit code 128 means "couldn't find the ref you asked for"; if we're in sha1
        # mode, we just tried sync'ing from the upstream field; it doesn't exist, thus
        # abort the optimization attempt and do a full sync.
        break
      time.sleep(random.randint(30, 45))

    if initial:
      if alt_dir:
        if old_packed != '':
          _lwrite(packed_refs, old_packed)
        else:
          os.remove(packed_refs)
      self.bare_git.pack_refs('--all', '--prune')

    if is_sha1 and current_branch_only and self.upstream:
      # We just synced the upstream given branch; verify we
      # got what we wanted, else trigger a second run of all
      # refs.
      if not CheckForSha1():
        return self._RemoteFetch(name=name, current_branch_only=False,
                                 initial=False, quiet=quiet, alt_dir=alt_dir)

    return ok

  def _ApplyCloneBundle(self, initial=False, quiet=False):
    if initial and self.manifest.manifestProject.config.GetString('repo.depth'):
      return False

    remote = self.GetRemote(self.remote.name)
    bundle_url = remote.url + '/clone.bundle'
    bundle_url = GitConfig.ForUser().UrlInsteadOf(bundle_url)
    if GetSchemeFromUrl(bundle_url) in ('persistent-http', 'persistent-https'):
      bundle_url = bundle_url[len('persistent-'):]
    if GetSchemeFromUrl(bundle_url) not in ('http', 'https'):
      return False

    bundle_dst = os.path.join(self.gitdir, 'clone.bundle')
    bundle_tmp = os.path.join(self.gitdir, 'clone.bundle.tmp')

    exist_dst = os.path.exists(bundle_dst)
    exist_tmp = os.path.exists(bundle_tmp)

    if not initial and not exist_dst and not exist_tmp:
      return False

    if not exist_dst:
      exist_dst = self._FetchBundle(bundle_url, bundle_tmp, bundle_dst, quiet)
    if not exist_dst:
      return False

    cmd = ['fetch']
    if quiet:
      cmd.append('--quiet')
    if not self.worktree:
      cmd.append('--update-head-ok')
    cmd.append(bundle_dst)
    for f in remote.fetch:
      cmd.append(str(f))
    cmd.append('refs/tags/*:refs/tags/*')

    ok = GitCommand(self, cmd, bare=True).Wait() == 0
    if os.path.exists(bundle_dst):
      os.remove(bundle_dst)
    if os.path.exists(bundle_tmp):
      os.remove(bundle_tmp)
    return ok

  def _FetchBundle(self, srcUrl, tmpPath, dstPath, quiet):
    if os.path.exists(dstPath):
      os.remove(dstPath)

    cmd = ['curl', '--fail', '--output', tmpPath, '--netrc', '--location']
    if quiet:
      cmd += ['--silent']
    if os.path.exists(tmpPath):
      size = os.stat(tmpPath).st_size
      if size >= 1024:
        cmd += ['--continue-at', '%d' % (size,)]
      else:
        os.remove(tmpPath)
    if 'http_proxy' in os.environ and 'darwin' == sys.platform:
      cmd += ['--proxy', os.environ['http_proxy']]
    cookiefile = GitConfig.ForUser().GetString('http.cookiefile')
    if cookiefile:
      cmd += ['--cookie', cookiefile]
    cmd += [srcUrl]

    if IsTrace():
      Trace('%s', ' '.join(cmd))
    try:
      proc = subprocess.Popen(cmd)
    except OSError:
      return False

    curlret = proc.wait()

    if curlret == 22:
      # From curl man page:
      # 22: HTTP page not retrieved. The requested url was not found or
      # returned another error with the HTTP error code being 400 or above.
      # This return code only appears if -f, --fail is used.
      if not quiet:
        print("Server does not provide clone.bundle; ignoring.",
              file=sys.stderr)
      return False

    if os.path.exists(tmpPath):
      if curlret == 0 and os.stat(tmpPath).st_size > 16:
        os.rename(tmpPath, dstPath)
        return True
      else:
        os.remove(tmpPath)
        return False
    else:
      return False

  def _Checkout(self, rev, quiet=False):
    cmd = ['checkout']
    if quiet:
      cmd.append('-q')
    cmd.append(rev)
    cmd.append('--')
    if GitCommand(self, cmd).Wait() != 0:
      if self._allrefs:
        raise GitError('%s checkout %s ' % (self.name, rev))

  def _CherryPick(self, rev, quiet=False):
    cmd = ['cherry-pick']
    cmd.append(rev)
    cmd.append('--')
    if GitCommand(self, cmd).Wait() != 0:
      if self._allrefs:
        raise GitError('%s cherry-pick %s ' % (self.name, rev))

  def _Revert(self, rev, quiet=False):
    cmd = ['revert']
    cmd.append('--no-edit')
    cmd.append(rev)
    cmd.append('--')
    if GitCommand(self, cmd).Wait() != 0:
      if self._allrefs:
        raise GitError('%s revert %s ' % (self.name, rev))

  def _ResetHard(self, rev, quiet=True):
    cmd = ['reset', '--hard']
    if quiet:
      cmd.append('-q')
    cmd.append(rev)
    if GitCommand(self, cmd).Wait() != 0:
      raise GitError('%s reset --hard %s ' % (self.name, rev))

  def _Rebase(self, upstream, onto = None):
    cmd = ['rebase']
    if onto is not None:
      cmd.extend(['--onto', onto])
    cmd.append(upstream)
    if GitCommand(self, cmd).Wait() != 0:
      raise GitError('%s rebase %s ' % (self.name, upstream))

  def _FastForward(self, head, ffonly=False):
    cmd = ['merge', head]
    if ffonly:
      cmd.append("--ff-only")
    if GitCommand(self, cmd).Wait() != 0:
      raise GitError('%s merge %s ' % (self.name, head))

  def _InitGitDir(self):
    if not os.path.exists(self.gitdir):
      os.makedirs(self.gitdir)
      self.bare_git.init()

      mp = self.manifest.manifestProject
      ref_dir = mp.config.GetString('repo.reference')

      if ref_dir:
        mirror_git = os.path.join(ref_dir, self.name + '.git')
        repo_git = os.path.join(ref_dir, '.repo', 'projects',
                                self.relpath + '.git')

        if os.path.exists(mirror_git):
          ref_dir = mirror_git

        elif os.path.exists(repo_git):
          ref_dir = repo_git

        else:
          ref_dir = None

        if ref_dir:
          _lwrite(os.path.join(self.gitdir, 'objects/info/alternates'),
                  os.path.join(ref_dir, 'objects') + '\n')

      if self.manifest.IsMirror:
        self.config.SetString('core.bare', 'true')
      else:
        self.config.SetString('core.bare', None)

      hooks = self._gitdir_path('hooks')
      try:
        to_rm = os.listdir(hooks)
      except OSError:
        to_rm = []
      for old_hook in to_rm:
        os.remove(os.path.join(hooks, old_hook))
      self._InitHooks()

      m = self.manifest.manifestProject.config
      for key in ['user.name', 'user.email']:
        if m.Has(key, include_defaults = False):
          self.config.SetString(key, m.GetString(key))

  def _InitHooks(self):
    hooks = self._gitdir_path('hooks')
    if not os.path.exists(hooks):
      os.makedirs(hooks)
    for stock_hook in _ProjectHooks():
      name = os.path.basename(stock_hook)

      if name in ('commit-msg',) and not self.remote.review \
            and not self is self.manifest.manifestProject:
        # Don't install a Gerrit Code Review hook if this
        # project does not appear to use it for reviews.
        #
        # Since the manifest project is one of those, but also
        # managed through gerrit, it's excluded
        continue

      dst = os.path.join(hooks, name)
      if os.path.islink(dst):
        continue
      if os.path.exists(dst):
        if filecmp.cmp(stock_hook, dst, shallow=False):
          os.remove(dst)
        else:
          _error("%s: Not replacing %s hook", self.relpath, name)
          continue
      try:
        os.symlink(os.path.relpath(stock_hook, os.path.dirname(dst)), dst)
      except OSError as e:
        if e.errno == errno.EPERM:
          raise GitError('filesystem must support symlinks')
        else:
          raise

  def _InitRemote(self):
    if self.remote.url:
      remote = self.GetRemote(self.remote.name)
      remote.url = self.remote.url
      remote.review = self.remote.review
      remote.projectname = self.name

      if self.worktree:
        remote.ResetFetch(mirror=False)
      else:
        remote.ResetFetch(mirror=True)
      remote.Save()

  def _InitMRef(self):
    if self.manifest.branch:
      self._InitAnyMRef(R_M + self.manifest.branch)

  def _InitMirrorHead(self):
    self._InitAnyMRef(HEAD)

  def _InitAnyMRef(self, ref):
    cur = self.bare_ref.symref(ref)

    if self.revisionId:
      if cur != '' or self.bare_ref.get(ref) != self.revisionId:
        msg = 'manifest set to %s' % self.revisionId
        dst = self.revisionId + '^0'
        self.bare_git.UpdateRef(ref, dst, message = msg, detach = True)
    else:
      remote = self.GetRemote(self.remote.name)
      dst = remote.ToLocal(self.revisionExpr)
      if cur != dst:
        msg = 'manifest set to %s' % self.revisionExpr
        self.bare_git.symbolic_ref('-m', msg, ref, dst)

  def _InitWorkTree(self):
    dotgit = os.path.join(self.worktree, '.git')
    if not os.path.exists(dotgit):
      os.makedirs(dotgit)

      for name in ['config',
                   'description',
                   'hooks',
                   'info',
                   'logs',
                   'objects',
                   'packed-refs',
                   'refs',
                   'rr-cache',
                   'svn']:
        try:
          src = os.path.join(self.gitdir, name)
          dst = os.path.join(dotgit, name)
          if os.path.islink(dst) or not os.path.exists(dst):
            os.symlink(os.path.relpath(src, os.path.dirname(dst)), dst)
          else:
            raise GitError('cannot overwrite a local work tree')
        except OSError as e:
          if e.errno == errno.EPERM:
            raise GitError('filesystem must support symlinks')
          else:
            raise

      _lwrite(os.path.join(dotgit, HEAD), '%s\n' % self.GetRevisionId())

      cmd = ['read-tree', '--reset', '-u']
      cmd.append('-v')
      cmd.append(HEAD)
      if GitCommand(self, cmd).Wait() != 0:
        raise GitError("cannot initialize work tree")

      rr_cache = os.path.join(self.gitdir, 'rr-cache')
      if not os.path.exists(rr_cache):
        os.makedirs(rr_cache)

      self._CopyFiles()

  def _gitdir_path(self, path):
    return os.path.join(self.gitdir, path)

  def _revlist(self, *args, **kw):
    a = []
    a.extend(args)
    a.append('--')
    return self.work_git.rev_list(*a, **kw)

  @property
  def _allrefs(self):
    return self.bare_ref.all

  class _GitGetByExec(object):
    def __init__(self, project, bare):
      self._project = project
      self._bare = bare

    def LsOthers(self):
      p = GitCommand(self._project,
                     ['ls-files',
                      '-z',
                      '--others',
                      '--exclude-standard'],
                     bare = False,
                     capture_stdout = True,
                     capture_stderr = True)
      if p.Wait() == 0:
        out = p.stdout
        if out:
          return out[:-1].split('\0')  # pylint: disable=W1401
                                       # Backslash is not anomalous
      return []

    def DiffZ(self, name, *args):
      cmd = [name]
      cmd.append('-z')
      cmd.extend(args)
      p = GitCommand(self._project,
                     cmd,
                     bare = False,
                     capture_stdout = True,
                     capture_stderr = True)
      try:
        out = p.process.stdout.read()
        r = {}
        if out:
          out = iter(out[:-1].split('\0'))  # pylint: disable=W1401
          while out:
            try:
              info = out.next()
              path = out.next()
            except StopIteration:
              break

            class _Info(object):
              def __init__(self, path, omode, nmode, oid, nid, state):
                self.path = path
                self.src_path = None
                self.old_mode = omode
                self.new_mode = nmode
                self.old_id = oid
                self.new_id = nid

                if len(state) == 1:
                  self.status = state
                  self.level = None
                else:
                  self.status = state[:1]
                  self.level = state[1:]
                  while self.level.startswith('0'):
                    self.level = self.level[1:]

            info = info[1:].split(' ')
            info = _Info(path, *info)
            if info.status in ('R', 'C'):
              info.src_path = info.path
              info.path = out.next()
            r[info.path] = info
        return r
      finally:
        p.Wait()

    def GetHead(self):
      if self._bare:
        path = os.path.join(self._project.gitdir, HEAD)
      else:
        path = os.path.join(self._project.worktree, '.git', HEAD)
      try:
        fd = open(path, 'rb')
      except IOError:
        raise NoManifestException(path)
      try:
        line = fd.read()
      finally:
        fd.close()
      if line.startswith('ref: '):
        return line[5:-1]
      return line[:-1]

    def SetHead(self, ref, message=None):
      cmdv = []
      if message is not None:
        cmdv.extend(['-m', message])
      cmdv.append(HEAD)
      cmdv.append(ref)
      self.symbolic_ref(*cmdv)

    def DetachHead(self, new, message=None):
      cmdv = ['--no-deref']
      if message is not None:
        cmdv.extend(['-m', message])
      cmdv.append(HEAD)
      cmdv.append(new)
      self.update_ref(*cmdv)

    def UpdateRef(self, name, new, old=None,
                  message=None,
                  detach=False):
      cmdv = []
      if message is not None:
        cmdv.extend(['-m', message])
      if detach:
        cmdv.append('--no-deref')
      cmdv.append(name)
      cmdv.append(new)
      if old is not None:
        cmdv.append(old)
      self.update_ref(*cmdv)

    def DeleteRef(self, name, old=None):
      if not old:
        old = self.rev_parse(name)
      self.update_ref('-d', name, old)
      self._project.bare_ref.deleted(name)

    def rev_list(self, *args, **kw):
      if 'format' in kw:
        cmdv = ['log', '--pretty=format:%s' % kw['format']]
      else:
        cmdv = ['rev-list']
      cmdv.extend(args)
      p = GitCommand(self._project,
                     cmdv,
                     bare = self._bare,
                     capture_stdout = True,
                     capture_stderr = True)
      r = []
      for line in p.process.stdout:
        if line[-1] == '\n':
          line = line[:-1]
        r.append(line)
      if p.Wait() != 0:
        raise GitError('%s rev-list %s: %s' % (
                       self._project.name,
                       str(args),
                       p.stderr))
      return r

    def __getattr__(self, name):
      """Allow arbitrary git commands using pythonic syntax.

      This allows you to do things like:
        git_obj.rev_parse('HEAD')

      Since we don't have a 'rev_parse' method defined, the __getattr__ will
      run.  We'll replace the '_' with a '-' and try to run a git command.
      Any other positional arguments will be passed to the git command, and the
      following keyword arguments are supported:
        config: An optional dict of git config options to be passed with '-c'.

      Args:
        name: The name of the git command to call.  Any '_' characters will
            be replaced with '-'.

      Returns:
        A callable object that will try to call git with the named command.
      """
      name = name.replace('_', '-')
      def runner(*args, **kwargs):
        cmdv = []
        config = kwargs.pop('config', None)
        for k in kwargs:
          raise TypeError('%s() got an unexpected keyword argument %r'
                          % (name, k))
        if config is not None:
          if not git_require((1, 7, 2)):
            raise ValueError('cannot set config on command line for %s()'
                             % name)
          for k, v in config.iteritems():
            cmdv.append('-c')
            cmdv.append('%s=%s' % (k, v))
        cmdv.append(name)
        cmdv.extend(args)
        p = GitCommand(self._project,
                       cmdv,
                       bare = self._bare,
                       capture_stdout = True,
                       capture_stderr = True)
        if p.Wait() != 0:
          raise GitError('%s %s: %s' % (
                         self._project.name,
                         name,
                         p.stderr))
        r = p.stdout
        if r.endswith('\n') and r.index('\n') == len(r) - 1:
          return r[:-1]
        return r
      return runner


class _PriorSyncFailedError(Exception):
  def __str__(self):
    return 'prior sync failed; rebase still in progress'

class _DirtyError(Exception):
  def __str__(self):
    return 'contains uncommitted changes'

class _InfoMessage(object):
  def __init__(self, project, text):
    self.project = project
    self.text = text

  def Print(self, syncbuf):
    syncbuf.out.info('%s/: %s', self.project.relpath, self.text)
    syncbuf.out.nl()

class _Failure(object):
  def __init__(self, project, why):
    self.project = project
    self.why = why

  def Print(self, syncbuf):
    syncbuf.out.fail('error: %s/: %s',
                     self.project.relpath,
                     str(self.why))
    syncbuf.out.nl()

class _Later(object):
  def __init__(self, project, action):
    self.project = project
    self.action = action

  def Run(self, syncbuf):
    out = syncbuf.out
    out.project('project %s/', self.project.relpath)
    out.nl()
    try:
      self.action()
      out.nl()
      return True
    except GitError:
      out.nl()
      return False

class _SyncColoring(Coloring):
  def __init__(self, config):
    Coloring.__init__(self, config, 'reposync')
    self.project   = self.printer('header', attr = 'bold')
    self.info      = self.printer('info')
    self.fail      = self.printer('fail', fg='red')

class SyncBuffer(object):
  def __init__(self, config, detach_head=False):
    self._messages = []
    self._failures = []
    self._later_queue1 = []
    self._later_queue2 = []

    self.out = _SyncColoring(config)
    self.out.redirect(sys.stderr)

    self.detach_head = detach_head
    self.clean = True

  def info(self, project, fmt, *args):
    self._messages.append(_InfoMessage(project, fmt % args))

  def fail(self, project, err=None):
    self._failures.append(_Failure(project, err))
    self.clean = False

  def later1(self, project, what):
    self._later_queue1.append(_Later(project, what))

  def later2(self, project, what):
    self._later_queue2.append(_Later(project, what))

  def Finish(self):
    self._PrintMessages()
    self._RunLater()
    self._PrintMessages()
    return self.clean

  def _RunLater(self):
    for q in ['_later_queue1', '_later_queue2']:
      if not self._RunQueue(q):
        return

  def _RunQueue(self, queue):
    for m in getattr(self, queue):
      if not m.Run(self):
        self.clean = False
        return False
    setattr(self, queue, [])
    return True

  def _PrintMessages(self):
    for m in self._messages:
      m.Print(self)
    for m in self._failures:
      m.Print(self)

    self._messages = []
    self._failures = []


class MetaProject(Project):
  """A special project housed under .repo.
  """
  def __init__(self, manifest, name, gitdir, worktree):
    Project.__init__(self,
                     manifest = manifest,
                     name = name,
                     gitdir = gitdir,
                     worktree = worktree,
                     remote = RemoteSpec('origin'),
                     relpath = '.repo/%s' % name,
                     revisionExpr = 'refs/heads/master',
                     revisionId = None,
                     groups = None)

  def PreSync(self):
    if self.Exists:
      cb = self.CurrentBranch
      if cb:
        base = self.GetBranch(cb).merge
        if base:
          self.revisionExpr = base
          self.revisionId = None

  def MetaBranchSwitch(self, target):
    """ Prepare MetaProject for manifest branch switch
    """

    # detach and delete manifest branch, allowing a new
    # branch to take over
    syncbuf = SyncBuffer(self.config, detach_head = True)
    self.Sync_LocalHalf(syncbuf)
    syncbuf.Finish()

    return GitCommand(self,
                        ['update-ref', '-d', 'refs/heads/default'],
                        capture_stdout = True,
                        capture_stderr = True).Wait() == 0


  @property
  def LastFetch(self):
    try:
      fh = os.path.join(self.gitdir, 'FETCH_HEAD')
      return os.path.getmtime(fh)
    except OSError:
      return 0

  @property
  def HasChanges(self):
    """Has the remote received new commits not yet checked out?
    """
    if not self.remote or not self.revisionExpr:
      return False

    all_refs = self.bare_ref.all
    revid = self.GetRevisionId(all_refs)
    head = self.work_git.GetHead()
    if head.startswith(R_HEADS):
      try:
        head = all_refs[head]
      except KeyError:
        head = None

    if revid == head:
      return False
    elif self._revlist(not_rev(HEAD), revid):
      return True
    return False
