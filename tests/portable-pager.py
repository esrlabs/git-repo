import os
import sys
import select

__author__ = 'mputz'


def RunPager():
    global active

    if not os.isatty(0) or not os.isatty(1):
        return
    pager = 'less'
    if pager == '' or pager == 'cat':
        return

    # This process turns into the pager; a child it forks will
    # do the real processing and output back to the pager. This
    # is necessary to keep the pager in control of the tty.
    #
    try:
        r, w = os.pipe()
        pid = os.fork()
        if not pid:
            os.dup2(w, 1)
            os.dup2(w, 2)
            os.close(r)
            os.close(w)
            active = True
            return

        os.dup2(r, 0)
        os.close(r)
        os.close(w)

        _BecomePager(pager)
    except Exception:
        print("fatal: cannot start pager '%s'" % pager, file=sys.stderr)
        sys.exit(255)


def _BecomePager(pager):
    # Delaying execution of the pager until we have output
    # ready works around a long-standing bug in popularly
    # available versions of 'less', a better 'more'.
    #
    _a, _b, _c = select.select([0], [], [0])

    os.environ['LESS'] = 'FRSX'

    try:
        os.execvp(pager, [pager])
    except OSError:
        os.execv('/bin/sh', ['sh', '-c', pager])


if __name__ == '__main__':
    if len(sys.argv) == 1:
        print('run pager')

        import subprocess
        import platform
        #subprocess.call(["python3.3", "portable-pager.py", "1", "| less"])
        if platform.system() != "Windows":
            python = "python3.3"
        else:
            python = "python"

        os.system("%s portable-pager.py 1 | less" % python)

        #RunPager()
    else:
        print('output data')
        for i in range(0, 100):
            print("%d" % i)
