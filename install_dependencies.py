"""Create a project virtual environment and install runtime/build dependencies."""

import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='Verify an existing installation without downloading anything')
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        parser.error('Python 3.10 or newer is required. Install Python with Tcl/Tk enabled.')
    root = Path(__file__).resolve().parent
    interpreter = root / '.venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    try:
        if args.check and not interpreter.is_file():
            parser.error('No project virtual environment found. Run this script without --check first.')
        if not args.check:
            if not interpreter.is_file():
                subprocess.run([sys.executable, '-m', 'venv', str(root / '.venv')], check=True)
            subprocess.run([str(interpreter), '-m', 'pip', 'install', '--upgrade', 'pip'], check=True)
            subprocess.run([str(interpreter), '-m', 'pip', 'install', '-r',
                            str(root / 'requirements-build.txt')], check=True)
        subprocess.run([str(interpreter), '-m', 'pip', 'check'], check=True)
        subprocess.run([str(interpreter), '-c',
                        'import tkinter, pymavlink, pyrtcm, tkintermapview, requests, PyInstaller; '
                        'from base_ui import prepare_tk; prepare_tk(); '
                        'tkinter.Tcl(); print("Dependency imports and Tcl support verified.")'],
                       cwd=root, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f'\nSetup failed: {exc}\nCheck your Python installation and internet connection, then retry.',
              file=sys.stderr)
        return 1
    print('\nSetup complete. Double-click Open RTK Reader.bat to launch.\n'
          'To build the executable: .venv\\Scripts\\python.exe build_app.py')
    return 0


if __name__ == '__main__':
    sys.exit(main())
