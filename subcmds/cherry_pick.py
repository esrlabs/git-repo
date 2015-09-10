#
# Copyright (C) 2010 The Android Open Source Project
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
from command import Command
from git_command import GitCommand

CHANGE_ID_RE = re.compile(r'^\s*Change-Id: I([0-9a-f]{40})\s*$')

class CherryPick(Command):
  common = True
  helpSummary = "Cherry-pick a change."
  helpUsage = """
%prog <sha1>
"""
  helpDescription = """
'%prog' cherry-picks a change from one branch to another.
The change id will be updated, and a reference to the old
change id will be added.
"""

  def _Options(self, p):
    pass

  def Execute(self, opt, args):
    if len(args) != 1:
      self.Usage()

    reference = args[0]

    p = GitCommand(None,
                   ['rev-parse', '--verify', reference],
                   capture_stdout = True,
                   capture_stderr = True)
    if p.Wait() != 0:
      print(p.stderr, file=sys.stderr)
      sys.exit(1)
    sha1 = p.stdout.strip()

    p = GitCommand(None, ['cat-file', 'commit', sha1], capture_stdout=True)
    if p.Wait() != 0:
      print("error: Failed to retrieve old commit message", file=sys.stderr)
      sys.exit(1)
    old_msg = self._StripHeader(p.stdout)

    p = GitCommand(None,
                   ['cherry-pick', sha1],
                   capture_stdout = True,
                   capture_stderr = True)
    status = p.Wait()

    print(p.stdout, file=sys.stdout)
    print(p.stderr, file=sys.stderr)

    if status == 0:
      # The cherry-pick was applied correctly. We just need to edit the
      # commit message.
      new_msg = self._Reformat(old_msg, sha1)

      p = GitCommand(None, ['commit', '--amend', '-F', '-'],
                     provide_stdin = True,
                     capture_stdout = True,
                     capture_stderr = True)
      p.stdin.write(new_msg)
      p.stdin.close()
      if p.Wait() != 0:
        print("error: Failed to update commit message", file=sys.stderr)
        sys.exit(1)

    else:
      print('NOTE: When committing (please see above) and editing the commit '
            'message, please remove the old Change-Id-line and add:')
      print(self._GetReference(sha1), file=sys.stderr)
      print(file=sys.stderr)

  def _IsChangeId(self, line):
    return CHANGE_ID_RE.match(line)

  def _GetReference(self, sha1):
    return "(cherry picked from commit %s)" % sha1

  def _StripHeader(self, commit_msg):
    lines = commit_msg.splitlines()
    return "\n".join(lines[lines.index("")+1:])

  def _Reformat(self, old_msg, sha1):
    new_msg = []

    for line in old_msg.splitlines():
      if not self._IsChangeId(line):
        new_msg.append(line)

    # Add a blank line between the message and the change id/reference
    try:
      if new_msg[-1].strip() != "":
        new_msg.append("")
    except IndexError:
      pass

    new_msg.append(self._GetReference(sha1))
    return "\n".join(new_msg)
