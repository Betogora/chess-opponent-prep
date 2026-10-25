#!/usr/bin/env python3
"""Kurzname fuer briefing.py (gleiche Befehle): python prep.py scout|brief|prepare|team ..."""
import os
import sys

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.getcwd())
    from briefing import main
    sys.exit(main())
