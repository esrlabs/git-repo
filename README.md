
## Git-repo for Windows and Linux ##

This is a portable version (Windows 7+, Unix) of the [git-repo](http://source.android.com/source/version-control.html) tool.

Git-repo was developed by Google for their Android platform in order to manage multiple Git repositories with a single tool.
For example it is possible to view the changes of all configured git repositories with a single command: repo diff.

Since the original git-repo tool is supposed to work only on Unix systems, therefore uses platform dependent features,
Windows users have no viable solution for handling huge progjects which include many git repositories.

The mainly used, platform dependet features are: symbolic links as well as the creation of new child processes with fork().

### Requirements ###

* Git (especially Git Bash)
* Python 3+
* Windows 7+ (symbolic link support) or Unix like system

### Getting started ###

WARNING: It is recommended to use the provided 'Git Bash' in Windows.

For more detailed instructions regaring usage, visit [git-repo](http://source.android.com/source/version-control.html).
Since this version does not break any features of the original repo, the following instructions are exactly the same
found on the referenced Android git-repo tool page.

* setup a git repository (url refered to as $MANIFEST), containing a manifest file similar to Androids [default.xml](https://android.googlesource.com/platform/manifest/+/master/default.xml)
* Clone this git repository to a preferred directory ($REPO)

    git clone https://github.com/esrlabs/git-repo.git

* Change to the root of the directory
* Initialize repo with the manifest url

    $REPO/repo init -u $MANIFEST

* Sync to get all repositories

    $REPO/repo sync

* ..
