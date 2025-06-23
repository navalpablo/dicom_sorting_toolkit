# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Collect all submodules of pydicom
pydicom_hidden_imports = collect_submodules('pydicom')

a = Analysis(
    ['GUI_dicom_sorting_tool.py'],        # your main GUI
    pathex=['C:/Users/h501upnb/Downloads/dicom_sorting_toolkit'],  # adjust if needed
    binaries=[],
    # Include both your helper modules as data files
    datas=[
        ('dicom_sorting_tool.py', '.'),
        ('to_explicit_pydicom.py', '.'),
    ],
    hiddenimports=pydicom_hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure, 
    a.zipped_data,
    cipher=block_cipher
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],                     # runtime hooks go here if you have any
    name='DICOM_Sorting_Tool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # or True if you want a console
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None
)
