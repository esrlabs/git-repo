#!/usr/bin/env python
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
import getpass
import imp
import netrc
import optparse
import os
import portable
import subprocess
import sys
import time

from pyversion import is_python3
if is_python3():
  import urllib.request
else:
  import urllib2
  urllib = imp.new_module('urllib')
  urllib.request = urllib2

try:
  import kerberos
except ImportError:
  kerberos = None

from color import SetDefaultColoring
from trace import SetTrace
from git_command import git, GitCommand
from git_config import init_ssh, close_ssh
from command import InteractiveCommand
from command import MirrorSafeCommand
from command import GitcAvailableCommand, GitcClientCommand
from subcmds.version import Version
from editor import Editor
from error import DownloadError
from error import InvalidProjectGroupsError
from error import ManifestInvalidRevisionError
from error import ManifestParseError
from error import NoManifestException
from error import NoSuchProjectError
from error import RepoChangedException
import gitc_utils
from manifest_xml import GitcManifest, XmlManifest
from pager import RunPager
from wrapper import WrapperPath, Wrapper

from subcmds import all_commands

if not is_python3():
  # pylint:disable=W0622
  input = raw_input
  # pylint:enable=W0622

global_options = optparse.OptionParser(
                 usage="repo [-p|--paginate|--no-pager] COMMAND [ARGS]"
                 )
global_options.add_option('-p', '--paginate',
                          dest='pager', action='store_true',
                          help='display command output in the pager')
global_options.add_option('--no-pager',
                          dest='no_pager', action='store_true',
                          help='disable the pager')
global_options.add_option('--color',
                          choices=('auto', 'always', 'never'), default=None,
                          help='control color usage: auto, always, never')
global_options.add_option('--trace',
                          dest='trace', action='store_true',
                          help='trace git command execution')
global_options.add_option('--time',
                          dest='time', action='store_true',
                          help='time repo command execution')
global_options.add_option('--version',
                          dest='show_version', action='store_true',
                          help='display this version of repo')

class _Repo(object):
  def __init__(self, repodir):
    self.repodir = repodir
    self.commands = all_commands
    # add 'branch' as an alias for 'branches'
    all_commands['branch'] = all_commands['branches']

  def _Run(self, argv):
    result = 0
    name = None
    glob = []

    for i in range(len(argv)):
      if not argv[i].startswith('-'):
        name = argv[i]
        if i > 0:
          glob = argv[:i]
        argv = argv[i + 1:]
        break
    if not name:
      glob = argv
      name = 'help'
      argv = []
    gopts, _gargs = global_options.parse_args(glob)

    if gopts.trace:
      SetTrace()
    if gopts.show_version:
      if name == 'help':
        name = 'version'
      else:
        print('fatal: invalid usage of --version', file=sys.stderr)
        return 1

    SetDefaultColoring(gopts.color)

    try:
      cmd = self.commands[name]
    except KeyError:
      print("repo: '%s' is not a repo command.  See 'repo help'." % name,
            file=sys.stderr)
      return 1

    cmd.repodir = self.repodir
    cmd.manifest = XmlManifest(cmd.repodir)
    cmd.gitc_manifest = None
    gitc_client_name = gitc_utils.parse_clientdir(os.getcwd())
    if gitc_client_name:
      cmd.gitc_manifest = GitcManifest(cmd.repodir, gitc_client_name)
      cmd.manifest.isGitcClient = True

    Editor.globalConfig = cmd.manifest.globalConfig

    if not isinstance(cmd, MirrorSafeCommand) and cmd.manifest.IsMirror:
      print("fatal: '%s' requires a working directory" % name,
            file=sys.stderr)
      return 1

    if isinstance(cmd, GitcAvailableCommand) and not gitc_utils.get_gitc_manifest_dir():
      print("fatal: '%s' requires GITC to be available" % name,
            file=sys.stderr)
      return 1

    if isinstance(cmd, GitcClientCommand) and not gitc_client_name:
      print("fatal: '%s' requires a GITC client" % name,
            file=sys.stderr)
      return 1

    try:
      copts, cargs = cmd.OptionParser.parse_args(argv)
      copts = cmd.ReadEnvironmentOptions(copts)
    except NoManifestException as e:
      print('error: in `%s`: %s' % (' '.join([name] + argv), str(e)),
        file=sys.stderr)
      print('error: manifest missing or unreadable -- please run init',
            file=sys.stderr)
      return 1

    if not gopts.no_pager and not isinstance(cmd, InteractiveCommand):
      config = cmd.manifest.globalConfig
      if gopts.pager:
        use_pager = True
      else:
        use_pager = config.GetBoolean('pager.%s' % name)
        if use_pager is None:
          use_pager = cmd.WantPager(copts)
      if use_pager:
        # RunPager(cmd)
        portable.RunPager(cmd)
    else:
      portable.NoPager(cmd)

    start = time.time()
    try:
      result = cmd.Execute(copts, cargs)
    except (DownloadError, ManifestInvalidRevisionError,
        NoManifestException) as e:
      print('error: in `%s`: %s' % (' '.join([name] + argv), str(e)),
        file=sys.stderr)
      if isinstance(e, NoManifestException):
        print('error: manifest missing or unreadable -- please run init',
              file=sys.stderr)
      result = 1
    except NoSuchProjectError as e:
      if e.name:
        print('error: project %s not found' % e.name, file=sys.stderr)
      else:
        print('error: no project in current directory', file=sys.stderr)
      result = 1
    except InvalidProjectGroupsError as e:
      if e.name:
        print('error: project group must be enabled for project %s' % e.name, file=sys.stderr)
      else:
        print('error: project group must be enabled for the project in the current directory', file=sys.stderr)
      result = 1
    finally:
      elapsed = time.time() - start
      hours, remainder = divmod(elapsed, 3600)
      minutes, seconds = divmod(remainder, 60)
      if gopts.time:
        if hours == 0:
          print('real\t%dm%.3fs' % (minutes, seconds), file=sys.stderr)
        else:
          print('real\t%dh%dm%.3fs' % (hours, minutes, seconds),
                file=sys.stderr)

    return result


def _MyRepoPath():
  return os.path.dirname(__file__)


def _CheckWrapperVersion(ver, repo_path):
  if not repo_path:
    repo_path = '~/bin/repo'

  if not ver:
    print('no --wrapper-version argument', file=sys.stderr)
    sys.exit(1)

  exp = Wrapper().VERSION
  ver = tuple(map(int, ver.split('.')))
  if len(ver) == 1:
    ver = (0, ver[0])

  exp_str = '.'.join(map(str, exp))
  if exp[0] > ver[0] or ver < (0, 4):
    print("""
!!! A new repo command (%5s) is available.    !!!
!!! You must upgrade before you can continue:   !!!

    cp %s %s
""" % (exp_str, WrapperPath(), repo_path), file=sys.stderr)
    sys.exit(1)

  if exp > ver:
    print("""
... A new repo command (%5s) is available.
... You should upgrade soon:

    cp %s %s
""" % (exp_str, WrapperPath(), repo_path), file=sys.stderr)

def _CheckRepoDir(repo_dir):
  if not repo_dir:
    print('no --repo-dir argument', file=sys.stderr)
    sys.exit(1)

def _PruneOptions(argv, opt):
  i = 0
  while i < len(argv):
    a = argv[i]
    if a == '--':
      break
    if a.startswith('--'):
      eq = a.find('=')
      if eq > 0:
        a = a[0:eq]
    if not opt.has_option(a):
      del argv[i]
      continue
    i += 1

_user_agent = None

def _UserAgent():
  global _user_agent

  if _user_agent is None:
    py_version = sys.version_info

    os_name = sys.platform
    if os_name == 'linux2':
      os_name = 'Linux'
    elif os_name == 'win32':
      os_name = 'Win32'
    elif os_name == 'cygwin':
      os_name = 'Cygwin'
    elif os_name == 'darwin':
      os_name = 'Darwin'

    p = GitCommand(
      None, ['describe', 'HEAD'],
      cwd = _MyRepoPath(),
      capture_stdout = True)
    if p.Wait() == 0:
      repo_version = p.stdout
      if len(repo_version) > 0 and repo_version[-1] == '\n':
        repo_version = repo_version[0:-1]
      if len(repo_version) > 0 and repo_version[0] == 'v':
        repo_version = repo_version[1:]
    else:
      repo_version = 'unknown'

    _user_agent = 'git-repo/%s (%s) git/%s Python/%d.%d.%d' % (
      repo_version,
      os_name,
      '.'.join(map(str, git.version_tuple())),
      py_version[0], py_version[1], py_version[2])
  return _user_agent

class _UserAgentHandler(urllib.request.BaseHandler):
  def http_request(self, req):
    req.add_header('User-Agent', _UserAgent())
    return req

  def https_request(self, req):
    req.add_header('User-Agent', _UserAgent())
    return req

def _AddPasswordFromUserInput(handler, msg, req):
  # If repo could not find auth info from netrc, try to get it from user input
  url = req.get_full_url()
  user, password = handler.passwd.find_user_password(None, url)
  if user is None:
    print(msg)
    try:
      user = input('User: ')
      password = getpass.getpass()
    except KeyboardInterrupt:
      return
    handler.passwd.add_password(None, url, user, password)

class _BasicAuthHandler(urllib.request.HTTPBasicAuthHandler):
  def http_error_401(self, req, fp, code, msg, headers):
    _AddPasswordFromUserInput(self, msg, req)
    return urllib.request.HTTPBasicAuthHandler.http_error_401(
      self, req, fp, code, msg, headers)

  def http_error_auth_reqed(self, authreq, host, req, headers):
    try:
      old_add_header = req.add_header
      def _add_header(name, val):
        val = val.replace('\n', '')
        old_add_header(name, val)
      req.add_header = _add_header
      return urllib.request.AbstractBasicAuthHandler.http_error_auth_reqed(
        self, authreq, host, req, headers)
    except:
      reset = getattr(self, 'reset_retry_count', None)
      if reset is not None:
        reset()
      elif getattr(self, 'retried', None):
        self.retried = 0
      raise

class _DigestAuthHandler(urllib.request.HTTPDigestAuthHandler):
  def http_error_401(self, req, fp, code, msg, headers):
    _AddPasswordFromUserInput(self, msg, req)
    return urllib.request.HTTPDigestAuthHandler.http_error_401(
      self, req, fp, code, msg, headers)

  def http_error_auth_reqed(self, auth_header, host, req, headers):
    try:
      old_add_header = req.add_header
      def _add_header(name, val):
        val = val.replace('\n', '')
        old_add_header(name, val)
      req.add_header = _add_header
      return urllib.request.AbstractDigestAuthHandler.http_error_auth_reqed(
        self, auth_header, host, req, headers)
    except:
      reset = getattr(self, 'reset_retry_count', None)
      if reset is not None:
        reset()
      elif getattr(self, 'retried', None):
        self.retried = 0
      raise

class _KerberosAuthHandler(urllib.request.BaseHandler):
  def __init__(self):
    self.retried = 0
    self.context = None
    self.handler_order = urllib.request.BaseHandler.handler_order - 50

  def http_error_401(self, req, fp, code, msg, headers): # pylint:disable=unused-argument
    host = req.get_host()
    retry = self.http_error_auth_reqed('www-authenticate', host, req, headers)
    return retry

  def http_error_auth_reqed(self, auth_header, host, req, headers):
    try:
      spn = "HTTP@%s" % host
      authdata = self._negotiate_get_authdata(auth_header, headers)

      if self.retried > 3:
        raise urllib.request.HTTPError(req.get_full_url(), 401,
          "Negotiate auth failed", headers, None)
      else:
        self.retried += 1

      neghdr = self._negotiate_get_svctk(spn, authdata)
      if neghdr is None:
        return None

      req.add_unredirected_header('Authorization', neghdr)
      response = self.parent.open(req)

      srvauth = self._negotiate_get_authdata(auth_header, response.info())
      if self._validate_response(srvauth):
        return response
    except kerberos.GSSError:
      return None
    except:
      self.reset_retry_count()
      raise
    finally:
      self._clean_context()

  def reset_retry_count(self):
    self.retried = 0

  def _negotiate_get_authdata(self, auth_header, headers):
    authhdr = headers.get(auth_header, None)
    if authhdr is not None:
      for mech_tuple in authhdr.split(","):
        mech, __, authdata = mech_tuple.strip().partition(" ")
        if mech.lower() == "negotiate":
          return authdata.strip()
    return None

  def _negotiate_get_svctk(self, spn, authdata):
    if authdata is None:
      return None

    result, self.context = kerberos.authGSSClientInit(spn)
    if result < kerberos.AUTH_GSS_COMPLETE:
      return None

    result = kerberos.authGSSClientStep(self.context, authdata)
    if result < kerberos.AUTH_GSS_CONTINUE:
      return None

    response = kerberos.authGSSClientResponse(self.context)
    return "Negotiate %s" % response

  def _validate_response(self, authdata):
    if authdata is None:
      return None
    result = kerberos.authGSSClientStep(self.context, authdata)
    if result == kerberos.AUTH_GSS_COMPLETE:
      return True
    return None

  def _clean_context(self):
    if self.context is not None:
      kerberos.authGSSClientClean(self.context)
      self.context = None

def init_http():
  handlers = [_UserAgentHandler()]

  mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
  try:
    n = netrc.netrc()
    for host in n.hosts:
      p = n.hosts[host]
      mgr.add_password(p[1], 'http://%s/'  % host, p[0], p[2])
      mgr.add_password(p[1], 'https://%s/' % host, p[0], p[2])
  except netrc.NetrcParseError:
    pass
  except IOError:
    pass
  handlers.append(_BasicAuthHandler(mgr))
  handlers.append(_DigestAuthHandler(mgr))
  if kerberos:
    handlers.append(_KerberosAuthHandler())

  if 'http_proxy' in os.environ:
    url = os.environ['http_proxy']
    handlers.append(urllib.request.ProxyHandler({'http': url, 'https': url}))
  if 'REPO_CURL_VERBOSE' in os.environ:
    handlers.append(urllib.request.HTTPHandler(debuglevel=1))
    handlers.append(urllib.request.HTTPSHandler(debuglevel=1))
  urllib.request.install_opener(urllib.request.build_opener(*handlers))

def _Main(argv):
  result = 0

  opt = optparse.OptionParser(usage="repo wrapperinfo -- ...")
  opt.add_option("--repo-dir", dest="repodir",
                 help="path to .repo/")
  opt.add_option("--wrapper-version", dest="wrapper_version",
                 help="version of the wrapper script")
  opt.add_option("--wrapper-path", dest="wrapper_path",
                 help="location of the wrapper script")
  _PruneOptions(argv, opt)
  opt, argv = opt.parse_args(argv)

  _CheckWrapperVersion(opt.wrapper_version, opt.wrapper_path)
  _CheckRepoDir(opt.repodir)

  Version.wrapper_version = opt.wrapper_version
  Version.wrapper_path = opt.wrapper_path

  repo = _Repo(opt.repodir)
  try:
    try:
      init_ssh()
      init_http()
      result = repo._Run(argv) or 0
    finally:
      close_ssh()
  except KeyboardInterrupt:
    print('aborted by user', file=sys.stderr)
    result = 1
  except ManifestParseError as mpe:
    print('fatal: %s' % mpe, file=sys.stderr)
    result = 1
  except RepoChangedException as rce:
    # If repo changed, re-exec ourselves.
    #
    argv = list(sys.argv)
    argv.extend(rce.extra_args)
    try:
      # os.execv(__file__, argv)
      result = subprocess.call([sys.executable] + argv)
    except OSError as e:
      print('fatal: cannot restart repo after upgrade', file=sys.stderr)
      print('fatal: %s' % e, file=sys.stderr)
      result = 128

  portable.WaitForProcess()
  sys.exit(result)

if __name__ == '__main__':
  _Main(sys.argv[1:])
