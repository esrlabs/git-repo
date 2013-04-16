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


import getpass
import imp
import netrc
import optparse
import os
import subprocess
import sys
import traceback
import time
import urllib.request
import signal
import portable
from repo_trace import SetTrace
from git_command import git, GitCommand
from git_config import init_ssh, close_ssh
from command import InteractiveCommand
from command import MirrorSafeCommand
from subcmds.version import Version
from editor import Editor
from error import DownloadError
from error import ManifestInvalidRevisionError
from error import ManifestParseError
from error import NoManifestException
from error import NoSuchProjectError
from error import RepoChangedException
from manifest_xml import XmlManifest
from pager import RunPager
from pager import _SelectPager

from subcmds import all_commands

from repo_trace import REPO_TRACE, IsTrace, Trace


global_options = optparse.OptionParser(
    usage="repo [-p|--paginate|--no-pager|--piped-into-less|--debug|--debug-host|--debug-env] COMMAND [ARGS]")
global_options.add_option('-p', '--paginate',
                          dest='pager', action='store_true',
                          help='display command output in the pager')
global_options.add_option('--no-pager',
                          dest='no_pager', action='store_true',
                          help='disable the pager')
global_options.add_option('--trace',
                          dest='trace', action='store_true',
                          help='trace git command execution')
global_options.add_option('--time',
                          dest='time', action='store_true',
                          help='time repo command execution')
global_options.add_option('--version',
                          dest='show_version', action='store_true',
                          help='display this version of repo')
global_options.add_option("--piped-into-pager", action="store_true", dest="pipedIntoPager", default=False)
global_options.add_option("--debug", action="store_true", dest="debug", default=False)
global_options.add_option("--debug-host", dest="debug_host", default='localhost')
global_options.add_option("--debug-env", dest="debug_env", default="intellij")


def _UsePager(name, cmd, gopts, copts):
    if not gopts.no_pager and not isinstance(cmd, InteractiveCommand):
        config = cmd.manifest.globalConfig
        if gopts.pager:
            use_pager = True
        else:
            use_pager = config.GetBoolean('pager.%s' % name)
            if use_pager is None:
                use_pager = cmd.WantPager(copts)
        return use_pager
    else:
        return False


class _Repo(object):
    def __init__(self, repodir):
        self.repodir = repodir
        self.commands = all_commands
        # add 'branch' as an alias for 'branches'
        all_commands['branch'] = all_commands['branches']

    def _Config(self, argv):
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

        try:
            cmd = self.commands[name]
        except KeyError:
            print("repo: '%s' is not a repo command.  See 'repo help'." % name,
                  file=sys.stderr)
            return 1

        cmd.repodir = self.repodir
        cmd.manifest = XmlManifest(cmd.repodir)
        Editor.globalConfig = cmd.manifest.globalConfig

        if not isinstance(cmd, MirrorSafeCommand) and cmd.manifest.IsMirror:
            print("fatal: '%s' requires a working directory" % name,
                  file=sys.stderr)
            return 1

        copts, cargs = cmd.OptionParser.parse_args(argv)
        copts = cmd.ReadEnvironmentOptions(copts)

        self.config = name, cmd, gopts, _gargs, copts, cargs, argv
        return 0

    def _Run(self):
        if self.config:
            (name, cmd, gopts, _gargs, copts, cargs, argv) = self.config
        else:
            print("repo was not configured, run _Config(argv) before calling _Run(..)")
            return 1

        if _UsePager(name, cmd, gopts, copts):
            config = cmd.manifest.globalConfig
            RunPager(config)

        start = time.time()
        try:
            result = cmd.Execute(copts, cargs)
        except DownloadError as e:
            print('error: DownloadError: %s' % str(e), file=sys.stderr)
            result = 1
        except ManifestInvalidRevisionError as e:
            print('error: ManifestInvalidRevisionError: %s' % str(e), file=sys.stderr)
            result = 1
        except NoManifestException as e:
            print('error: manifest required for this command -- please run init',
                  file=sys.stderr)
            result = 1
        except NoSuchProjectError as e:
            if e.name:
                print('error: project %s not found' % e.name, file=sys.stderr)
            else:
                print('error: no project in current directory', file=sys.stderr)
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


def _MyWrapperPath():
    return os.path.join(os.path.dirname(__file__), 'repo')


_wrapper_module = None


def WrapperModule():
    global _wrapper_module
    if not _wrapper_module:
        _wrapper_module = imp.load_source('wrapper', _MyWrapperPath())
    return _wrapper_module


def _CurrentWrapperVersion():
    return WrapperModule().VERSION


def _CheckWrapperVersion(ver, repo_path):
    if not repo_path:
        repo_path = '~/bin/repo'

    if not ver:
        print('no --wrapper-version argument', file=sys.stderr)
        sys.exit(1)

    exp = _CurrentWrapperVersion()
    ver = tuple(map(int, ver.split('.')))
    if len(ver) == 1:
        ver = (0, ver[0])

    exp_str = '.'.join(map(str, exp))
    if exp[0] > ver[0] or ver < (0, 4):
        print("""
!!! A new repo command (%5s) is available.    !!!
!!! You must upgrade before you can continue:   !!!

    cp %s %s
""" % (exp_str, _MyWrapperPath(), repo_path), file=sys.stderr)
        sys.exit(1)

    if exp > ver:
        print("""
... A new repo command (%5s) is available.
... You should upgrade soon:

    cp %s %s
""" % (exp_str, _MyWrapperPath(), repo_path), file=sys.stderr)


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
            cwd=_MyRepoPath(),
            capture_stdout=True)
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
            user = eval(input('User: '))
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


def init_http():
    handlers = [_UserAgentHandler()]

    mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    try:
        n = netrc.netrc()
        for host in n.hosts:
            p = n.hosts[host]
            mgr.add_password(p[1], 'http://%s/' % host, p[0], p[2])
            mgr.add_password(p[1], 'https://%s/' % host, p[0], p[2])
    except netrc.NetrcParseError:
        pass
    except IOError:
        pass
    handlers.append(_BasicAuthHandler(mgr))
    handlers.append(_DigestAuthHandler(mgr))

    if 'http_proxy' in os.environ:
        url = os.environ['http_proxy']
        handlers.append(urllib.request.ProxyHandler({'http': url, 'https': url}))
    if 'REPO_CURL_VERBOSE' in os.environ:
        handlers.append(urllib.request.HTTPHandler(debuglevel=1))
        handlers.append(urllib.request.HTTPSHandler(debuglevel=1))
    urllib.request.install_opener(urllib.request.build_opener(*handlers))


def _Debug(host, env):
    try:
        if env == "eclipse":
            if portable.isUnix():
                sys.path.append("/opt/eclipseCPy/plugins/org.python.pydev_2.7.1.2012100913/pysrc")
            else:
                sys.path.append("C:\Program Files\eclipsePython\plugins\org.python.pydev_2.7.1.2012100913\pysrc")
            import pydevd as pydevd
        elif env == "intellij":
            if portable.isUnix():
                sys.path.append("/home/mputz/.IntelliJIdea12/config/plugins/python/helpers/pydev")
                sys.path.append("/home/mputz/.IntelliJIdea12/config/plugins/python/pycharm-debug-py3k.egg")
            else:
                sys.path.append("C:\\Users\mputz\.IntelliJIdea12\config\plugins\python\pycharm-debug-py3k.egg")
                sys.path.append("C:\\Users\mputz\.IntelliJIdea12\config\plugins\python\helpers\pydev")
            import pydevd as pydevd

        pydevd.settrace(host, port=19499, stdoutToServer=True, stderrToServer=True)
        print("hey")

    except ImportError:
        traceback.print_exc(file=sys.stdout)
        sys.stderr.write("Error: you must add pydevd in a pysrc folder (e.g. in eclipse plugin) to your PYTHONPATH.\n")
        sys.exit(1)

# If program runs in Windows and a Pager is required, fork has to circumvented:
# make a system call of the current script with the additional parameter '--no-pager' and
# append a pipe for the pager, e.g. '| less'
def _WindowsPager(repo):
    (name, cmd, gopts, _gargs, copts, cargs, argv) = repo.config
    if _UsePager(name, cmd, gopts, copts):
        python = sys.executable
        thisScript = os.path.abspath(__file__)

        args = sys.argv[1:]
        argsSplit = args.index('--')
        args1 = args[:argsSplit]
        args2 = args[argsSplit + 1:]
        pager = _SelectPager(cmd.manifest.globalConfig)
        shellCommand = [python, thisScript] + args1 + ['--', '--piped-into-pager', '--no-pager'] + args2 + ['|', pager]
        if IsTrace():
            Trace(' '.join(shellCommand))
        subprocess.call(shellCommand, shell=True)
        return True
    else:
        # set global variable if output is piped into pager; means that pager is simulated, this
        # leads to correct coloring in windows
        import pager

        pager.active = gopts.pipedIntoPager

        return False


def _Main(argv):
    result = 0

    signal.signal(signal.SIGTERM, portable.terminateHandle)

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
    repo._Config(argv)

    gopts = repo.config[2]
    if gopts.debug:
        if portable.isPosix():
            # deactivate pager on posix systems since forked process cant be debugged
            os.environ['GIT_PAGER'] = ''

    # intercept here if on Windows and Pager is required
    if not portable.isPosix():
        if _WindowsPager(repo):
            # everything was already done; so exit
            return 0

    if gopts.debug:
        print("enter debug mode, host %s" % gopts.debug_host)
        _Debug(gopts.debug_host, gopts.debug_env)
        print("done debugging?")

    try:
        try:
            init_ssh()
            init_http()
            result = repo._Run() or 0
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
        argv = [sys.executable] + argv
        try:
            argv.insert(0, __file__)
            subprocess.call(argv)
        except OSError as e:
            print('fatal: cannot restart repo after upgrade', file=sys.stderr)
            print('fatal: %s' % e, file=sys.stderr)
            result = 128

    return result


if __name__ == '__main__':
    result = _Main(sys.argv[1:])
    sys.exit(result)
