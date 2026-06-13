"""Thin wrapper — run 'python tools/tune_rows.py' from source as before."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from row_tuner import main

if __name__ == "__main__":
    main()
