## Repo for Microsoft Windows and Linux ##

This is E.S.R.Labs Repo - just like Google Repo but this one also runs under Microsoft Windows.
For more information, see [Version Control with Repo and Git](http://source.android.com/source/version-control.html).

Repo is a repository management tool that Google built on top of Git. Repo unifies many Git repositories when necessary,
does the uploads to a revision control system, and automates parts of the development workflow.
Repo is not meant to replace Git, only to make it easier to work with Git in the context of multiple repositories.
The repo command is an executable Python script that you can put anywhere in your path.
In working with the source files, you will use Repo for across-network operations.
For example, with a single Repo command you can download files from multiple repositories into your local working directory.

### Setup steps for Microsoft Windows ###

##### Download and install Git #####
* Download [Git (http://git-scm.com/downloads)](http://git-scm.com/downloads)
* Add Git to your path environment variable: e.g. C:\Program Files (x86)\Git\cmd;C:\Program Files (x86)\Git\bin;
	
##### Download and install Python #####
* Download [Python 3+ (http://python.org/download/releases/3.3.0/)](http://python.org/download/releases/3.3.0/)
* Add Python to your path environment variable: e.g. C:\Python33;

##### Download and install Repo either using the Windows Command Shell or Git Bash #####
###### Windows Command Shell ######

    md %USERPROFILE%\bin
    curl https://raw.github.com/esrlabs/git-repo/master/repo > %USERPROFILE%/bin/repo
    curl https://raw.github.com/esrlabs/git-repo/master/repo.cmd > %USERPROFILE%/bin/repo.cmd
	
###### Git Bash ######

    mkdir ~/bin
    curl https://raw.github.com/esrlabs/git-repo/master/repo > ~/bin/repo
    curl https://raw.github.com/esrlabs/git-repo/master/repo.cmd > ~/bin/repo.cmd
	
* Add Repo to your path environment variable: %USERPROFILE%\bin;
	
### Setup steps for Linux ###

##### Downloading and installing Git and Python #####
* sudo apt-get install git-core
* Since our Repo requires Python 3.3, use the following commands to switch between multiple Python versions:
#####

    sudo update-alternatives --install /usr/bin/python python /usr/bin/python2 10
    sudo update-alternatives --install /usr/bin/python python /usr/bin/python3.3 20
    sudo update-alternatives --config python

##### Download and install Repo #####

    $ mkdir ~/bin
    $ PATH=~/bin:$PATH
	$ curl https://raw.github.com/esrlabs/git-repo/master/repo > ~/bin/repo
    $ chmod a+x ~/bin/repo

### Usage ###

For more detailed instructions regarding usage, visit [git-repo](http://source.android.com/source/version-control.html).
