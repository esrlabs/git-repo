# Short Version

 - Make small logical changes.
 - Provide a meaningful commit message.
 - Check for coding errors and style nits with pyflakes and flake8
 - Make sure all code is under the Apache License, 2.0.
 - Publish your changes for review.
 - Make corrections if requested.
 - Verify your changes on gerrit so they can be submitted.

   `git push https://gerrit-review.googlesource.com/git-repo HEAD:refs/for/master`


# Long Version

I wanted a file describing how to submit patches for repo,
so I started with the one found in the core Git distribution
(Documentation/SubmittingPatches), which itself was based on the
patch submission guidelines for the Linux kernel.

However there are some differences, so please review and familiarize
yourself with the following relevant bits.


## Make separate commits for logically separate changes.

Unless your patch is really trivial, you should not be sending
out a patch that was generated between your working tree and your
commit head.  Instead, always make a commit with complete commit
message and generate a series of patches from your repository.
It is a good discipline.

Describe the technical detail of the change(s).

If your description starts to get too long, that's a sign that you
probably need to split up your commit to finer grained pieces.


## Check for coding errors and style nits with pyflakes and flake8

### Coding errors

Run `pyflakes` on changed modules:

    pyflakes file.py

Ideally there should be no new errors or warnings introduced.

### Style violations

Run `flake8` on changes modules:

    flake8 file.py

Note that repo generally follows [Google's python style guide]
(https://google.github.io/styleguide/pyguide.html) rather than [PEP 8]
(https://www.python.org/dev/peps/pep-0008/), so it's possible that
the output of `flake8` will be quite noisy. It's not mandatory to
avoid all warnings, but at least the maximum line length should be
followed.

If there are many occurrences of the same warning that cannot be
avoided without going against the Google style guide, these may be
suppressed in the included `.flake8` file.

## Check the license

repo is licensed under the Apache License, 2.0.

Because of this licensing model *every* file within the project
*must* list the license that covers it in the header of the file.
Any new contributions to an existing file *must* be submitted under
the current license of that file.  Any new files *must* clearly
indicate which license they are provided under in the file header.

Please verify that you are legally allowed and willing to submit your
changes under the license covering each file *prior* to submitting
your patch.  It is virtually impossible to remove a patch once it
has been applied and pushed out.


## Sending your patches.

Do not email your patches to anyone.

Instead, login to the Gerrit Code Review tool at:

  https://gerrit-review.googlesource.com/

Ensure you have completed one of the necessary contributor
agreements, providing documentation to the project maintainers that
they have right to redistribute your work under the Apache License:

  https://gerrit-review.googlesource.com/#/settings/agreements

Ensure you have obtained an HTTP password to authenticate:

  https://gerrit-review.googlesource.com/new-password

Ensure that you have the local commit hook installed to automatically
add a ChangeId to your commits:

    curl -Lo `git rev-parse --git-dir`/hooks/commit-msg https://gerrit-review.googlesource.com/tools/hooks/commit-msg
    chmod +x `git rev-parse --git-dir`/hooks/commit-msg

If you have already committed your changes you will need to amend the commit
to get the ChangeId added.

    git commit --amend

Push your patches over HTTPS to the review server, possibly through
a remembered remote to make this easier in the future:

    git config remote.review.url https://gerrit-review.googlesource.com/git-repo
    git config remote.review.push HEAD:refs/for/master

    git push review

You will be automatically emailed a copy of your commits, and any
comments made by the project maintainers.


## Make changes if requested

The project maintainer who reviews your changes might request changes to your
commit. If you make the requested changes you will need to amend your commit
and push it to the review server again.


## Verify your changes on gerrit

After you receive a Code-Review+2 from the maintainer, select the Verified
button on the gerrit page for the change. This verifies that you have tested
your changes and notifies the maintainer that they are ready to be submitted.
The maintainer will then submit your changes to the repository.
