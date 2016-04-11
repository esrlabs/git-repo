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
import copy
import re
import sys

from command import InteractiveCommand
from editor import Editor
from error import GitError, HookError, UploadError
from git_command import GitCommand
from project import RepoHook

from git_refs import GitRefs, HEAD, R_HEADS, R_TAGS, R_PUB, R_M

from pyversion import is_python3
# pylint:disable=W0622
if not is_python3():
  input = raw_input
else:
  unicode = str
# pylint:enable=W0622

UNUSUAL_COMMIT_THRESHOLD = 5

def _ConfirmManyPushs(multiple_branches=False):
  if multiple_branches:
    print('ATTENTION: One or more branches has an unusually high number '
          'of commits.')
  else:
    print('ATTENTION: You are pushing an unusually high number of commits.')
  print('YOU PROBABLY DO NOT MEAN TO DO THIS. (Did you rebase across '
        'branches?)')
  answer = input("If you are sure you intend to do this, type 'yes': ").strip()
  return answer == "yes"

def _die(fmt, *args):
  msg = fmt % args
  print('error: %s' % msg, file=sys.stderr)
  sys.exit(1)

class Push(InteractiveCommand):
  common = True
  helpSummary = "Push changes (bypass code review)"
  helpUsage = """
%prog [<project>]...
"""
  helpDescription = """
The '%prog' command is used to push changes to its remote branch.
It searches for topic branches in local projects that have not yet
been pushed (or published for review).  If multiple topic branches
are found, '%prog' opens an editor to allow the user to select
which branches to push.

'%prog' searches for pushable changes in all projects listed at
the command line.  Projects can be specified either by name, or by
a relative or absolute path to the project's local directory. If no
projects are specified, '%prog' will search for pushadable changes
in all projects listed in the manifest.

"""

  def _Options(self, p):
    p.add_option('--br',
                 type='string',  action='store', dest='branch',
                 help='Branch to push.')
    p.add_option('--cbr', '--current-branch',
                 dest='current_branch', action='store_true',
                 help='Push current git branch.')
    p.add_option('-D', '--destination', '--dest',
                 type='string', action='store', dest='dest_branch',
                 metavar='BRANCH',
                 help='Push on this target branch.')
    p.add_option('-f', '--force',
                 dest='force_push',
                 action='store_true',
                 help='Force push')

    # Options relating to push hook.  Note that verify and no-verify are NOT
    # opposites of each other, which is why they store to different locations.
    # We are using them to match 'git commit' syntax.
    #
    # Combinations:
    # - no-verify=False, verify=False (DEFAULT):
    #   If stdout is a tty, can prompt about running push hooks if needed.
    #   If user denies running hooks, the push is cancelled.  If stdout is
    #   not a tty and we would need to prompt about push hooks, push is
    #   cancelled.
    # - no-verify=False, verify=True:
    #   Always run push hooks with no prompt.
    # - no-verify=True, verify=False:
    #   Never run push hooks, but push anyway (AKA bypass hooks).
    # - no-verify=True, verify=True:
    #   Invalid
    p.add_option('--no-verify',
                 dest='bypass_hooks', action='store_true',
                 help='Do not run the push hook.')
    p.add_option('--verify',
                 dest='allow_all_hooks', action='store_true',
                 help='Run the push hook without prompting.')

  def _SingleBranch(self, opt, branch):
    project = branch.project
    name = branch.name
    remote = project.GetBranch(name).remote

    date = branch.date
    commit_list = branch.commits

    destination = opt.dest_branch or project.dest_branch or project.revisionExpr
    print('Push project %s/ to remote branch %s:' % (project.relpath, destination))
    print('  branch %s (%2d commit%s, %s):' % (
                  name,
                  len(commit_list),
                  len(commit_list) != 1 and 's' or '',
                  date))
    for commit in commit_list:
      print('         %s' % commit)

    sys.stdout.write('to %s (y/N)? ' % remote.name)
    answer = sys.stdin.readline().strip().lower()
    answer = answer in ('y', 'yes', '1', 'true', 't')

    if answer:
      if len(branch.commits) > UNUSUAL_COMMIT_THRESHOLD:
        answer = _ConfirmManyPushs()

    if answer:
      self._Push(opt, [branch])
    else:
      _die("push aborted by user")

  def _MultipleBranches(self, opt, pending):
    projects = {}
    branches = {}

    script = []
    script.append('# Uncomment the branches to push:')
    for project, avail in pending:
      script.append('#')
      script.append('# project %s/:' % project.relpath)

      b = {}
      for branch in avail:
        if branch is None:
          continue
        name = branch.name
        date = branch.date
        commit_list = branch.commits

        if b:
          script.append('#')
        destination = opt.dest_branch or project.dest_branch or project.revisionExpr
        script.append('#  branch %s (%2d commit%s, %s) to remote branch %s:' % (
                      name,
                      len(commit_list),
                      len(commit_list) != 1 and 's' or '',
                      date,
                      destination))
        for commit in commit_list:
          script.append('#         %s' % commit)
        b[name] = branch

      projects[project.relpath] = project
      branches[project.name] = b
    script.append('')

    script = [ x.encode('utf-8')
             if issubclass(type(x), unicode)
             else x
             for x in script ]

    script = Editor.EditString("\n".join(script)).split("\n")

    project_re = re.compile(r'^#?\s*project\s*([^\s]+)/:$')
    branch_re = re.compile(r'^\s*branch\s*([^\s(]+)\s*\(.*')

    project = None
    todo = []

    for line in script:
      m = project_re.match(line)
      if m:
        name = m.group(1)
        project = projects.get(name)
        if not project:
          _die('project %s not available for push', name)
        continue

      m = branch_re.match(line)
      if m:
        name = m.group(1)
        if not project:
          _die('project for branch %s not in script', name)
        branch = branches[project.name].get(name)
        if not branch:
          _die('branch %s not in %s', name, project.relpath)
        todo.append(branch)
    if not todo:
      _die("nothing uncommented for push")

    many_commits = False
    for branch in todo:
      if len(branch.commits) > UNUSUAL_COMMIT_THRESHOLD:
        many_commits = True
        break
    if many_commits:
      if not _ConfirmManyPushs(multiple_branches=True):
        _die("push aborted by user")

    self._Push(opt, todo)

  def _Push(self, opt, todo):
    have_errors = False
    for branch in todo:
      try:
        # Check if there are local changes that may have been forgotten
        changes = branch.project.UncommitedFiles()
        if changes:
          sys.stdout.write('Uncommitted changes in ' + branch.project.name)
          sys.stdout.write(' (did you forget to amend?):\n')
          sys.stdout.write('\n'.join(changes) + '\n')
          sys.stdout.write('Continue pushing? (y/N) ')
          a = sys.stdin.readline().strip().lower()
          if a not in ('y', 'yes', 't', 'true', 'on'):
            print("skipping push", file=sys.stderr)
            branch.uploaded = False
            branch.error = 'User aborted'
            continue

        destination = opt.dest_branch or branch.project.dest_branch

        # Make sure our local branch is not setup to track a different remote branch
        merge_branch = self._GetMergeBranch(branch.project)
        if destination:
          full_dest = 'refs/heads/%s' % destination
          if not opt.dest_branch and merge_branch and merge_branch != full_dest:
            print('merge branch %s does not match destination branch %s'
                  % (merge_branch, full_dest))
            print('skipping push.')
            print('Please use `--destination %s` if this is intentional'
                  % destination)
            branch.uploaded = False
            continue

        self.Push(branch, dest_branch=destination, force=opt.force_push)
        branch.uploaded = True
      except UploadError as e:
        branch.error = e
        branch.uploaded = False
        have_errors = True

    print(file=sys.stderr)
    print('----------------------------------------------------------------------', file=sys.stderr)

    if have_errors:
      for branch in todo:
        if not branch.uploaded:
          if len(str(branch.error)) <= 30:
            fmt = ' (%s)'
          else:
            fmt = '\n       (%s)'
          print(('[FAILED] %-15s %-15s' + fmt) % (
                 branch.project.relpath + '/', \
                 branch.name, \
                 str(branch.error)),
                 file=sys.stderr)
      print()

    for branch in todo:
      if branch.uploaded:
        print('[OK    ] %-15s %s' % (
               branch.project.relpath + '/',
               branch.name),
               file=sys.stderr)

    if have_errors:
      sys.exit(1)

  def Push(self, branch_base, branch=None,
                      dest_branch=None, force=False):
    """Pushs the named branch.
    """
    project = branch_base.project
    if branch is None:
      branch = project.CurrentBranch
    if branch is None:
      raise GitError('not currently on a branch')

    branch = project.GetBranch(branch)
    if not branch.LocalMerge:
      raise GitError('branch %s does not track a remote' % branch.name)

    if dest_branch is None:
      dest_branch = project.dest_branch
    if dest_branch is None:
      dest_branch = branch.merge
    if not dest_branch.startswith(R_HEADS):
      dest_branch = R_HEADS + dest_branch

    if not branch.remote.projectname:
      branch.remote.projectname = project.name
      branch.remote.Save()

    remote = branch.remote.name
    cmd = ['push']

    if force:
       cmd.append('--force')

    cmd.append(remote)

    if dest_branch.startswith(R_HEADS):
      dest_branch = dest_branch[len(R_HEADS):]

    push_type = 'heads'
    ref_spec = '%s:refs/%s/%s' % (R_HEADS + branch.name, push_type,
                                  dest_branch)
    cmd.append(ref_spec)

    if GitCommand(project, cmd, bare=True).Wait() != 0:
      raise UploadError('Push failed')

  def _GetMergeBranch(self, project):
    p = GitCommand(project,
                   ['rev-parse', '--abbrev-ref', 'HEAD'],
                   capture_stdout = True,
                   capture_stderr = True)
    p.Wait()
    local_branch = p.stdout.strip()
    p = GitCommand(project,
                   ['config', '--get', 'branch.%s.merge' % local_branch],
                   capture_stdout = True,
                   capture_stderr = True)
    p.Wait()
    merge_branch = p.stdout.strip()
    return merge_branch

  def Execute(self, opt, args):
    self.opt = opt
    project_list = self.GetProjects(args)
    pending = []
    branch = None

    if opt.branch:
      branch = opt.branch

    for project in project_list:
      if opt.current_branch:
        cbr = project.CurrentBranch
        up_branch = project.GetUploadableBranch(cbr)
        if up_branch:
          avail = [up_branch]
        else:
          avail = None
          print('ERROR: Current branch (%s) not pushable. '
                'You may be able to type '
                '"git branch --set-upstream-to m/master" to fix '
                'your branch.' % str(cbr),
                file=sys.stderr)
      else:
        avail = project.GetUploadableBranches(branch)
      if avail:
        pending.append((project, avail))

    if pending and (not opt.bypass_hooks):
      hook = RepoHook('pre-push', self.manifest.repo_hooks_project,
                      self.manifest.topdir, abort_if_user_denies=True)
      pending_proj_names = [project.name for (project, avail) in pending]
      pending_worktrees = [project.worktree for (project, avail) in pending]
      try:
        hook.Run(opt.allow_all_hooks, project_list=pending_proj_names,
                 worktree_list=pending_worktrees)
      except HookError as e:
        print("ERROR: %s" % str(e), file=sys.stderr)
        return

    if not pending:
      print("no branches ready for push", file=sys.stderr)
    elif len(pending) == 1 and len(pending[0][1]) == 1:
      self._SingleBranch(opt, pending[0][1][0])
    else:
      self._MultipleBranches(opt, pending)
