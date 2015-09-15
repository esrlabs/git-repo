#!/usr/bin/env python

from __future__ import print_function
import optparse
import os
import platform
import random
import subprocess
import sys
import time
from optparse import OptionParser

if not sys.version_info[0] == 3:
  # pylint:disable=W0622
  input = raw_input
  # pylint:enable=W0622

def isUnix():
  return platform.system() != "Windows"

child_process = None

def redirect_all(executable):
  old_sysin = sys.stdin
  old_sysout = sys.stdout
  old_syserr = sys.stderr
  p = subprocess.Popen([executable], stdin=subprocess.PIPE, stdout=old_sysout, stderr=old_syserr)
  sys.stdout = p.stdin
  sys.stderr = p.stdin
  old_sysout.close()
  global child_process
  child_process = p

def WaitForProcess():
  if not isUnix():
    global child_process
    if child_process:
      child_process.stdin.close()
      child_process.wait()


def main():
  usage = "Usage: %prog [options] REPO_GIT"
  parser = OptionParser(usage)
  parser.add_option("-u", "--manifest-url",
                 dest='manifest_url',
                 help='manifest repository location', metavar='URL')
  parser.add_option("-s", "--no-sync",
                 action="store_true", dest="no_sync", default=False,
                 help="do not sync after init")
  parser.add_option("-c", "--clean",
                 action="store_true", dest="clean", default=False,
                 help="clean gits after init")
  parser.add_option("-i", "--interactive",
                 action="store_true", dest="interactive", default=False,
                 help="wait for user input after each step")
  parser.add_option("-q", "--quiet",
                 action="store_false", dest="verbose", default=True,
                 help="don't print status messages to stdout")

  (options, args) = parser.parse_args()

  repo_dir = sys.argv[1]

  env = os.environ
  if len(args) < 1:
    print("Missing REPO_GIT argument")
    exit(1)
  if options.verbose:
    env["REPO_TRACE"] = "1"

  if options.manifest_url.find('Test') < 0:
    print("Warning: aborting due to manifest url has no 'Test' substring. Make sure to create special manifest for this test util since it will not care for any git fetched!")
    exit(1)

  redirect_all('cat')

  repo = "%s/repo" % args[0]
  abs_repo = os.path.abspath(args[0])
  prefix = '# '

  def p(s=""):
    print('\033[47m\033[32m' + (prefix + s).ljust(80) + '\033[0m')

  def check_repository(min_git_count):
    dirs = filter(lambda x: not x == '.repo' and not x.find('Test') > -1, os.listdir('.'))
    if len(dirs) > 0:
      p("Warning: aborting due existing folders without 'Test' in name in repository! (folders: %s)" % (' '.join(dirs)))
      exit(1)

    dirs = filter(lambda x: not x == '.repo', os.listdir('.'))
    if len(dirs) < min_git_count:
      p("Warning: exit since not enough repositories found: required=%s, found=%s" % (min_git_count, len(dirs)))
      exit(1)


  def clean():
    dirs = filter(lambda x: not x.startswith('.') and os.path.isdir(os.path.join('.', x)), os.listdir('.'))
    for d in dirs:
      cmd = "git reset --hard"
      subprocess.call(cmd.split(), cwd="./%s" % d, env=env)
      cmd = "git clean -xfd"
      subprocess.call(cmd.split(), cwd="./%s" % d, env=env)

  def select_folder(folder_index):
    dirs = filter(lambda x: not x.startswith('.') and os.path.isdir(os.path.join('.', x)), os.listdir('.'))
    dirs = sorted(dirs)
    return dirs[folder_index]

  def repo_do(name, cmd, dry_run=False):
    print()
    p(name)

    cmd = ['python', repo] + cmd
    if options.verbose:
      p(' '.join(cmd))

    if not dry_run:
      subprocess.call(cmd, env=env)
    else:
      p("Skipping")

    if options.interactive:
      key = input("{0}{0}{1}Press any key to continue or 'q' to exit".format(os.linesep, prefix))
      if key == 'q':
        p("Exit")
        exit(1)
    else:
      time.sleep(1)

  def changeAnyFile(d):
    files = filter(lambda x: not x.startswith('.') and os.path.isfile(os.path.join(d, x)), os.listdir(d))
    f = files[0]
    fh = open('%s/%s' % (d, f), 'w')
    fh.write(str(random.random()))
    fh.close()
    p("Changing file %s in %s" % (f, d))

  def stageAllIn(d):
    cmd = "git add -u"
    subprocess.call(cmd.split(), cwd="./%s" % d, env=env)

  def commitIn(d):
    cmd = "git commit -m \"%s\"" % (str(random.random()))
    subprocess.call(cmd.split(), cwd="./%s" % d, env=env)

  def startChangeCommit(folder):
    repo_do("Start branch in folder %s" % folder, ["start", "fix", folder])
    changeAnyFile(folder)
    repo_do("Changed file in folder %s" % folder, ["status"])
    stageAllIn(folder)
    repo_do("Stage file in folder %s" % folder, ["status"])
    commitIn(folder)
    repo_do("Commit changes in folder %s" % folder, ["status"])

  repo_do("Test init", ["init", "-u", options.manifest_url, "--no-repo-verify", "--repo-url", abs_repo, "--repo-branch", "stable"])

  if options.clean:
    clean()
    repo_do("Do clean", ["status"])

  repo_do("Test sync", ["sync"], options.no_sync)
  check_repository(2)

  repo_do("Test status", ["status"])
  repo_do("Test info", ["info", "-o"])

  folder_index0 = select_folder(0)
  folder_index1 = select_folder(1)

  startChangeCommit(folder_index0)
  repo_do("Check single pushable branch", ["info", "-o"])
  repo_do("Test single push", ["push"])
  repo_do("Check nothing to push after commit", ["info", "-o"])

  startChangeCommit(folder_index0)
  startChangeCommit(folder_index1)
  repo_do("Check two pushable branches", ["info", "-o"])
  repo_do("Test multiple push with editor", ["push"])
  repo_do("Check nothing to push after commit", ["info", "-o"])
  repo_do("Check already pushed branches", ["status"])
  repo_do("Do prune", ["prune"])
  repo_do("Check prune", ["status"])

  repo_do("Test forall with env varibales", ["forall", "-c", "printenv", "REPO_PROJECT"])

  print()
  p("Done")

  WaitForProcess()

if __name__ == "__main__":
  main()
