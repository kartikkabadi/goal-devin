#!/usr/bin/env python3
"""Negative-control candidate that hangs forever without doing any work."""

import time

if __name__ == "__main__":
    while True:
        time.sleep(3600)
