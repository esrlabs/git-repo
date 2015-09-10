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

class ManifestParseError(Exception):
  """Failed to parse the manifest file.
  """

class ManifestInvalidRevisionError(Exception):
  """The revision value in a project is incorrect.
  """

class NoManifestException(Exception):
  """The required manifest does not exist.
  """
  def __init__(self, path, reason):
    super(NoManifestException, self).__init__()
    self.path = path
    self.reason = reason

  def __str__(self):
    return self.reason

class EditorError(Exception):
  """Unspecified error from the user's text editor.
  """
  def __init__(self, reason):
    super(EditorError, self).__init__()
    self.reason = reason

  def __str__(self):
    return self.reason

class GitError(Exception):
  """Unspecified internal error from git.
  """
  def __init__(self, command):
    super(GitError, self).__init__()
    self.command = command

  def __str__(self):
    return self.command

class UploadError(Exception):
  """A bundle upload to Gerrit did not succeed.
  """
  def __init__(self, reason):
    super(UploadError, self).__init__()
    self.reason = reason

  def __str__(self):
    return self.reason

class DownloadError(Exception):
  """Cannot download a repository.
  """
  def __init__(self, reason):
    super(DownloadError, self).__init__()
    self.reason = reason

  def __str__(self):
    return self.reason

class NoSuchProjectError(Exception):
  """A specified project does not exist in the work tree.
  """
  def __init__(self, name=None):
    super(NoSuchProjectError, self).__init__()
    self.name = name

  def __str__(self):
    if self.name is None:
      return 'in current directory'
    return self.name


class InvalidProjectGroupsError(Exception):
  """A specified project is not suitable for the specified groups
  """
  def __init__(self, name=None):
    super(InvalidProjectGroupsError, self).__init__()
    self.name = name

  def __str__(self):
    if self.name is None:
      return 'in current directory'
    return self.name

class RepoChangedException(Exception):
  """Thrown if 'repo sync' results in repo updating its internal
     repo or manifest repositories.  In this special case we must
     use exec to re-execute repo with the new code and manifest.
  """
  def __init__(self, extra_args=None):
    super(RepoChangedException, self).__init__()
    self.extra_args = extra_args or []

class HookError(Exception):
  """Thrown if a 'repo-hook' could not be run.

  The common case is that the file wasn't present when we tried to run it.
  """
