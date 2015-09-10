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

from command import PagedCommand

try:
  import threading as _threading
except ImportError:
  import dummy_threading as _threading

import glob

import itertools
import os

from color import Coloring

class Status(PagedCommand):
  common = True
  helpSummary = "Show the working tree status"
  helpUsage = """
%prog [<project>...]
"""
  helpDescription = """
'%prog' compares the working tree to the staging area (aka index),
and the most recent commit on this branch (HEAD), in each project
specified.  A summary is displayed, one line per file where there
is a difference between these three states.

The -j/--jobs option can be used to run multiple status queries
in parallel.

The -o/--orphans option can be used to show objects that are in
the working directory, but not associated with a repo project.
This includes unmanaged top-level files and directories, but also
includes deeper items.  For example, if dir/subdir/proj1 and
dir/subdir/proj2 are repo projects, dir/subdir/proj3 will be shown
if it is not known to repo.

Status Display
--------------

The status display is organized into three columns of information,
for example if the file 'subcmds/status.py' is modified in the
project 'repo' on branch 'devwork':

  project repo/                                   branch devwork
   -m     subcmds/status.py

The first column explains how the staging area (index) differs from
the last commit (HEAD).  Its values are always displayed in upper
case and have the following meanings:

 -:  no difference
 A:  added         (not in HEAD,     in index                     )
 M:  modified      (    in HEAD,     in index, different content  )
 D:  deleted       (    in HEAD, not in index                     )
 R:  renamed       (not in HEAD,     in index, path changed       )
 C:  copied        (not in HEAD,     in index, copied from another)
 T:  mode changed  (    in HEAD,     in index, same content       )
 U:  unmerged; conflict resolution required

The second column explains how the working directory differs from
the index.  Its values are always displayed in lower case and have
the following meanings:

 -:  new / unknown (not in index,     in work tree                )
 m:  modified      (    in index,     in work tree, modified      )
 d:  deleted       (    in index, not in work tree                )

"""

  def _Options(self, p):
    p.add_option('-j', '--jobs',
                 dest='jobs', action='store', type='int', default=2,
                 help="number of projects to check simultaneously")
    p.add_option('-o', '--orphans',
                 dest='orphans', action='store_true',
                 help="include objects in working directory outside of repo projects")

  def _StatusHelper(self, project, clean_counter, sem):
    """Obtains the status for a specific project.

    Obtains the status for a project, redirecting the output to
    the specified object. It will release the semaphore
    when done.

    Args:
      project: Project to get status of.
      clean_counter: Counter for clean projects.
      sem: Semaphore, will call release() when complete.
      output: Where to output the status.
    """
    try:
      state = project.PrintWorkTreeStatus()
      if state == 'CLEAN':
        next(clean_counter)
    finally:
      sem.release()

  def _FindOrphans(self, dirs, proj_dirs, proj_dirs_parents, outstring):
    """find 'dirs' that are present in 'proj_dirs_parents' but not in 'proj_dirs'"""
    status_header = ' --\t'
    for item in dirs:
      if not os.path.isdir(item):
        outstring.append(''.join([status_header, item]))
        continue
      if item in proj_dirs:
        continue
      if item in proj_dirs_parents:
        self._FindOrphans(glob.glob('%s/.*' % item) +
            glob.glob('%s/*' % item),
            proj_dirs, proj_dirs_parents, outstring)
        continue
      outstring.append(''.join([status_header, item, '/']))

  def Execute(self, opt, args):
    all_projects = self.GetProjects(args)
    counter = itertools.count()

    if opt.jobs == 1:
      for project in all_projects:
        state = project.PrintWorkTreeStatus()
        if state == 'CLEAN':
          next(counter)
    else:
      sem = _threading.Semaphore(opt.jobs)
      threads = []
      for project in all_projects:
        sem.acquire()

        t = _threading.Thread(target=self._StatusHelper,
                              args=(project, counter, sem))
        threads.append(t)
        t.daemon = True
        t.start()
      for t in threads:
        t.join()
    if len(all_projects) == next(counter):
      print('nothing to commit (working directory clean)')

    if opt.orphans:
      proj_dirs = set()
      proj_dirs_parents = set()
      for project in self.GetProjects(None, missing_ok=True):
        proj_dirs.add(project.relpath)
        (head, _tail) = os.path.split(project.relpath)
        while head != "":
          proj_dirs_parents.add(head)
          (head, _tail) = os.path.split(head)
      proj_dirs.add('.repo')

      class StatusColoring(Coloring):
        def __init__(self, config):
          Coloring.__init__(self, config, 'status')
          self.project = self.printer('header', attr = 'bold')
          self.untracked = self.printer('untracked', fg = 'red')

      orig_path = os.getcwd()
      try:
        os.chdir(self.manifest.topdir)

        outstring = []
        self._FindOrphans(glob.glob('.*') +
            glob.glob('*'),
            proj_dirs, proj_dirs_parents, outstring)

        if outstring:
          output = StatusColoring(self.manifest.globalConfig)
          output.project('Objects not within a project (orphans)')
          output.nl()
          for entry in outstring:
            output.untracked(entry)
            output.nl()
        else:
          print('No orphan files or directories')

      finally:
        # Restore CWD.
        os.chdir(orig_path)
