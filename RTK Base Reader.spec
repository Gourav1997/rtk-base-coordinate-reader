# Rebuild with: .venv\Scripts\python.exe build_app.py
import os
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files('customtkinter') + collect_data_files('certifi') + [('LICENSE', '.')]
# Explicitly include Tcl/Tk support for Python distributions with zipped libraries.
for variable, destination in [('TCL_LIBRARY', '_tcl_data'), ('TK_LIBRARY', '_tk_data')]:
    if os.environ.get(variable):
        datas.append((os.environ[variable], destination))

a = Analysis(
    ['base_ui.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'pymavlink.dialects.v10.ardupilotmega',
        'pymavlink.dialects.v20.ardupilotmega',
        'pymavlink.dialects.v10.common',
        'pymavlink.dialects.v20.common',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['pytest', 'IPython', 'matplotlib', 'numpy'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='RTK Base Reader',
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
