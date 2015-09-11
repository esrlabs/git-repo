import os
import platform

def isUnix():
  return platform.system() != "Windows"

def to_windows_path(path):
  return path.replace('/', '\\')
