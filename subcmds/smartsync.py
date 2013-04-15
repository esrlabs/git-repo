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

from subcmds.sync import Sync


class Smartsync(Sync):
    common = True
    helpSummary = "Update working tree to the latest known good revision"
    helpUsage = """
%prog [<project>...]
"""
    helpDescription = """
The '%prog' command is a shortcut for sync -s.
"""

    def _Options(self, p):
        Sync._Options(self, p, show_smart=False)

    def Execute(self, opt, args):
        opt.smart_sync = True
        Sync.Execute(self, opt, args)
