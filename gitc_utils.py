#
# Copyright (C) 2015 The Android Open Source Project
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
import platform
import re
import sys
import time

import git_command
import git_config
import wrapper

from error import ManifestParseError

NUM_BATCH_RETRIEVE_REVISIONID = 32

def get_gitc_manifest_dir():
  return wrapper.Wrapper().get_gitc_manifest_dir()

def parse_clientdir(gitc_fs_path):
  return wrapper.Wrapper().gitc_parse_clientdir(gitc_fs_path)

def _set_project_revisions(projects):
  """Sets the revisionExpr for a list of projects.

  Because of the limit of open file descriptors allowed, length of projects
  should not be overly large. Recommend calling this function multiple times
  with each call not exceeding NUM_BATCH_RETRIEVE_REVISIONID projects.

  @param projects: List of project objects to set the revionExpr for.
  """
  # Retrieve the commit id for each project based off of it's current
  # revisionExpr and it is not already a commit id.
  project_gitcmds = [(
      project, git_command.GitCommand(None,
                                      ['ls-remote',
                                       project.remote.url,
                                       project.revisionExpr],
                                      capture_stdout=True, cwd='/tmp'))
      for project in projects if not git_config.IsId(project.revisionExpr)]
  for proj, gitcmd in project_gitcmds:
    if gitcmd.Wait():
      print('FATAL: Failed to retrieve revisionExpr for %s' % proj)
      sys.exit(1)
    revisionExpr = gitcmd.stdout.split('\t')[0]
    if not revisionExpr:
      raise(ManifestParseError('Invalid SHA-1 revision project %s (%s)' %
                               (proj.remote.url, proj.revisionExpr)))
    proj.revisionExpr = revisionExpr

def _manifest_groups(manifest):
  """Returns the manifest group string that should be synced

  This is the same logic used by Command.GetProjects(), which is used during
  repo sync

  @param manifest: The XmlManifest object
  """
  mp = manifest.manifestProject
  groups = mp.config.GetString('manifest.groups')
  if not groups:
    groups = 'default,platform-' + platform.system().lower()
  return groups

def generate_gitc_manifest(gitc_manifest, manifest, paths=None):
  """Generate a manifest for shafsd to use for this GITC client.

  @param gitc_manifest: Current gitc manifest, or None if there isn't one yet.
  @param manifest: A GitcManifest object loaded with the current repo manifest.
  @param paths: List of project paths we want to update.
  """

  print('Generating GITC Manifest by fetching revision SHAs for each '
        'project.')
  if paths is None:
    paths = manifest.paths.keys()

  groups = [x for x in re.split(r'[,\s]+', _manifest_groups(manifest)) if x]

  # Convert the paths to projects, and filter them to the matched groups.
  projects = [manifest.paths[p] for p in paths]
  projects = [p for p in projects if p.MatchesGroups(groups)]

  if gitc_manifest is not None:
    for path, proj in manifest.paths.iteritems():
      if not proj.MatchesGroups(groups):
        continue

      if not proj.upstream and not git_config.IsId(proj.revisionExpr):
        proj.upstream = proj.revisionExpr

      if not path in gitc_manifest.paths:
        # Any new projects need their first revision, even if we weren't asked
        # for them.
        projects.append(proj)
      elif not path in paths:
        # And copy revisions from the previous manifest if we're not updating
        # them now.
        gitc_proj = gitc_manifest.paths[path]
        if gitc_proj.old_revision:
          proj.revisionExpr = None
          proj.old_revision = gitc_proj.old_revision
        else:
          proj.revisionExpr = gitc_proj.revisionExpr

  index = 0
  while index < len(projects):
    _set_project_revisions(
        projects[index:(index+NUM_BATCH_RETRIEVE_REVISIONID)])
    index += NUM_BATCH_RETRIEVE_REVISIONID

  if gitc_manifest is not None:
    for path, proj in gitc_manifest.paths.iteritems():
      if proj.old_revision and path in paths:
        # If we updated a project that has been started, keep the old-revision
        # updated.
        repo_proj = manifest.paths[path]
        repo_proj.old_revision = repo_proj.revisionExpr
        repo_proj.revisionExpr = None

  # Convert URLs from relative to absolute.
  for _name, remote in manifest.remotes.iteritems():
    remote.fetchUrl = remote.resolvedFetchUrl

  # Save the manifest.
  save_manifest(manifest)

def save_manifest(manifest, client_dir=None):
  """Save the manifest file in the client_dir.

  @param client_dir: Client directory to save the manifest in.
  @param manifest: Manifest object to save.
  """
  if not client_dir:
    client_dir = manifest.gitc_client_dir
  with open(os.path.join(client_dir, '.manifest'), 'w') as f:
    manifest.Save(f, groups=_manifest_groups(manifest))
  # TODO(sbasi/jorg): Come up with a solution to remove the sleep below.
  # Give the GITC filesystem time to register the manifest changes.
  time.sleep(3)
