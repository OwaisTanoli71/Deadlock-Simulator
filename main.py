"""
Deadlock Detection & Recovery Simulator
Entry point — run this file to launch the GUI.
"""

import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.main_window import main

if __name__ == "__main__":
    main()
