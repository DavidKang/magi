"""How old a dated thing is, counted in local days from the day it is read."""

import datetime as dt


def days_since(iso):
    return (dt.date.today() - dt.datetime.fromisoformat(iso).astimezone().date()).days
