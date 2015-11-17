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

from __future__ import print_function
import re
import sys
from formatter import AbstractFormatter, DumbWriter

from color import Coloring
from command import PagedCommand, MirrorSafeCommand, GitcAvailableCommand, GitcClientCommand
import gitc_utils

class Help(PagedCommand, MirrorSafeCommand):
  common = False
  helpSummary = "Display detailed help on a command"
  helpUsage = """
%prog [--all|command]
"""
  helpDescription = """
Displays detailed usage information about a command.
"""

  def _PrintAllCommands(self):
    print('usage: repo COMMAND [ARGS]')
    print('The complete list of recognized repo commands are:')
    commandNames = list(sorted(self.commands))

    maxlen = 0
    for name in commandNames:
      maxlen = max(maxlen, len(name))
    fmt = '  %%-%ds  %%s' % maxlen

    for name in commandNames:
      command = self.commands[name]
      try:
        summary = command.helpSummary.strip()
      except AttributeError:
        summary = ''
      print(fmt % (name, summary))
    print("See 'repo help <command>' for more information on a "
          'specific command.')

  def _PrintCommonCommands(self):
    print('usage: repo COMMAND [ARGS]')
    print('The most commonly used repo commands are:')

    def gitc_supported(cmd):
      if not isinstance(cmd, GitcAvailableCommand) and not isinstance(cmd, GitcClientCommand):
        return True
      if self.manifest.isGitcClient:
        return True
      if isinstance(cmd, GitcClientCommand):
        return False
      if gitc_utils.get_gitc_manifest_dir():
        return True
      return False

    commandNames = list(sorted([name
                    for name, command in self.commands.items()
                    if command.common and gitc_supported(command)]))

    maxlen = 0
    for name in commandNames:
      maxlen = max(maxlen, len(name))
    fmt = '  %%-%ds  %%s' % maxlen

    for name in commandNames:
      command = self.commands[name]
      try:
        summary = command.helpSummary.strip()
      except AttributeError:
        summary = ''
      print(fmt % (name, summary))
    print(
"See 'repo help <command>' for more information on a specific command.\n"
"See 'repo help --all' for a complete list of recognized commands.")

  def _PrintCommandHelp(self, cmd):
    class _Out(Coloring):
      def __init__(self, gc):
        Coloring.__init__(self, gc, 'help')
        self.heading = self.printer('heading', attr='bold')

        self.wrap = AbstractFormatter(DumbWriter())

      def _PrintSection(self, heading, bodyAttr):
        try:
          body = getattr(cmd, bodyAttr)
        except AttributeError:
          return
        if body == '' or body is None:
          return

        self.nl()

        self.heading('%s', heading)
        self.nl()

        self.heading('%s', ''.ljust(len(heading), '-'))
        self.nl()

        me = 'repo %s' % cmd.NAME
        body = body.strip()
        body = body.replace('%prog', me)

        asciidoc_hdr = re.compile(r'^\n?([^\n]{1,})\n([=~-]{2,})$')
        for para in body.split("\n\n"):
          if para.startswith(' '):
            self.write('%s', para)
            self.nl()
            self.nl()
            continue

          m = asciidoc_hdr.match(para)
          if m:
            title = m.group(1)
            section_type = m.group(2)
            if section_type[0] in ('=', '-'):
              p = self.heading
            else:
              def _p(fmt, *args):
                self.write('  ')
                self.heading(fmt, *args)
              p = _p

            p('%s', title)
            self.nl()
            p('%s', ''.ljust(len(title), section_type[0]))
            self.nl()
            continue

          self.wrap.add_flowing_data(para)
          self.wrap.end_paragraph(1)
        self.wrap.end_paragraph(0)

    out = _Out(self.manifest.globalConfig)
    out._PrintSection('Summary', 'helpSummary')
    cmd.OptionParser.print_help()
    out._PrintSection('Description', 'helpDescription')

  def _Options(self, p):
    p.add_option('-a', '--all',
                 dest='show_all', action='store_true',
                 help='show the complete list of commands')

  def Execute(self, opt, args):
    if len(args) == 0:
      if opt.show_all:
        self._PrintAllCommands()
      else:
        self._PrintCommonCommands()

    elif len(args) == 1:
      name = args[0]

      try:
        cmd = self.commands[name]
      except KeyError:
        print("repo: '%s' is not a repo command." % name, file=sys.stderr)
        sys.exit(1)

      cmd.manifest = self.manifest
      self._PrintCommandHelp(cmd)

    else:
      self._PrintCommandHelp(self)
