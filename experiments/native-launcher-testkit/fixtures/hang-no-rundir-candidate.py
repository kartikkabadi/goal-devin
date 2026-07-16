#!/usr/bin/env python3
"""Negative-control candidate that hangs without ever creating a run directory."""

import time

if __name__ == "__main__":
    while True:
        time.sleep(3600)
