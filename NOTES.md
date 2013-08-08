
# TODO

Bugs:
*

Features:
* upload via https
* upload without reviewing

# Notes on compability

* Windows does not allow links to non-existing files and dirs
* Windows does not allow a ":" in the filename
* Windows is case insensitive

# Extensions

* Remote Debugging Possibility
    * options:
        * enable debugging: --debug
        * set debug host: --debug-host=172.31.0.250
          (default localhost, uses port is 19499)
    * in debugger startup code: set path mappings (! elsewise breakpoints not found)
* using local git-repo (in $GIT_REPO; branch 'dev') and local git repositories (in $REPOS)
    $GIT_REPO/repo init -u $REPOS/manifest/ --no-repo-verify --repo-branch=dev
* Tracing: set environment variable
    export REPO_TRACE=1

# repo functionality

## handling external config: repo/.git and repo.git/

* files always created:
    * hooks, info, logs, objects, refs

* files not linked
    * HEAD, gitk.cache, index

* problemcatic files: created on demand, when?
    * [D] rr-cache
    * [F] packed-refs

## packed-refs

* increases performace since refs are packed - cleartext?
* affects of:
    * non existing -> failure in windows when trying to link
    * empty -> no effect


# Problems / Conversions

## Windows, coloring:

* disabled if pager not active => fixed with option: --piped-into-pager

## Processes, fork()

* fork()
    * => restart oneself with '| less' appended
    * extensive usage of "new" subprocess module in python
* git commands not stopped if main program terminates due to STRG+C
    * => added sdignal handler
