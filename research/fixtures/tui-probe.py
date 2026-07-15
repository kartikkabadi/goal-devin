#!/usr/bin/env python3
"""Minimal PTY-based native Devin TUI probe.

Spawns `devin` in a pseudo-terminal, sends a bounded sequence of inputs,
reads available stdout until the process exits, and writes the raw capture
to a file for offline ANSI inspection.
"""

import fcntl
import os
import pty
import select
import subprocess
import sys


def set_nonblocking(fd):
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)


def drain(fd, timeout=0.2):
    out = b""
    while True:
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            break
        try:
            chunk = os.read(fd, 8192)
            if not chunk:
                return out, True  # EOF
            out += chunk
        except BlockingIOError:
            break
        except OSError:
            # PTY closed/reset by child exit.
            return out, True
    return out, False


def main():
    if len(sys.argv) < 3:
        print("usage: tui-probe.py <out-file> <stderr-file> [cwd]", file=sys.stderr)
        sys.exit(2)
    output_path = sys.argv[1]
    stderr_path = sys.argv[2]
    workdir = sys.argv[3] if len(sys.argv) > 3 else "."

    master, slave = pty.openpty()
    set_nonblocking(master)

    env = {
        **os.environ,
        "TERM": "xterm-256color",
        "PATH": "/home/ubuntu/.local/bin:" + os.environ.get("PATH", ""),
    }

    with open(stderr_path, "wb") as stderr_file:
        proc = subprocess.Popen(
            ["devin"],
            stdin=slave,
            stdout=slave,
            stderr=stderr_file,
            cwd=workdir,
            env=env,
            preexec_fn=os.setsid,
        )
    os.close(slave)

    captured = b""
    eof = False
    try:
        # Wait for the TUI to initialize.
        chunk, eof = drain(master, timeout=2.0)
        captured += chunk

        # Send a prompt.
        if not eof:
            os.write(master, b"hello\n")
            chunk, eof = drain(master, timeout=5.0)
            captured += chunk

        # Send the exit command.
        if not eof:
            os.write(master, b"/exit\n")
            chunk, eof = drain(master, timeout=3.0)
            captured += chunk

        # Send Ctrl+C in case /exit did not terminate.
        if not eof:
            os.write(master, b"\x03")
            chunk, eof = drain(master, timeout=2.0)
            captured += chunk

        # Send Esc in case a menu/permission prompt is open.
        if not eof:
            os.write(master, b"\x1b")
            chunk, eof = drain(master, timeout=2.0)
            captured += chunk
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        os.close(master)

    with open(output_path, "wb") as f:
        f.write(captured)

    print(f"Captured {len(captured)} bytes to {output_path}")
    print(f"Return code: {proc.returncode}")


if __name__ == "__main__":
    main()
