import os
import subprocess
import sys


def open_in_browser(url):
    subprocess.Popen(["open", url])


def pbcopy(text):
    subprocess.run(["pbcopy"], input=text, text=True, check=True)


def leave(app):
    # Skip the interpreter's shutdown: it joins the pool workers of a running or failed refresh, after every queued acli and gh call.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(app.return_code or 0)
