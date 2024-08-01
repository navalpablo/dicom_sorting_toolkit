# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Collect all submodules of pydicom
pydicom_hidden_imports = collect_submodules('pydicom')

# Collect all submodules of dcm2bids (assuming it's installed)
dcm2bids_hidden_imports = collect_submodules('dcm2bids')

# Collect data files for dcm2bids
dcm2bids_datas = collect_data_files('dcm2bids')

a = Analysis(['GUI_dicom_sorting_tool.py'],
             pathex=[],
             binaries=[],
             datas=[
                 ('dicom_sorting_tool.py', '.'),
                 ('Batch_dcm2bids.py', '.'),
                 # Add path to dcm2niix executable if it's not in PATH
                 # ('/path/to/dcm2niix', '.')
             ] + dcm2bids_datas,
             hiddenimports=pydicom_hidden_imports + dcm2bids_hidden_imports + ['pandas', 'numpy'],
             hookspath=[],
             hooksconfig={},
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

pyz = PYZ(a.pure, a.zipped_data,
          cipher=block_cipher)

exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,  
          [],
          name='DICOM_Sorting_and_BIDS_Tool',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          upx_exclude=[],
          runtime_tmpdir=None,
          console=False,
          disable_windowed_traceback=False,
          target_arch=None,
          codesign_identity=None,
          entitlements_file=None )
