import os
import pager
import platform
import socket
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
      self.client_socket.close()
      self.server_socket.close()

  def fileno(self):
    return self.server_socket.fileno()


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
