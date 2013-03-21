
## Git-repo for Windows and Linux ##

This is a portable version (Windows 7+, Linux) of the [git-repo](http://source.android.com/source/version-control.html) tool.

Git-repo was developed by Google for their Android platform in order to manage multiple Git repositories with a single tool.
For example it is possible to view the changes of all configured git repositories with a single command: repo diff.

Since the original git-repo tool is supposed to work only on Linux systems, therefore uses platform dependent features,
Windows users have no viable solution for handling huge progjects which include many git repositories.

The mainly used, platform dependet features are: symbolic links as well as the creation of new child processes with fork().


### Requirements ###

* [Python 3.3+](http://python.org/download/releases/3.3.0/)
* [Git](http://git-scm.com/)
* Windows 7+ or Linux

### Setup ###

#### Windows ####

* Add to Windows environment variable PATH
    * full additions (explained further on)
        ;C:\Python33C;\Program Files (x86)\Git\cmd;C:\Program Files (x86)\Git\bin;%USERPROFILE%
    * Python3.3
    * Git cmd folder
    * Git bin folder
    * repo script default path

* Download repo script

    curl https://raw.github.com/esrlabs/git-repo/master/repo > %USERPROFILE%/repo

    curl https://raw.github.com/esrlabs/git-repo/master/repo > %USERPROFILE%/repo.cmd


#### Linux ####

* Add to environment variable PATH
    * repo bin folder (separator is ':')
      ~/bin

* Download repo script

    curl https://raw.github.com/esrlabs/git-repo/master/repo > ~/bin/repo

* Make executable

    chmod +x ~/bin/repo

* Optional: Manage different python versions
    * setup alternative executables for python

    sudo update-alternatives --install /usr/bin/python python /usr/bin/python2 10

    sudo update-alternatives --install /usr/bin/python python /usr/bin/python3.3 20

    * switching to python 3 / python2 (command provides interactive switching)

    sudo update-alternatives --config python


### Usage ###

For more detailed instructions regarding usage, visit [git-repo](http://source.android.com/source/version-control.html).
Since this version does not break any features of the original repo, the following instructions are exactly the same
found on the referenced Android [git-repo](http://source.android.com/source/version-control.html) tool page.

* setup a git repository (url refered to as $MANIFEST), containing a manifest file similar to Androids [default.xml](https://android.googlesource.com/platform/manifest/+/master/default.xml)
* Change to the root folder of your project
* Initialize repo with the manifest url

    repo init -u $MANIFEST

* Sync to get all repositories

    repo sync

* do stuff in git repositories..
* view diff, status, .. (in root folder)

    repo status

    repo diff
