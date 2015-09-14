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
import os
import portable
import re
import sys
import subprocess
import tempfile

from error import EditorError

class Editor(object):
  """Manages the user's preferred text editor."""

  _editor = None
  globalConfig = None

  @classmethod
  def _GetEditor(cls):
    if cls._editor is None:
      cls._editor = cls._SelectEditor()
    return cls._editor

  @classmethod
  def _SelectEditor(cls):
    e = os.getenv('GIT_EDITOR')
    if e:
      return e

    if cls.globalConfig:
      e = cls.globalConfig.GetString('core.editor')
      if e:
        return e

    e = os.getenv('VISUAL')
    if e:
      return e

    e = os.getenv('EDITOR')
    if e:
      return e

    if os.getenv('TERM') == 'dumb':
      print(
"""No editor specified in GIT_EDITOR, core.editor, VISUAL or EDITOR.
Tried to fall back to vi but terminal is dumb.  Please configure at
least one of these before using this command.""", file=sys.stderr)
      sys.exit(1)

    return 'vi'

  @classmethod
  def EditString(cls, data):
    """Opens an editor to edit the given content.

       Args:
         data        : the text to edit

      Returns:
        new value of edited text; None if editing did not succeed
    """
    editor = cls._GetEditor()
    if editor == ':':
      return data

    fd, path = tempfile.mkstemp()
    try:
      os.write(fd, data)
      os.close(fd)
      fd = None

      if re.compile("^.*[$ \t'].*$").match(editor):
        # args = [editor + ' "$@"', 'sh']
        # shell = True
        (args, shell) = portable.prepare_editor_args(editor)
      else:
        args = [editor]
        shell = False
      args.append(path)

      try:
        rc = subprocess.Popen(args, shell=shell).wait()
      except OSError as e:
        raise EditorError('editor failed, %s: %s %s'
          % (str(e), editor, path))
      if rc != 0:
        raise EditorError('editor failed with exit status %d: %s %s'
          % (rc, editor, path))

      fd2 = open(path)
      try:
        return fd2.read()
      finally:
        fd2.close()
    finally:
      if fd:
        os.close(fd)
      os.remove(path)
