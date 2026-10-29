import asyncio
import os
import subprocess
import sys
import threading


def open_in_browser(url):
    subprocess.Popen(["open", url])


def pbcopy(text):
    subprocess.run(["pbcopy"], input=text, text=True, check=True)


def leave(app):
    # Skip the interpreter's shutdown: it joins the pool workers of a running or failed refresh, after every queued acli and gh call.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(app.return_code or 0)


def error_message(error):
    return error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) and error.stderr else str(error)


async def off_loop(call):
    """call's result or error, run on a daemon thread rather than the loop's executor: quitting must not wait for it."""
    loop = asyncio.get_running_loop()
    outcome = loop.create_future()

    def run():
        try:
            found = (call(), None)
        except Exception as error:
            found = (None, error)
        try:
            loop.call_soon_threadsafe(lambda: outcome.done() or outcome.set_result(found))
        except RuntimeError:  # the app quit and closed its loop while call ran
            pass

    threading.Thread(target=run, daemon=True).start()
    return await outcome
