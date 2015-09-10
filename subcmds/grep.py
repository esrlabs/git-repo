#
# Copyright (C) 2009 The Android Open Source Project
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

from __future__ import print_function
import sys
from color import Coloring
from command import PagedCommand
from git_command import git_require, GitCommand

class GrepColoring(Coloring):
  def __init__(self, config):
    Coloring.__init__(self, config, 'grep')
    self.project = self.printer('project', attr='bold')

class Grep(PagedCommand):
  common = True
  helpSummary = "Print lines matching a pattern"
  helpUsage = """
%prog {pattern | -e pattern} [<project>...]
"""
  helpDescription = """
Search for the specified patterns in all project files.

Boolean Options
---------------

The following options can appear as often as necessary to express
the pattern to locate:

 -e PATTERN
 --and, --or, --not, -(, -)

Further, the -r/--revision option may be specified multiple times
in order to scan multiple trees.  If the same file matches in more
than one tree, only the first result is reported, prefixed by the
revision name it was found under.

Examples
-------

Look for a line that has '#define' and either 'MAX_PATH or 'PATH_MAX':

  repo grep -e '#define' --and -\\( -e MAX_PATH -e PATH_MAX \\)

Look for a line that has 'NODE' or 'Unexpected' in files that
contain a line that matches both expressions:

  repo grep --all-match -e NODE -e Unexpected

"""

  def _Options(self, p):
    def carry(option,
              opt_str,
              value,
              parser):
      pt = getattr(parser.values, 'cmd_argv', None)
      if pt is None:
        pt = []
        setattr(parser.values, 'cmd_argv', pt)

      if opt_str == '-(':
        pt.append('(')
      elif opt_str == '-)':
        pt.append(')')
      else:
        pt.append(opt_str)

      if value is not None:
        pt.append(value)

    g = p.add_option_group('Sources')
    g.add_option('--cached',
                 action='callback', callback=carry,
                 help='Search the index, instead of the work tree')
    g.add_option('-r', '--revision',
                 dest='revision', action='append', metavar='TREEish',
                 help='Search TREEish, instead of the work tree')

    g = p.add_option_group('Pattern')
    g.add_option('-e',
                 action='callback', callback=carry,
                 metavar='PATTERN', type='str',
                 help='Pattern to search for')
    g.add_option('-i', '--ignore-case',
                 action='callback', callback=carry,
                 help='Ignore case differences')
    g.add_option('-a', '--text',
                 action='callback', callback=carry,
                 help="Process binary files as if they were text")
    g.add_option('-I',
                 action='callback', callback=carry,
                 help="Don't match the pattern in binary files")
    g.add_option('-w', '--word-regexp',
                 action='callback', callback=carry,
                 help='Match the pattern only at word boundaries')
    g.add_option('-v', '--invert-match',
                 action='callback', callback=carry,
                 help='Select non-matching lines')
    g.add_option('-G', '--basic-regexp',
                 action='callback', callback=carry,
                 help='Use POSIX basic regexp for patterns (default)')
    g.add_option('-E', '--extended-regexp',
                 action='callback', callback=carry,
                 help='Use POSIX extended regexp for patterns')
    g.add_option('-F', '--fixed-strings',
                 action='callback', callback=carry,
                 help='Use fixed strings (not regexp) for pattern')

    g = p.add_option_group('Pattern Grouping')
    g.add_option('--all-match',
                 action='callback', callback=carry,
                 help='Limit match to lines that have all patterns')
    g.add_option('--and', '--or', '--not',
                 action='callback', callback=carry,
                 help='Boolean operators to combine patterns')
    g.add_option('-(', '-)',
                 action='callback', callback=carry,
                 help='Boolean operator grouping')

    g = p.add_option_group('Output')
    g.add_option('-n',
                 action='callback', callback=carry,
                 help='Prefix the line number to matching lines')
    g.add_option('-C',
                 action='callback', callback=carry,
                 metavar='CONTEXT', type='str',
                 help='Show CONTEXT lines around match')
    g.add_option('-B',
                 action='callback', callback=carry,
                 metavar='CONTEXT', type='str',
                 help='Show CONTEXT lines before match')
    g.add_option('-A',
                 action='callback', callback=carry,
                 metavar='CONTEXT', type='str',
                 help='Show CONTEXT lines after match')
    g.add_option('-l', '--name-only', '--files-with-matches',
                 action='callback', callback=carry,
                 help='Show only file names containing matching lines')
    g.add_option('-L', '--files-without-match',
                 action='callback', callback=carry,
                 help='Show only file names not containing matching lines')


  def Execute(self, opt, args):
    out = GrepColoring(self.manifest.manifestProject.config)

    cmd_argv = ['grep']
    if out.is_on and git_require((1, 6, 3)):
      cmd_argv.append('--color')
    cmd_argv.extend(getattr(opt, 'cmd_argv', []))

    if '-e' not in cmd_argv:
      if not args:
        self.Usage()
      cmd_argv.append('-e')
      cmd_argv.append(args[0])
      args = args[1:]

    projects = self.GetProjects(args)

    full_name = False
    if len(projects) > 1:
      cmd_argv.append('--full-name')
      full_name = True

    have_rev = False
    if opt.revision:
      if '--cached' in cmd_argv:
        print('fatal: cannot combine --cached and --revision', file=sys.stderr)
        sys.exit(1)
      have_rev = True
      cmd_argv.extend(opt.revision)
    cmd_argv.append('--')

    bad_rev = False
    have_match = False

    for project in projects:
      p = GitCommand(project,
                     cmd_argv,
                     bare = False,
                     capture_stdout = True,
                     capture_stderr = True)
      if p.Wait() != 0:
        # no results
        #
        if p.stderr:
          if have_rev and 'fatal: ambiguous argument' in p.stderr:
            bad_rev = True
          else:
            out.project('--- project %s ---' % project.relpath)
            out.nl()
            out.write("%s", p.stderr)
            out.nl()
        continue
      have_match = True

      # We cut the last element, to avoid a blank line.
      #
      r = p.stdout.split('\n')
      r = r[0:-1]

      if have_rev and full_name:
        for line in r:
          rev, line = line.split(':', 1)
          out.write("%s", rev)
          out.write(':')
          out.project(project.relpath)
          out.write('/')
          out.write("%s", line)
          out.nl()
      elif full_name:
        for line in r:
          out.project(project.relpath)
          out.write('/')
          out.write("%s", line)
          out.nl()
      else:
        for line in r:
          print(line)

    if have_match:
      sys.exit(0)
    elif have_rev and bad_rev:
      for r in opt.revision:
        print("error: can't search revision %s" % r, file=sys.stderr)
      sys.exit(1)
    else:
      sys.exit(1)
