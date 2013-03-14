'''
Created on 12.03.2013

@author: mputz
'''

import os
import platform
import subprocess

def isLinux():
  if platform.system() == "Windows":
    return False
  else:
    return True

def pathToLinux(path):
  return path.replace('\\', '/')
def pathToWindows(path):
  return path.replace('/', '\\')


def os_link(src, dst):
  if isLinux():
    # requires src in relation to dst
    src = os.path.relpath(src, os.path.dirname(dst))
    os.symlink(src, dst)
  else:
    dst = pathToLinux(dst)
    #subprocess.call(["ln", "-s", src, dst])
    # ln in MinGW does not create hard links? - it copies
    if os.path.isdir(src):
      src = pathToWindows(src)
      dst = pathToWindows(dst)
      # symlink does create soft links in windows for directories => use mklink
      # call windows cmd tool 'mklink' from git bash (mingw)
      subprocess.Popen('cmd /c mklink /J %s %s' % (dst, src))
    else:
      # requires paths in relation to current dir (not in relation to target file)
      src = pathToLinux(src)
      os.link(src, dst)