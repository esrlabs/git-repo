'''
Created on 12.03.2013

@author: mputz
'''

import os
import platform
import subprocess
import sys
import stat

from repo_trace import REPO_TRACE, IsTrace, Trace

SYNC_REPO_PROGRAM = False
SUBPROCESSES = []

def terminateHandle(signal, frame):
  for cmd in SUBPROCESSES:
    if cmd:
      cmd.terminate()
  sys.exit(0)

def stream2str(stream):
  return str(stream, encoding='UTF-8')

def isUnix():
  if platform.system() == "Windows":
    return False
  else:
    return True

def isPosix():
  return platform.system() != "Windows"


def toUnixPath(path):
  return path.replace('\\', '/')

def toWindowsPath(path):
  return path.replace('/', '\\')


def os_link(src, dst):
  if isUnix():
    # requires src in relation to dst
    src = os.path.relpath(src, os.path.dirname(dst))
    os.symlink(src, dst)
  else:
    isDir = True if os.path.isdir(src) else False
    src = os.path.relpath(src, os.path.dirname(dst))
    src = toWindowsPath(src)
    dst = toWindowsPath(dst)
    # ln in MinGW does not create hard links? - it copies
    # call windows cmd tool 'mklink' from git bash (mingw)
    if isDir:
      cmd = 'cmd /c mklink /D "%s" "%s"' % (dst, src)
      if IsTrace():
        Trace(cmd)
      subprocess.Popen(cmd, stdout=subprocess.PIPE)
    else:
      cmd = 'cmd /c mklink "%s" "%s"' % (dst, src)
      if IsTrace():
        Trace(cmd)
      subprocess.Popen(cmd, stdout=subprocess.PIPE)

def removeReadOnlyFilesHandler(fn, path, excinfo):
    removeReadOnlyFiles(fn, path)

def removeReadOnlyFiles(fn, path):
    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWUSR)
        fn(path)
    else:
        raise Exception("Could not delete %s" % path)