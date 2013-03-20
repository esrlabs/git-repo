'''
Created on 12.03.2013

@author: mputz
'''

import os
import platform
import subprocess

SYNC_REPO_PROGRAM = False

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
    dst = toUnixPath(dst)
    #subprocess.call(["ln", "-s", src, dst])
    # ln in MinGW does not create hard links? - it copies
    if os.path.isdir(src):
      src = toWindowsPath(src)
      dst = toWindowsPath(dst)
      # symlink does create soft links in windows for directories => use mklink
      # call windows cmd tool 'mklink' from git bash (mingw)
      p = subprocess.Popen('cmd /c mklink /J %s %s' % (dst, src))
      p.communicate()
    else:
      # requires paths in relation to current dir (not in relation to target file)
      src = toUnixPath(src)
      os.link(src, dst)