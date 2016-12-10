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

import contextlib
import errno
import json
import os
import re
import subprocess
import sys
try:
  import threading as _threading
except ImportError:
  import dummy_threading as _threading
import time

from pyversion import is_python3
if is_python3():
  import urllib.request
  import urllib.error
else:
  import urllib2
  import imp
  urllib = imp.new_module('urllib')
  urllib.request = urllib2
  urllib.error = urllib2

from signal import SIGTERM
from error import GitError, UploadError
from trace import Trace
if is_python3():
  from http.client import HTTPException
else:
  from httplib import HTTPException

from git_command import GitCommand
from git_command import ssh_sock
from git_command import terminate_ssh_clients

R_HEADS = 'refs/heads/'
R_TAGS  = 'refs/tags/'
ID_RE = re.compile(r'^[0-9a-f]{40}$')

REVIEW_CACHE = dict()

def IsId(rev):
  return ID_RE.match(rev)

def _key(name):
  parts = name.split('.')
  if len(parts) < 2:
    return name.lower()
  parts[ 0] = parts[ 0].lower()
  parts[-1] = parts[-1].lower()
  return '.'.join(parts)

class GitConfig(object):
  _ForUser = None

  @classmethod
  def ForUser(cls):
    if cls._ForUser is None:
      cls._ForUser = cls(configfile = os.path.expanduser('~/.gitconfig'))
    return cls._ForUser

  @classmethod
  def ForRepository(cls, gitdir, defaults=None):
    return cls(configfile = os.path.join(gitdir, 'config'),
               defaults = defaults)

  def __init__(self, configfile, defaults=None, jsonFile=None):
    self.file = configfile
    self.defaults = defaults
    self._cache_dict = None
    self._section_dict = None
    self._remotes = {}
    self._branches = {}

    self._json = jsonFile
    if self._json is None:
      self._json = os.path.join(
        os.path.dirname(self.file),
        '.repo_' + os.path.basename(self.file) + '.json')

  def Has(self, name, include_defaults = True):
    """Return true if this configuration file has the key.
    """
    if _key(name) in self._cache:
      return True
    if include_defaults and self.defaults:
      return self.defaults.Has(name, include_defaults = True)
    return False

  def GetBoolean(self, name):
    """Returns a boolean from the configuration file.
       None : The value was not defined, or is not a boolean.
       True : The value was set to true or yes.
       False: The value was set to false or no.
    """
    v = self.GetString(name)
    if v is None:
      return None
    v = v.lower()
    if v in ('true', 'yes'):
      return True
    if v in ('false', 'no'):
      return False
    return None

  def GetString(self, name, all_keys=False):
    """Get the first value for a key, or None if it is not defined.

       This configuration file is used first, if the key is not
       defined or all_keys = True then the defaults are also searched.
    """
    try:
      v = self._cache[_key(name)]
    except KeyError:
      if self.defaults:
        return self.defaults.GetString(name, all_keys = all_keys)
      v = []

    if not all_keys:
      if v:
        return v[0]
      return None

    r = []
    r.extend(v)
    if self.defaults:
      r.extend(self.defaults.GetString(name, all_keys = True))
    return r

  def SetString(self, name, value):
    """Set the value(s) for a key.
       Only this configuration file is modified.

       The supplied value should be either a string,
       or a list of strings (to store multiple values).
    """
    key = _key(name)

    try:
      old = self._cache[key]
    except KeyError:
      old = []

    if value is None:
      if old:
        del self._cache[key]
        self._do('--unset-all', name)

    elif isinstance(value, list):
      if len(value) == 0:
        self.SetString(name, None)

      elif len(value) == 1:
        self.SetString(name, value[0])

      elif old != value:
        self._cache[key] = list(value)
        self._do('--replace-all', name, value[0])
        for i in range(1, len(value)):
          self._do('--add', name, value[i])

    elif len(old) != 1 or old[0] != value:
      self._cache[key] = [value]
      self._do('--replace-all', name, value)

  def GetRemote(self, name):
    """Get the remote.$name.* configuration values as an object.
    """
    try:
      r = self._remotes[name]
    except KeyError:
      r = Remote(self, name)
      self._remotes[r.name] = r
    return r

  def GetBranch(self, name):
    """Get the branch.$name.* configuration values as an object.
    """
    try:
      b = self._branches[name]
    except KeyError:
      b = Branch(self, name)
      self._branches[b.name] = b
    return b

  def GetSubSections(self, section):
    """List all subsection names matching $section.*.*
    """
    return self._sections.get(section, set())

  def HasSection(self, section, subsection = ''):
    """Does at least one key in section.subsection exist?
    """
    try:
      return subsection in self._sections[section]
    except KeyError:
      return False

  def UrlInsteadOf(self, url):
    """Resolve any url.*.insteadof references.
    """
    for new_url in self.GetSubSections('url'):
      for old_url in self.GetString('url.%s.insteadof' % new_url, True):
        if old_url is not None and url.startswith(old_url):
          return new_url + url[len(old_url):]
    return url

  @property
  def _sections(self):
    d = self._section_dict
    if d is None:
      d = {}
      for name in self._cache.keys():
        p = name.split('.')
        if 2 == len(p):
          section = p[0]
          subsect = ''
        else:
          section = p[0]
          subsect = '.'.join(p[1:-1])
        if section not in d:
          d[section] = set()
        d[section].add(subsect)
        self._section_dict = d
    return d

  @property
  def _cache(self):
    if self._cache_dict is None:
      self._cache_dict = self._Read()
    return self._cache_dict

  def _Read(self):
    d = self._ReadJson()
    if d is None:
      d = self._ReadGit()
      self._SaveJson(d)
    return d

  def _ReadJson(self):
    try:
      if os.path.getmtime(self._json) \
      <= os.path.getmtime(self.file):
        os.remove(self._json)
        return None
    except OSError:
      return None
    try:
      Trace(': parsing %s', self.file)
      fd = open(self._json)
      try:
        return json.load(fd)
      finally:
        fd.close()
    except (IOError, ValueError):
      os.remove(self._json)
      return None

  def _SaveJson(self, cache):
    try:
      fd = open(self._json, 'w')
      try:
        json.dump(cache, fd, indent=2)
      finally:
        fd.close()
    except (IOError, TypeError):
      if os.path.exists(self._json):
        os.remove(self._json)

  def _ReadGit(self):
    """
    Read configuration data from git.

    This internal method populates the GitConfig cache.

    """
    c = {}
    d = self._do('--null', '--list')
    if d is None:
      return c
    for line in d.decode('utf-8').rstrip('\0').split('\0'):  # pylint: disable=W1401
                                                             # Backslash is not anomalous
      if '\n' in line:
        key, val = line.split('\n', 1)
      else:
        key = line
        val = None

      if key in c:
        c[key].append(val)
      else:
        c[key] = [val]

    return c

  def _do(self, *args):
    command = ['config', '--file', self.file]
    command.extend(args)

    p = GitCommand(None,
                   command,
                   capture_stdout = True,
                   capture_stderr = True)
    if p.Wait() == 0:
      return p.stdout
    else:
      GitError('git config %s: %s' % (str(args), p.stderr))


class RefSpec(object):
  """A Git refspec line, split into its components:

      forced:  True if the line starts with '+'
      src:     Left side of the line
      dst:     Right side of the line
  """

  @classmethod
  def FromString(cls, rs):
    lhs, rhs = rs.split(':', 2)
    if lhs.startswith('+'):
      lhs = lhs[1:]
      forced = True
    else:
      forced = False
    return cls(forced, lhs, rhs)

  def __init__(self, forced, lhs, rhs):
    self.forced = forced
    self.src = lhs
    self.dst = rhs

  def SourceMatches(self, rev):
    if self.src:
      if rev == self.src:
        return True
      if self.src.endswith('/*') and rev.startswith(self.src[:-1]):
        return True
    return False

  def DestMatches(self, ref):
    if self.dst:
      if ref == self.dst:
        return True
      if self.dst.endswith('/*') and ref.startswith(self.dst[:-1]):
        return True
    return False

  def MapSource(self, rev):
    if self.src.endswith('/*'):
      return self.dst[:-1] + rev[len(self.src) - 1:]
    return self.dst

  def __str__(self):
    s = ''
    if self.forced:
      s += '+'
    if self.src:
      s += self.src
    if self.dst:
      s += ':'
      s += self.dst
    return s


_master_processes = []
_master_keys = set()
_ssh_master = True
_master_keys_lock = None

def init_ssh():
  """Should be called once at the start of repo to init ssh master handling.

  At the moment, all we do is to create our lock.
  """
  global _master_keys_lock
  assert _master_keys_lock is None, "Should only call init_ssh once"
  _master_keys_lock = _threading.Lock()

def _open_ssh(host, port=None):
  global _ssh_master

  # Acquire the lock.  This is needed to prevent opening multiple masters for
  # the same host when we're running "repo sync -jN" (for N > 1) _and_ the
  # manifest <remote fetch="ssh://xyz"> specifies a different host from the
  # one that was passed to repo init.
  _master_keys_lock.acquire()
  try:

    # Check to see whether we already think that the master is running; if we
    # think it's already running, return right away.
    if port is not None:
      key = '%s:%s' % (host, port)
    else:
      key = host

    if key in _master_keys:
      return True

    if not _ssh_master \
    or 'GIT_SSH' in os.environ \
    or sys.platform in ('win32', 'cygwin'):
      # failed earlier, or cygwin ssh can't do this
      #
      return False

    # We will make two calls to ssh; this is the common part of both calls.
    command_base = ['ssh',
                     '-o','ControlPath %s' % ssh_sock(),
                     host]
    if port is not None:
      command_base[1:1] = ['-p', str(port)]

    # Since the key wasn't in _master_keys, we think that master isn't running.
    # ...but before actually starting a master, we'll double-check.  This can
    # be important because we can't tell that that 'git@myhost.com' is the same
    # as 'myhost.com' where "User git" is setup in the user's ~/.ssh/config file.
    check_command = command_base + ['-O','check']
    try:
      Trace(': %s', ' '.join(check_command))
      check_process = subprocess.Popen(check_command,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
      check_process.communicate() # read output, but ignore it...
      isnt_running = check_process.wait()

      if not isnt_running:
        # Our double-check found that the master _was_ infact running.  Add to
        # the list of keys.
        _master_keys.add(key)
        return True
    except Exception:
      # Ignore excpetions.  We we will fall back to the normal command and print
      # to the log there.
      pass

    command = command_base[:1] + \
              ['-M', '-N'] + \
              command_base[1:]
    try:
      Trace(': %s', ' '.join(command))
      p = subprocess.Popen(command)
    except Exception as e:
      _ssh_master = False
      print('\nwarn: cannot enable ssh control master for %s:%s\n%s'
             % (host,port, str(e)), file=sys.stderr)
      return False

    time.sleep(1)
    ssh_died = (p.poll() is not None)
    if ssh_died:
      return False

    _master_processes.append(p)
    _master_keys.add(key)
    return True
  finally:
    _master_keys_lock.release()

def close_ssh():
  global _master_keys_lock

  terminate_ssh_clients()

  for p in _master_processes:
    try:
      os.kill(p.pid, SIGTERM)
      p.wait()
    except OSError:
      pass
  del _master_processes[:]
  _master_keys.clear()

  d = ssh_sock(create=False)
  if d:
    try:
      os.rmdir(os.path.dirname(d))
    except OSError:
      pass

  # We're done with the lock, so we can delete it.
  _master_keys_lock = None

URI_SCP = re.compile(r'^([^@:]*@?[^:/]{1,}):')
URI_ALL = re.compile(r'^([a-z][a-z+-]*)://([^@/]*@?[^/]*)/')

def GetSchemeFromUrl(url):
  m = URI_ALL.match(url)
  if m:
    return m.group(1)
  return None

@contextlib.contextmanager
def GetUrlCookieFile(url, quiet):
  if url.startswith('persistent-'):
    try:
      p = subprocess.Popen(
          ['git-remote-persistent-https', '-print_config', url],
          stdin=subprocess.PIPE, stdout=subprocess.PIPE,
          stderr=subprocess.PIPE)
      try:
        cookieprefix = 'http.cookiefile='
        proxyprefix = 'http.proxy='
        cookiefile = None
        proxy = None
        for line in p.stdout:
          line = line.strip()
          if line.startswith(cookieprefix):
            cookiefile = line[len(cookieprefix):]
          if line.startswith(proxyprefix):
            proxy = line[len(proxyprefix):]
        # Leave subprocess open, as cookie file may be transient.
        if cookiefile or proxy:
          yield cookiefile, proxy
          return
      finally:
        p.stdin.close()
        if p.wait():
          err_msg = p.stderr.read()
          if ' -print_config' in err_msg:
            pass  # Persistent proxy doesn't support -print_config.
          elif not quiet:
            print(err_msg, file=sys.stderr)
    except OSError as e:
      if e.errno == errno.ENOENT:
        pass  # No persistent proxy.
      raise
  yield GitConfig.ForUser().GetString('http.cookiefile'), None

def _preconnect(url):
  m = URI_ALL.match(url)
  if m:
    scheme = m.group(1)
    host = m.group(2)
    if ':' in host:
      host, port = host.split(':')
    else:
      port = None
    if scheme in ('ssh', 'git+ssh', 'ssh+git'):
      return _open_ssh(host, port)
    return False

  m = URI_SCP.match(url)
  if m:
    host = m.group(1)
    return _open_ssh(host)

  return False

class Remote(object):
  """Configuration options related to a remote.
  """
  def __init__(self, config, name):
    self._config = config
    self.name = name
    self.url = self._Get('url')
    self.pushUrl = self._Get('pushurl')
    self.review = self._Get('review')
    self.projectname = self._Get('projectname')
    self.fetch = list(map(RefSpec.FromString,
                      self._Get('fetch', all_keys=True)))
    self._review_url = None

  def _InsteadOf(self):
    globCfg = GitConfig.ForUser()
    urlList = globCfg.GetSubSections('url')
    longest = ""
    longestUrl = ""

    for url in urlList:
      key = "url." + url + ".insteadOf"
      insteadOfList = globCfg.GetString(key, all_keys=True)

      for insteadOf in insteadOfList:
        if self.url.startswith(insteadOf) \
        and len(insteadOf) > len(longest):
          longest = insteadOf
          longestUrl = url

    if len(longest) == 0:
      return self.url

    return self.url.replace(longest, longestUrl, 1)

  def PreConnectFetch(self):
    connectionUrl = self._InsteadOf()
    return _preconnect(connectionUrl)

  def ReviewUrl(self, userEmail):
    if self._review_url is None:
      if self.review is None:
        return None

      u = self.review
      if u.startswith('persistent-'):
        u = u[len('persistent-'):]
      if u.split(':')[0] not in ('http', 'https', 'sso', 'ssh'):
        u = 'http://%s' % u
      if u.endswith('/Gerrit'):
        u = u[:len(u) - len('/Gerrit')]
      if u.endswith('/ssh_info'):
        u = u[:len(u) - len('/ssh_info')]
      if not u.endswith('/'):
        u += '/'
      http_url = u

      if u in REVIEW_CACHE:
        self._review_url = REVIEW_CACHE[u]
      elif 'REPO_HOST_PORT_INFO' in os.environ:
        host, port = os.environ['REPO_HOST_PORT_INFO'].split()
        self._review_url = self._SshReviewUrl(userEmail, host, port)
        REVIEW_CACHE[u] = self._review_url
      elif u.startswith('sso:') or u.startswith('ssh:'):
        self._review_url = u  # Assume it's right
        REVIEW_CACHE[u] = self._review_url
      else:
        try:
          info_url = u + 'ssh_info'
          from trace import Trace
          Trace("urlopen %s" % info_url)
          try:
            info = urllib.request.urlopen(info_url).read()
          except Exception:
            info = 'NOT_AVAILABLE'

          if info == 'NOT_AVAILABLE' or '<' in info:
            # If `info` contains '<', we assume the server gave us some sort
            # of HTML response back, like maybe a login page.
            #
            # Assume HTTP if SSH is not enabled or ssh_info doesn't look right.
            self._review_url = http_url
          else:
            host, port = info.split()
            self._review_url = self._SshReviewUrl(userEmail, host, port)
        except urllib.error.HTTPError as e:
          raise UploadError('%s: %s' % (self.review, str(e)))
        except urllib.error.URLError as e:
          raise UploadError('%s: %s' % (self.review, str(e)))
        except HTTPException as e:
          raise UploadError('%s: %s' % (self.review, e.__class__.__name__))

        REVIEW_CACHE[u] = self._review_url
    return self._review_url + self.projectname

  def _SshReviewUrl(self, userEmail, host, port):
    username = self._config.GetString('review.%s.username' % self.review)
    if username is None:
      username = userEmail.split('@')[0]
    return 'ssh://%s@%s:%s/' % (username, host, port)

  def ToLocal(self, rev):
    """Convert a remote revision string to something we have locally.
    """
    if self.name == '.' or IsId(rev):
      return rev

    if not rev.startswith('refs/'):
      rev = R_HEADS + rev

    for spec in self.fetch:
      if spec.SourceMatches(rev):
        return spec.MapSource(rev)

    if not rev.startswith(R_HEADS):
      return rev

    raise GitError('remote %s does not have %s' % (self.name, rev))

  def WritesTo(self, ref):
    """True if the remote stores to the tracking ref.
    """
    for spec in self.fetch:
      if spec.DestMatches(ref):
        return True
    return False

  def ResetFetch(self, mirror=False):
    """Set the fetch refspec to its default value.
    """
    if mirror:
      dst = 'refs/heads/*'
    else:
      dst = 'refs/remotes/%s/*' % self.name
    self.fetch = [RefSpec(True, 'refs/heads/*', dst)]

  def Save(self):
    """Save this remote to the configuration.
    """
    self._Set('url', self.url)
    if self.pushUrl is not None:
      self._Set('pushurl', self.pushUrl + '/' + self.projectname)
    else:
      self._Set('pushurl', self.pushUrl)
    self._Set('review', self.review)
    self._Set('projectname', self.projectname)
    self._Set('fetch', list(map(str, self.fetch)))

  def _Set(self, key, value):
    key = 'remote.%s.%s' % (self.name, key)
    return self._config.SetString(key, value)

  def _Get(self, key, all_keys=False):
    key = 'remote.%s.%s' % (self.name, key)
    return self._config.GetString(key, all_keys = all_keys)


class Branch(object):
  """Configuration options related to a single branch.
  """
  def __init__(self, config, name):
    self._config = config
    self.name = name
    self.merge = self._Get('merge')

    r = self._Get('remote')
    if r:
      self.remote = self._config.GetRemote(r)
    else:
      self.remote = None

  @property
  def LocalMerge(self):
    """Convert the merge spec to a local name.
    """
    if self.remote and self.merge:
      return self.remote.ToLocal(self.merge)
    return None

  def Save(self):
    """Save this branch back into the configuration.
    """
    if self._config.HasSection('branch', self.name):
      if self.remote:
        self._Set('remote', self.remote.name)
      else:
        self._Set('remote', None)
      self._Set('merge', self.merge)

    else:
      fd = open(self._config.file, 'a')
      try:
        fd.write('[branch "%s"]\n' % self.name)
        if self.remote:
          fd.write('\tremote = %s\n' % self.remote.name)
        if self.merge:
          fd.write('\tmerge = %s\n' % self.merge)
      finally:
        fd.close()

  def _Set(self, key, value):
    key = 'branch.%s.%s' % (self.name, key)
    return self._config.SetString(key, value)

  def _Get(self, key, all_keys=False):
    key = 'branch.%s.%s' % (self.name, key)
    return self._config.GetString(key, all_keys = all_keys)
