"""The system clock the refresh reads."""

import datetime as dt
import time


class SystemClock:
    def time(self):
        return time.time()

    def now(self):
        return dt.datetime.now()
