#
# Copyright (C) 2014 The Android Open Source Project
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

from color import Coloring
from command import PagedCommand
from manifest_xml import XmlManifest

class _Coloring(Coloring):
  def __init__(self, config):
    Coloring.__init__(self, config, "status")

class Diffmanifests(PagedCommand):
  """ A command to see logs in projects represented by manifests

  This is used to see deeper differences between manifests. Where a simple
  diff would only show a diff of sha1s for example, this command will display
  the logs of the project between both sha1s, allowing user to see diff at a
  deeper level.
  """

  common = True
  helpSummary = "Manifest diff utility"
  helpUsage = """%prog manifest1.xml [manifest2.xml] [options]"""

  helpDescription = """
The %prog command shows differences between project revisions of manifest1 and
manifest2. if manifest2 is not specified, current manifest.xml will be used
instead. Both absolute and relative paths may be used for manifests. Relative
paths start from project's ".repo/manifests" folder.

The --raw option Displays the diff in a way that facilitates parsing, the
project pattern will be <status> <path> <revision from> [<revision to>] and the
commit pattern will be <status> <onelined log> with status values respectively :

  A = Added project
  R = Removed project
  C = Changed project
  U = Project with unreachable revision(s) (revision(s) not found)

for project, and

   A = Added commit
   R = Removed commit

for a commit.

Only changed projects may contain commits, and commit status always starts with
a space, and are part of last printed project.
Unreachable revisions may occur if project is not up to date or if repo has not
been initialized with all the groups, in which case some projects won't be
synced and their revisions won't be found.

"""

  def _Options(self, p):
    p.add_option('--raw',
                 dest='raw', action='store_true',
                 help='Display raw diff.')
    p.add_option('--no-color',
                 dest='color', action='store_false', default=True,
                 help='does not display the diff in color.')
    p.add_option('--pretty-format',
                 dest='pretty_format', action='store',
                 metavar='<FORMAT>',
                 help='print the log using a custom git pretty format string')

  def _printRawDiff(self, diff):
    for project in diff['added']:
      self.printText("A %s %s" % (project.relpath, project.revisionExpr))
      self.out.nl()

    for project in diff['removed']:
      self.printText("R %s %s" % (project.relpath, project.revisionExpr))
      self.out.nl()

    for project, otherProject in diff['changed']:
      self.printText("C %s %s %s" % (project.relpath, project.revisionExpr,
                                     otherProject.revisionExpr))
      self.out.nl()
      self._printLogs(project, otherProject, raw=True, color=False)

    for project, otherProject in diff['unreachable']:
      self.printText("U %s %s %s" % (project.relpath, project.revisionExpr,
                                     otherProject.revisionExpr))
      self.out.nl()

  def _printDiff(self, diff, color=True, pretty_format=None):
    if diff['added']:
      self.out.nl()
      self.printText('added projects : \n')
      self.out.nl()
      for project in diff['added']:
        self.printProject('\t%s' % (project.relpath))
        self.printText(' at revision ')
        self.printRevision(project.revisionExpr)
        self.out.nl()

    if diff['removed']:
      self.out.nl()
      self.printText('removed projects : \n')
      self.out.nl()
      for project in diff['removed']:
        self.printProject('\t%s' % (project.relpath))
        self.printText(' at revision ')
        self.printRevision(project.revisionExpr)
        self.out.nl()

    if diff['changed']:
      self.out.nl()
      self.printText('changed projects : \n')
      self.out.nl()
      for project, otherProject in diff['changed']:
        self.printProject('\t%s' % (project.relpath))
        self.printText(' changed from ')
        self.printRevision(project.revisionExpr)
        self.printText(' to ')
        self.printRevision(otherProject.revisionExpr)
        self.out.nl()
        self._printLogs(project, otherProject, raw=False, color=color,
                        pretty_format=pretty_format)
        self.out.nl()

    if diff['unreachable']:
      self.out.nl()
      self.printText('projects with unreachable revisions : \n')
      self.out.nl()
      for project, otherProject in diff['unreachable']:
        self.printProject('\t%s ' % (project.relpath))
        self.printRevision(project.revisionExpr)
        self.printText(' or ')
        self.printRevision(otherProject.revisionExpr)
        self.printText(' not found')
        self.out.nl()

  def _printLogs(self, project, otherProject, raw=False, color=True,
                 pretty_format=None):

    logs = project.getAddedAndRemovedLogs(otherProject,
                                          oneline=(pretty_format is None),
                                          color=color,
                                          pretty_format=pretty_format)
    if logs['removed']:
      removedLogs = logs['removed'].split('\n')
      for log in removedLogs:
        if log.strip():
          if raw:
            self.printText(' R ' + log)
            self.out.nl()
          else:
            self.printRemoved('\t\t[-] ')
            self.printText(log)
            self.out.nl()

    if logs['added']:
      addedLogs = logs['added'].split('\n')
      for log in addedLogs:
        if log.strip():
          if raw:
            self.printText(' A ' + log)
            self.out.nl()
          else:
            self.printAdded('\t\t[+] ')
            self.printText(log)
            self.out.nl()

  def Execute(self, opt, args):
    if not args or len(args) > 2:
      self.Usage()

    self.out = _Coloring(self.manifest.globalConfig)
    self.printText = self.out.nofmt_printer('text')
    if opt.color:
      self.printProject = self.out.nofmt_printer('project', attr = 'bold')
      self.printAdded = self.out.nofmt_printer('green', fg = 'green', attr = 'bold')
      self.printRemoved = self.out.nofmt_printer('red', fg = 'red', attr = 'bold')
      self.printRevision = self.out.nofmt_printer('revision', fg = 'yellow')
    else:
      self.printProject = self.printAdded = self.printRemoved = self.printRevision = self.printText

    manifest1 = XmlManifest(self.manifest.repodir)
    manifest1.Override(args[0])
    if len(args) == 1:
      manifest2 = self.manifest
    else:
      manifest2 = XmlManifest(self.manifest.repodir)
      manifest2.Override(args[1])

    diff = manifest1.projectsDiff(manifest2)
    if opt.raw:
      self._printRawDiff(diff)
    else:
      self._printDiff(diff, color=opt.color, pretty_format=opt.pretty_format)
