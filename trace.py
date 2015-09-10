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
import sys
import os
REPO_TRACE = 'REPO_TRACE'

try:
  _TRACE = os.environ[REPO_TRACE] == '1'
except KeyError:
  _TRACE = False

def IsTrace():
  return _TRACE

def SetTrace():
  global _TRACE
  _TRACE = True

def Trace(fmt, *args):
  if IsTrace():
    print(fmt % args, file=sys.stderr)
