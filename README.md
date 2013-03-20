
## Git-repo for Windows and Linux ##

This is a port of the [git-repo](http://source.android.com/source/version-control.html) tool from Unix to Windows.
Git-repo was developed by Google for their Android platform in order to manage multiple Git repositories with a single tool.
For further information, refer to the [git-repo](http://source.android.com/source/version-control.html) page of Android.

Since the original git-repo tool is supposed to work only on Unix systems, therefore uses platform dependent features,
Windows users have no viable solution for handling huge progjects which include many git repositories.

The mainly used, platform dependet features are: symbolic links as well as the creation of new child processes with fork().

### Requirements ###

* Python 3+
* Windows 7+ (symbolic link support)