"""Backoff helpers for retrying transient runtime failures."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BackoffPolicy:

    interval: int
    max_delay: int = 60
    max_exponent: int = 4

    def delay_for(self, consecutive_errors):
        if consecutive_errors <= 0:
            return self.interval
        exponent = min(consecutive_errors, self.max_exponent)
        return min(self.interval * (2**exponent), self.max_delay)
