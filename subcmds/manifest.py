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
import os
import sys

from command import PagedCommand

class Manifest(PagedCommand):
  common = False
  helpSummary = "Manifest inspection utility"
  helpUsage = """
%prog [-o {-|NAME.xml} [-r]]
"""
  _helpDescription = """

With the -o option, exports the current manifest for inspection.
The manifest and (if present) local_manifest.xml are combined
together to produce a single manifest file.  This file can be stored
in a Git repository for use during future 'repo init' invocations.

"""

  @property
  def helpDescription(self):
    helptext = self._helpDescription + '\n'
    r = os.path.dirname(__file__)
    r = os.path.dirname(r)
    fd = open(os.path.join(r, 'docs', 'manifest-format.txt'))
    for line in fd:
      helptext += line
    fd.close()
    return helptext

  def _Options(self, p):
    p.add_option('-r', '--revision-as-HEAD',
                 dest='peg_rev', action='store_true',
                 help='Save revisions as current HEAD')
    p.add_option('--suppress-upstream-revision', dest='peg_rev_upstream',
                 default=True, action='store_false',
                 help='If in -r mode, do not write the upstream field.  '
                 'Only of use if the branch names for a sha1 manifest are '
                 'sensitive.')
    p.add_option('-o', '--output-file',
                 dest='output_file',
                 default='-',
                 help='File to save the manifest to',
                 metavar='-|NAME.xml')

  def _Output(self, opt):
    if opt.output_file == '-':
      fd = sys.stdout
    else:
      fd = open(opt.output_file, 'w')
    self.manifest.Save(fd,
                       peg_rev = opt.peg_rev,
                       peg_rev_upstream = opt.peg_rev_upstream)
    fd.close()
    if opt.output_file != '-':
      print('Saved manifest to %s' % opt.output_file, file=sys.stderr)

  def Execute(self, opt, args):
    if args:
      self.Usage()

    if opt.output_file is not None:
      self._Output(opt)
      return

    print('error: no operation to perform', file=sys.stderr)
    print('error: see repo help manifest', file=sys.stderr)
    sys.exit(1)
