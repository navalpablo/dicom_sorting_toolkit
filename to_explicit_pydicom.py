#!/usr/bin/env python3
"""to_explicit_pydicom.py – recursively decompress (if needed) and
   rewrite every DICOM as Explicit VR Little Endian, in-place."""
import os, argparse, multiprocessing as mp, pydicom
from pydicom.uid import ExplicitVRLittleEndian
from tqdm import tqdm

def convert(path: str):
    try:
        ds = pydicom.dcmread(path, force=True)          # force=True handles odd files
        # 1. Decompress if transfer-syntax is compressed
        if ds.file_meta.TransferSyntaxUID.is_compressed:
            ds.decompress()                             # needs pylibjpeg or gdcm
        # 2. Ensure file-meta exists and set new transfer syntax
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.is_little_endian = True
        ds.is_implicit_VR  = False
        ds.save_as(path, write_like_original=False)
        return True, ''
    except Exception as e:
        return False, str(e)

def walk(root):
    files = [os.path.join(r, f)
             for r, _, fs in os.walk(root) for f in fs]
    ok = err = 0
    with mp.Pool() as pool, tqdm(total=len(files), unit='file') as bar:
        for success, msg in pool.imap_unordered(convert, files):
            ok += success
            err += (not success)
            bar.set_postfix(success=ok, errors=err)
            bar.update()
            if msg:
                bar.write(f"⚠️  {msg}")

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description="Make every DICOM Explicit VR LE")
    ap.add_argument("path", help="Root directory")
    walk(ap.parse_args().path)
