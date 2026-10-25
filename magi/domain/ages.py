"""How old a dated thing is, counted from the day it is read."""

import datetime as dt


def days_since(iso):
    return (dt.date.today() - dt.date.fromisoformat(iso[:10])).days
