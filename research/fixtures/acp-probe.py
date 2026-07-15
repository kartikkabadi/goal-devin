#!/usr/bin/env python3
"""Minimal ACP (Agent Client Protocol) probe for research.

Sends initialize and session/new to `devin acp` over stdio using
newline-delimited JSON-RPC, then prints all responses.
"""

import json
import subprocess
import time


def send(proc, msg: dict) -> None:
    line = json.dumps(msg, separators=(",", ":")) + "\n"
    proc.stdin.write(line.encode())
    proc.stdin.flush()


def main():
    proc = subprocess.Popen(
        ["devin", "acp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": 1,
            "clientCapabilities": {
                "fs": {"readTextFile": True, "writeTextFile": False},
                "terminal": False,
            },
            "clientInfo": {
                "name": "goal-devin-research-probe",
                "title": "Goal Devin Research Probe",
                "version": "0.0.0",
            },
        },
    }

    send(proc, init)
    time.sleep(2)

    new_session = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "session/new",
        "params": {
            "cwd": "/tmp",
            "mcpServers": [],
        },
    }

    send(proc, new_session)
    time.sleep(3)

    proc.terminate()
    try:
        outs, errs = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        outs, errs = proc.communicate()

    print("--- stdout ---")
    print(outs.decode(errors="replace"))
    print("--- stderr ---")
    print(errs.decode(errors="replace"))
    print("--- returncode ---")
    print(proc.returncode)


if __name__ == "__main__":
    main()
