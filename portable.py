import git_config
import os
import pager
import platform
import re
import shutil
import socket
import stat
import sys
import subprocess
import threading
from trace import Trace

def isUnix():
  return platform.system() != "Windows"

if isUnix():
  import fcntl

def to_windows_path(path):
  return path.replace('/', '\\')

def rmtree(path):
  shutil.rmtree(path, onerror=onerror)

def rename(src, dst):
  if isUnix():
    os.rename(src, dst)
  else:
    if os.path.exists(dst):
      os.remove(dst)
    os.rename(src, dst)

def onerror(function, path, excinfo):
  if not os.access(path, os.W_OK):
    os.chmod(path, stat.S_IWUSR)
    function(path)
  else:
    raise


def input_reader(src, dest, std_name):
  if isUnix():
    return file_reader(src, dest, std_name)
  else:
    return socket_reader(src, dest, std_name)

class file_reader(object):
  """select file descriptor class"""
  def __init__(self, fd, dest, std_name):
    assert std_name in ('stdout', 'stderr')
    self.fd = fd
    self.dest = dest
    self.std_name = std_name
    self.setup_fd()

  def setup_fd(self):
    flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
    fcntl.fcntl(self.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

  def fileno(self):
    return self.fd.fileno()

  def read(self, bufsize):
    return self.fd.read(bufsize)

  def close(self):
    return self.fd.close()

  def src(self):
    return self.fd

class socket_reader():
  """select socket with file descriptor class"""
  def __init__(self, src, dest, std_name=''):
    self.src = src
    self.dest = dest
    self.std_name = std_name
    self.completed = False

    self.host = "localhost"
    self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.server_socket.bind((self.host, 0))
    self.server_socket.setblocking(0)
    self.port = self.server_socket.getsockname()[1]

    address = (self.host, self.port)
    self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.client_socket.connect(address)
    t = threading.Thread(target=self.send_msg, args=(self.src, self.client_socket, address))
    t.start()

  def send_msg(self, src, dest, address):
    while True:
      data = src.read(4096)
      if data:
        dest.sendto(data, address)
      else:
        break
    dest.sendto("", address)

  def read(self, bufsize):
    try:
      return self.server_socket.recv(bufsize)
    except Exception as e:
      Trace("failed to read from server socket: " + e.strerror)
      self.close()

  def close(self):
    if self.client_socket:
      self.client_socket.close()
    if self.server_socket:
      self.server_socket.close()

  def fileno(self):
    return self.server_socket.fileno()

  def src(self):
    return self.src


def os_symlink(src, dst):
  if isUnix():
    os.symlink(src, dst)
  else:
    windows_symlink(src, dst)

def windows_symlink(src, dst):
  globalConfig = git_config.GitConfig.ForUser()

  src = to_windows_path(src)
  dst = to_windows_path(dst)
  is_dir = True if os.path.isdir(os.path.realpath(os.path.join(os.path.dirname(dst), src))) else False

  no_symlinks = globalConfig.GetBoolean("portable.windowsNoSymlinks")
  if no_symlinks is None or no_symlinks == False:
    symlink_options_dir = '/D'
    symlink_options_file = ''
  else:
    src = os.path.abspath(os.path.join(os.path.dirname(dst), src))
    Trace("Using no symlinks for %s from %s to %s", "dir" if is_dir else "file", src, dst)
    symlink_options_dir = '/J'
    symlink_options_file = '/H'

  if is_dir:
    cmd = ['cmd', '/c', 'mklink', symlink_options_dir, dst, src]
    cmd = filter(len, cmd)
    Trace(' '.join(cmd))
    try:
      subprocess.Popen(cmd, stdout=subprocess.PIPE).wait()
    except Exception as e:
      Trace("failed to create dir symlink: %s", e.strerror)
      pass
  else:
    cmd = ['cmd', '/c', 'mklink', symlink_options_file, dst, src]
    cmd = filter(len, cmd)
    Trace(' '.join(cmd))
    try:
      subprocess.Popen(cmd, stdout=subprocess.PIPE).wait()
    except Exception as e:
      Trace("failed to create file symlink: %s", e.strerror)
      pass

def os_path_islink(path):
  if isUnix():
    os.path.islink(path)
  else:
    if get_windows_symlink(path) is not None:
      return True
    if get_windows_hardlink(path) is not None:
      return True
    return False

def os_path_realpath(file_path):
  if isUnix():
    os.path.realpath(file_path)
  else:
    if not os.path.exists(file_path):
      return file_path
    return windows_realpath(file_path)

def windows_realpath(file_path):
  symlink = file_path
  while True:
    s = get_windows_symlink(symlink)
    if s is None:
      break
    else:
      symlink = s

  hardlink = get_windows_hardlink(symlink)
  if hardlink is not None:
    return hardlink
  else:
    return symlink

def get_windows_symlink(file_path):
  if os.path.isdir(file_path):
    root = os.path.abspath(os.path.join(file_path, os.pardir))
    file_object = os.path.split(file_path)[1]
    if not file_object:
      file_object = os.path.split(os.path.split(file_object)[0])[1]
  else:
    root = os.path.dirname(file_path)
    file_object = os.path.split(file_path)[1]

  cmd = ['cmd', '/c', 'dir', '/AL', root]
  try:
    Trace(' '.join(cmd))
    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
  except:
    return None

  lines = [s.strip() for s in out.split('\n')]
  if len(lines) < 6:
    return None

  pattern = re.compile('.*<(.*)>\\s*(.*) \[(.*)\]$')
  for line in lines[5:]:
    result = pattern.match(line)
    if result:
      ftype = result.group(1)
      fname = result.group(2)
      flink = result.group(3)
      if file_object == fname:
        if ftype == 'SYMLINK' or ftype == 'SYMLINKD':
          new_path = os.path.realpath(os.path.join(os.path.dirname(file_path), flink))
          Trace("Relative link found: %s -> %s -> %s", fname, flink, new_path)
        else:
          new_path = flink
          Trace("Absolute link found: %s -> %s", fname, flink)
        return new_path
  return None

def get_windows_hardlink(file_path):
  if os.path.isdir(file_path):
    return None

  cmd = ['cmd', '/c', 'fsutil', 'hardlink', 'list', file_path]
  try:
    Trace(' '.join(cmd))
    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
  except:
    return None

  lines = [s.strip() for s in out.split('\n')]
  if len(lines) >= 2 and len(lines[1]) > 0:
    hardlink = file_path[0:2] + lines[0]
    Trace("Hard link found: %s -> %s", file_path, hardlink)
    return hardlink
  else:
    return None


child_process = None

def RunPager(cmd):
  if isUnix():
    pager.RunPager(cmd.manifest.globalConfig)
  else:
    RunWindowsPager(cmd)

def RunWindowsPager(cmd):
  executable = pager._SelectPager(cmd.manifest.globalConfig)
  redirect_all(executable)
  pager.active = True

def NoPager(cmd):
  if not isUnix():
    RunWindowsShell(cmd)

def RunWindowsShell(cmd):
  executable = _SelectCatenate(cmd.manifest.globalConfig)
  redirect_all(executable)

def redirect_all(executable):
  old_sysin = sys.stdin
  old_sysout = sys.stdout
  old_syserr = sys.stderr
  Trace("redirecting to %s" % executable)
  p = subprocess.Popen([executable], stdin=subprocess.PIPE, stdout=old_sysout, stderr=old_syserr)
  sys.stdout = p.stdin
  sys.stderr = p.stdin
  old_sysout.close()
  global child_process
  child_process = p

def _SelectCatenate(globalConfig):
  try:
    return os.environ['GIT_CATENATE']
  except KeyError:
    pass

  pager = globalConfig.GetString('core.catenate')
  if pager:
    return pager

  try:
    return os.environ['CATENATE']
  except KeyError:
    pass

  return 'cat'

def WaitForProcess():
  if not isUnix():
    global child_process
    if child_process:
      child_process.stdin.close()
      child_process.wait()


def prepare_editor_args(editor):
  if isUnix():
    args = [editor + ' "$@"', 'sh']
    shell = True
  else:
    editor = re.sub('["\']', '', editor)
    args = editor.rsplit()
    shell = False
  return (args, shell)


def os_chmod(dest, mode):
  if isUnix():
    os.chmod(dest, mode)
