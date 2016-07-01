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
import os
import platform
import re
import shutil
import sys

from pyversion import is_python3
if is_python3():
  import urllib.parse
else:
  import imp
  import urlparse
  urllib = imp.new_module('urllib')
  urllib.parse = urlparse

from color import Coloring
from command import InteractiveCommand, MirrorSafeCommand
from error import ManifestParseError
from project import SyncBuffer
from git_config import GitConfig
from git_command import git_require, MIN_GIT_VERSION

class Init(InteractiveCommand, MirrorSafeCommand):
  common = True
  helpSummary = "Initialize repo in the current directory"
  helpUsage = """
%prog [options]
"""
  helpDescription = """
The '%prog' command is run once to install and initialize repo.
The latest repo source code and manifest collection is downloaded
from the server and is installed in the .repo/ directory in the
current working directory.

The optional -b argument can be used to select the manifest branch
to checkout and use.  If no branch is specified, master is assumed.

The optional -m argument can be used to specify an alternate manifest
to be used. If no manifest is specified, the manifest default.xml
will be used.

The --reference option can be used to point to a directory that
has the content of a --mirror sync. This will make the working
directory use as much data as possible from the local reference
directory when fetching from the server. This will make the sync
go a lot faster by reducing data traffic on the network.


Switching Manifest Branches
---------------------------

To switch to another manifest branch, `repo init -b otherbranch`
may be used in an existing client.  However, as this only updates the
manifest, a subsequent `repo sync` (or `repo sync -d`) is necessary
to update the working directory files.
"""

  def _Options(self, p):
    # Logging
    g = p.add_option_group('Logging options')
    g.add_option('-q', '--quiet',
                 dest="quiet", action="store_true", default=False,
                 help="be quiet")

    # Manifest
    g = p.add_option_group('Manifest options')
    g.add_option('-u', '--manifest-url',
                 dest='manifest_url',
                 help='manifest repository location', metavar='URL')
    g.add_option('-b', '--manifest-branch',
                 dest='manifest_branch',
                 help='manifest branch or revision', metavar='REVISION')
    g.add_option('-m', '--manifest-name',
                 dest='manifest_name', default='default.xml',
                 help='initial manifest file', metavar='NAME.xml')
    g.add_option('--mirror',
                 dest='mirror', action='store_true',
                 help='create a replica of the remote repositories '
                      'rather than a client working directory')
    g.add_option('--reference',
                 dest='reference',
                 help='location of mirror directory', metavar='DIR')
    g.add_option('--depth', type='int', default=None,
                 dest='depth',
                 help='create a shallow clone with given depth; see git clone')
    g.add_option('--archive',
                 dest='archive', action='store_true',
                 help='checkout an archive instead of a git repository for '
                      'each project. See git archive.')
    g.add_option('-g', '--groups',
                 dest='groups', default='default',
                 help='restrict manifest projects to ones with specified '
                      'group(s) [default|all|G1,G2,G3|G4,-G5,-G6]',
                 metavar='GROUP')
    g.add_option('-p', '--platform',
                 dest='platform', default='auto',
                 help='restrict manifest projects to ones with a specified '
                      'platform group [auto|all|none|linux|darwin|...]',
                 metavar='PLATFORM')

    # Tool
    g = p.add_option_group('repo Version options')
    g.add_option('--repo-url',
                 dest='repo_url',
                 help='repo repository location', metavar='URL')
    g.add_option('--repo-branch',
                 dest='repo_branch',
                 help='repo branch or revision', metavar='REVISION')
    g.add_option('--no-repo-verify',
                 dest='no_repo_verify', action='store_true',
                 help='do not verify repo source code')

    # Other
    g = p.add_option_group('Other options')
    g.add_option('--config-name',
                 dest='config_name', action="store_true", default=False,
                 help='Always prompt for name/e-mail')

  def _RegisteredEnvironmentOptions(self):
    return {'REPO_MANIFEST_URL': 'manifest_url',
            'REPO_MIRROR_LOCATION': 'reference'}

  def _SyncManifest(self, opt):
    m = self.manifest.manifestProject
    is_new = not m.Exists

    if is_new:
      if not opt.manifest_url:
        print('fatal: manifest url (-u) is required.', file=sys.stderr)
        sys.exit(1)

      if not opt.quiet:
        print('Get %s' % GitConfig.ForUser().UrlInsteadOf(opt.manifest_url),
              file=sys.stderr)

      # The manifest project object doesn't keep track of the path on the
      # server where this git is located, so let's save that here.
      mirrored_manifest_git = None
      if opt.reference:
        manifest_git_path = urllib.parse.urlparse(opt.manifest_url).path[1:]
        mirrored_manifest_git = os.path.join(opt.reference, manifest_git_path)
        if not mirrored_manifest_git.endswith(".git"):
          mirrored_manifest_git += ".git"
        if not os.path.exists(mirrored_manifest_git):
          mirrored_manifest_git = os.path.join(opt.reference + '/.repo/manifests.git')

      m._InitGitDir(mirror_git=mirrored_manifest_git)

      if opt.manifest_branch:
        m.revisionExpr = opt.manifest_branch
      else:
        m.revisionExpr = 'refs/heads/master'
    else:
      if opt.manifest_branch:
        m.revisionExpr = opt.manifest_branch
      else:
        m.PreSync()

    if opt.manifest_url:
      r = m.GetRemote(m.remote.name)
      r.url = opt.manifest_url
      r.ResetFetch()
      r.Save()

    groups = re.split(r'[,\s]+', opt.groups)
    all_platforms = ['linux', 'darwin', 'windows']
    platformize = lambda x: 'platform-' + x
    if opt.platform == 'auto':
      if (not opt.mirror and
          not m.config.GetString('repo.mirror') == 'true'):
        groups.append(platformize(platform.system().lower()))
    elif opt.platform == 'all':
      groups.extend(map(platformize, all_platforms))
    elif opt.platform in all_platforms:
      groups.append(platformize(opt.platform))
    elif opt.platform != 'none':
      print('fatal: invalid platform flag', file=sys.stderr)
      sys.exit(1)

    groups = [x for x in groups if x]
    groupstr = ','.join(groups)
    if opt.platform == 'auto' and groupstr == 'default,platform-' + platform.system().lower():
      groupstr = None
    m.config.SetString('manifest.groups', groupstr)

    if opt.reference:
      m.config.SetString('repo.reference', opt.reference)

    if opt.archive:
      if is_new:
        m.config.SetString('repo.archive', 'true')
      else:
        print('fatal: --archive is only supported when initializing a new '
              'workspace.', file=sys.stderr)
        print('Either delete the .repo folder in this workspace, or initialize '
              'in another location.', file=sys.stderr)
        sys.exit(1)

    if opt.mirror:
      if is_new:
        m.config.SetString('repo.mirror', 'true')
      else:
        print('fatal: --mirror is only supported when initializing a new '
              'workspace.', file=sys.stderr)
        print('Either delete the .repo folder in this workspace, or initialize '
              'in another location.', file=sys.stderr)
        sys.exit(1)

    if not m.Sync_NetworkHalf(is_new=is_new):
      r = m.GetRemote(m.remote.name)
      print('fatal: cannot obtain manifest %s' % r.url, file=sys.stderr)

      # Better delete the manifest git dir if we created it; otherwise next
      # time (when user fixes problems) we won't go through the "is_new" logic.
      if is_new:
        portable.rmtree(m.gitdir)
      sys.exit(1)

    if opt.manifest_branch:
      m.MetaBranchSwitch()

    syncbuf = SyncBuffer(m.config)
    m.Sync_LocalHalf(syncbuf)
    syncbuf.Finish()

    if is_new or m.CurrentBranch is None:
      if not m.StartBranch('default'):
        print('fatal: cannot create default in manifest', file=sys.stderr)
        sys.exit(1)

  def _LinkManifest(self, name):
    if not name:
      print('fatal: manifest name (-m) is required.', file=sys.stderr)
      sys.exit(1)

    try:
      self.manifest.Link(name)
    except ManifestParseError as e:
      print("fatal: manifest '%s' not available" % name, file=sys.stderr)
      print('fatal: %s' % str(e), file=sys.stderr)
      sys.exit(1)

  def _Prompt(self, prompt, value):
    sys.stdout.write('%-10s [%s]: ' % (prompt, value))
    a = sys.stdin.readline().strip()
    if a == '':
      return value
    return a

  def _ShouldConfigureUser(self):
    gc = self.manifest.globalConfig
    mp = self.manifest.manifestProject

    # If we don't have local settings, get from global.
    if not mp.config.Has('user.name') or not mp.config.Has('user.email'):
      if not gc.Has('user.name') or not gc.Has('user.email'):
        return True

      mp.config.SetString('user.name', gc.GetString('user.name'))
      mp.config.SetString('user.email', gc.GetString('user.email'))

    print()
    print('Your identity is: %s <%s>' % (mp.config.GetString('user.name'),
                                         mp.config.GetString('user.email')))
    print('If you want to change this, please re-run \'repo init\' with --config-name')
    return False

  def _ConfigureUser(self):
    mp = self.manifest.manifestProject

    while True:
      print()
      name  = self._Prompt('Your Name', mp.UserName)
      email = self._Prompt('Your Email', mp.UserEmail)

      print()
      print('Your identity is: %s <%s>' % (name, email))
      sys.stdout.write('is this correct [y/N]? ')
      a = sys.stdin.readline().strip().lower()
      if a in ('yes', 'y', 't', 'true'):
        break

    if name != mp.UserName:
      mp.config.SetString('user.name', name)
    if email != mp.UserEmail:
      mp.config.SetString('user.email', email)

  def _HasColorSet(self, gc):
    for n in ['ui', 'diff', 'status']:
      if gc.Has('color.%s' % n):
        return True
    return False

  def _ConfigureColor(self):
    gc = self.manifest.globalConfig
    if self._HasColorSet(gc):
      return

    class _Test(Coloring):
      def __init__(self):
        Coloring.__init__(self, gc, 'test color display')
        self._on = True
    out = _Test()

    print()
    print("Testing colorized output (for 'repo diff', 'repo status'):")

    for c in ['black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan']:
      out.write(' ')
      out.printer(fg=c)(' %-6s ', c)
    out.write(' ')
    out.printer(fg='white', bg='black')(' %s ' % 'white')
    out.nl()

    for c in ['bold', 'dim', 'ul', 'reverse']:
      out.write(' ')
      out.printer(fg='black', attr=c)(' %-6s ', c)
    out.nl()

    sys.stdout.write('Enable color display in this user account (y/N)? ')
    a = sys.stdin.readline().strip().lower()
    if a in ('y', 'yes', 't', 'true', 'on'):
      gc.SetString('color.ui', 'auto')

  def _ConfigureDepth(self, opt):
    """Configure the depth we'll sync down.

    Args:
      opt: Options from optparse.  We care about opt.depth.
    """
    # Opt.depth will be non-None if user actually passed --depth to repo init.
    if opt.depth is not None:
      if opt.depth > 0:
        # Positive values will set the depth.
        depth = str(opt.depth)
      else:
        # Negative numbers will clear the depth; passing None to SetString
        # will do that.
        depth = None

      # We store the depth in the main manifest project.
      self.manifest.manifestProject.config.SetString('repo.depth', depth)

  def _DisplayResult(self):
    if self.manifest.IsMirror:
      init_type = 'mirror '
    else:
      init_type = ''

    print()
    print('repo %shas been initialized in %s'
          % (init_type, self.manifest.topdir))

    current_dir = os.getcwd()
    if current_dir != self.manifest.topdir:
      print('If this is not the directory in which you want to initialize '
            'repo, please run:')
      print('   rm -r %s/.repo' % self.manifest.topdir)
      print('and try again.')

  def Execute(self, opt, args):
    git_require(MIN_GIT_VERSION, fail=True)

    if opt.reference:
      opt.reference = os.path.expanduser(opt.reference)

    # Check this here, else manifest will be tagged "not new" and init won't be
    # possible anymore without removing the .repo/manifests directory.
    if opt.archive and opt.mirror:
      print('fatal: --mirror and --archive cannot be used together.',
            file=sys.stderr)
      sys.exit(1)

    self._SyncManifest(opt)
    self._LinkManifest(opt.manifest_name)

    if os.isatty(0) and os.isatty(1) and not self.manifest.IsMirror:
      if opt.config_name or self._ShouldConfigureUser():
        self._ConfigureUser()
      self._ConfigureColor()

    self._ConfigureDepth(opt)

    self._DisplayResult()
