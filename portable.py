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
    os.symlink(os.path.relpath(src, os.path.dirname(dst)), dst)
  else:
    dst = pathToLinux(dst)
    #subprocess.call(["ln", "-s", src, dst])
    # ln in MinGW does not create hard links? - it copies
    # python internal link
    if os.path.isdir(src):
      src = os.path.relpath(src, os.path.dirname(dst))
      src = pathToWindows(src)
      # symlink does create soft links in windows for directories
      #os.symlink(src, dst, True)
      # call windows cmd tool 'mklink' from git bash (mingw)
      subprocess.Popen('cmd /c mklink /J %s %s' % (dst, src))
    else:
      src = pathToLinux(src)
      os.link(src, dst)