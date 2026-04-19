import sys
import os

# Fix absolute imports for PyInstaller
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from linklocal.cli import cli

if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Default to starting the GUI for users who double-click the EXE
        cli.main(args=["start", "--gui"], prog_name="LinkLocal.exe")
    else:
        cli()
