"""Put the candidate package on sys.path for tests."""

import os
import sys

CANDIDATE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CANDIDATE_DIR not in sys.path:
    sys.path.insert(0, CANDIDATE_DIR)
