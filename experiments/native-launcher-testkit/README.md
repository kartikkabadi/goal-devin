# Goal Devin — Native Launcher Testkit (shared)

This directory contains fixtures shared by the R1A Python and R1B Rust native
launcher candidates.

## Contents

- `fake_devin.py` — a deterministic stand-in for the `devin` executable that
  fires project hooks, writes an ATIF export, and can simulate failures.

Both candidates import from this testkit and run the same black-box contract
against `fake_devin.py` in CI. The live canary runs against the installed real
`devin` binary separately.
