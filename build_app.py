r"""Build the portable Windows executable: .venv\Scripts\python.exe build_app.py"""

from pathlib import Path
import os

from base_ui import prepare_tk


if __name__ == '__main__':
    os.chdir(Path(__file__).resolve().parent)
    os.environ['PYINSTALLER_CONFIG_DIR'] = str(Path('build/.pyinstaller-cache').resolve())
    # Make the Tcl/Tk files visible to PyInstaller's build-time discovery.
    prepare_tk()
    from PyInstaller.__main__ import run
    run(['--noconfirm', '--clean', 'RTK Base Reader.spec'])
