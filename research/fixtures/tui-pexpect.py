#!/usr/bin/env python3
"""Pexpect-based native Devin TUI probe.

Spawns `devin` in a PTY, sends a prompt and slash commands, and writes the
raw output (including ANSI escapes) to files.
"""

import os
import pexpect
import sys


def main():
    if len(sys.argv) < 3:
        print("usage: tui-pexpect.py <out-file> <stderr-file> [cwd]", file=sys.stderr)
        sys.exit(2)
    output_path = sys.argv[1]
    stderr_path = sys.argv[2]
    workdir = sys.argv[3] if len(sys.argv) > 3 else "."

    env = {
        **os.environ,
        "TERM": "xterm-256color",
        "PATH": "/home/ubuntu/.local/bin:" + os.environ.get("PATH", ""),
    }

    with open(output_path, "wb") as out, open(stderr_path, "wb") as _err:
        child = pexpect.spawn(
            "/home/ubuntu/.local/bin/devin",
            args=[],
            cwd=workdir,
            env=env,
            logfile=out,
            encoding=None,
            timeout=30,
            maxread=8192,
        )

        # Wait for the TUI to settle (the logo + prompt appears).
        try:
            child.expect([b"Ask Devin", b"Devin CLI", b"SWE-1"], timeout=5)
        except pexpect.TIMEOUT:
            pass

        # Send a prompt terminated by CR (Enter).
        child.send(b"hello\r")
        try:
            child.expect([b"hello", b"Hi", b"How"], timeout=10)
        except pexpect.TIMEOUT:
            pass

        # Attempt to exit via slash command and key sequences.
        child.send(b"/exit\r")
        try:
            child.expect([b"killing", b"terminated", pexpect.EOF], timeout=8)
        except pexpect.TIMEOUT:
            pass

        child.send(b"\x03")  # Ctrl+C
        try:
            child.expect([pexpect.EOF], timeout=3)
        except pexpect.TIMEOUT:
            pass

        child.send(b"\x1b")  # Esc
        try:
            child.expect([pexpect.EOF], timeout=3)
        except pexpect.TIMEOUT:
            pass

        if child.isalive():
            child.terminate(force=True)
        child.close()

    print(f"Return code: {child.exitstatus}")


if __name__ == "__main__":
    main()
