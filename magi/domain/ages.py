"""How old a dated thing is: in local days from the day it is read, or in the largest unit that fits."""

import datetime as dt

# How long ago, in the largest unit that fits: seconds under a minute read as 0m.
AGE_UNITS = ((86400, "d"), (3600, "h"), (60, "m"))


def days_since(iso):
    return (dt.date.today() - dt.datetime.fromisoformat(iso).astimezone().date()).days


def ago(since, now):
    seconds = max((now - since).total_seconds(), 0)
    return next((f"{int(seconds // size)}{unit}" for size, unit in AGE_UNITS if seconds >= size), "0m")
