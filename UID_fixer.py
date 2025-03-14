#!/usr/bin/env python3
"""
fix_uids_with_sop_fix.py

This script recursively scans a folder for DICOM files and fixes noncompliant UID (UI)
fields. For UID fields that are not defined by the standard (such as Study, Series, and
Instance UIDs), noncompliant values are replaced using an organizationally derived scheme,
which mimics the DICOM example:

    "1.2.840.xxxxx.3.152.235.2.12.<unique>"

For the SOP Class UID (tag (0008,0016))—which must be one of the standard, registered values—
if its value is noncompliant it is replaced with a default valid value.
In this example, we assume the images are Secondary Capture and use the UID:
    1.2.840.10008.5.1.4.1.1.7

Usage:
    python fix_uids_with_sop_fix.py <input_folder>
"""

import os
import sys
import hashlib
import logging
import threading
import concurrent.futures

import pydicom
from pydicom.tag import Tag

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Organization-specific constants for building new UIDs (for non-standard UID fields)
ORG_ROOT     = "1.2.840.12345"  # Replace "12345" with your organization's code.
DEVICE_TYPE  = "3"
DEVICE_SERIAL = "152"
STUDY_NUMBER  = "235"
SERIES_NUMBER = "2"
IMAGE_NUMBER  = "12"

# Default valid SOP Class UID.
# For example, for Secondary Capture Image Storage the standard UID is:
DEFAULT_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.7"

def is_valid_uid(uid):
    """
    Check if a UID is compliant with DICOM rules:
      - Non-empty string.
      - Total length ≤ 64 characters.
      - Contains only digits and periods.
      - Each component (separated by periods) is a valid integer with no leading zeros (unless the component is "0").
    """
    if not isinstance(uid, str) or not uid:
        return False
    if len(uid) > 64:
        return False
    components = uid.split('.')
    for comp in components:
        if not comp.isdigit():
            return False
        if len(comp) > 1 and comp.startswith('0'):
            return False
    return True

def generate_org_uid(original_uid, mapping, lock):
    """
    Generate a new UID using an organizationally derived scheme for noncompliant UID fields
    (other than SOP Class UID). The new UID has the format:
    
      ORG_ROOT.DEVICE_TYPE.DEVICE_SERIAL.STUDY_NUMBER.SERIES_NUMBER.IMAGE_NUMBER.<unique>
    
    where <unique> is derived from a SHA‑1 hash of the original UID.
    The result is truncated if necessary so that the final UID is ≤ 64 characters.
    """
    with lock:
        if original_uid in mapping:
            return mapping[original_uid]
        # Compute SHA‑1 hash of the original UID and convert to a decimal string
        hash_digest = hashlib.sha1(original_uid.encode()).hexdigest()
        unique_suffix = str(int(hash_digest, 16))
        # Build the fixed prefix per the example
        prefix = f"{ORG_ROOT}.{DEVICE_TYPE}.{DEVICE_SERIAL}.{STUDY_NUMBER}.{SERIES_NUMBER}.{IMAGE_NUMBER}"
        # Calculate available length for the unique_suffix (plus one for the separator)
        available = 64 - (len(prefix) + 1)
        if len(unique_suffix) > available:
            unique_suffix = unique_suffix[:available]
        new_uid = f"{prefix}.{unique_suffix}"
        mapping[original_uid] = new_uid
        return new_uid

def process_dataset(ds, mapping, lock):
    """
    Recursively process a pydicom Dataset.
    For every element with VR "UI":
      - If the element is SOP Class UID (tag (0008,0016)) and its value is noncompliant,
        replace it with the default valid SOP Class UID.
      - For all other UID elements, if noncompliant, generate a new UID using the
        organizational scheme.
    """
    for elem in ds:
        if elem.VR == "SQ":
            for item in elem.value:
                process_dataset(item, mapping, lock)
        elif elem.VR == "UI":
            # Check if the element is SOP Class UID (0008,0016)
            if elem.tag == Tag(0x0008, 0x0016):
                if not is_valid_uid(elem.value):
                    logging.info(f"Replacing noncompliant SOP Class UID {elem.value} with default {DEFAULT_SOP_CLASS_UID}")
                    elem.value = DEFAULT_SOP_CLASS_UID
                continue  # Do not further process SOP Class UID.
            
            # Process multi-valued UID fields and single UID strings for other tags.
            if isinstance(elem.value, list):
                fixed_values = []
                for uid in elem.value:
                    if not is_valid_uid(uid):
                        fixed_uid = generate_org_uid(uid, mapping, lock)
                        logging.info(f"Fixed UID: {uid} -> {fixed_uid}")
                        fixed_values.append(fixed_uid)
                    else:
                        fixed_values.append(uid)
                elem.value = fixed_values
            elif isinstance(elem.value, str):
                if not is_valid_uid(elem.value):
                    original_uid = elem.value
                    fixed_uid = generate_org_uid(original_uid, mapping, lock)
                    logging.info(f"Fixed UID: {original_uid} -> {fixed_uid}")
                    elem.value = fixed_uid
    return ds

def process_file(filepath, mapping, lock):
    """
    Open a DICOM file, process its dataset to fix UID fields as needed, and overwrite the file.
    Returns True if processing is successful.
    """
    try:
        ds = pydicom.dcmread(filepath, force=True)
    except Exception as e:
        logging.error(f"Failed to read file {filepath}: {e}")
        return False

    ds = process_dataset(ds, mapping, lock)
    try:
        ds.save_as(filepath, write_like_original=False)
        logging.info(f"Processed file: {filepath}")
        return True
    except Exception as e:
        logging.error(f"Failed to save file {filepath}: {e}")
        return False

def process_directory(input_folder):
    """
    Recursively traverse the input folder, collect all files, and process them concurrently.
    """
    mapping = {}  # Shared mapping for consistent UID replacement.
    lock = threading.Lock()  # Protect shared mapping.
    file_list = []
    for root, _, files in os.walk(input_folder):
        for file in files:
            filepath = os.path.join(root, file)
            file_list.append(filepath)
    total_files = len(file_list)
    processed_files = 0

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_file, filepath, mapping, lock) for filepath in file_list]
        for future in concurrent.futures.as_completed(futures):
            try:
                if future.result():
                    processed_files += 1
            except Exception as e:
                logging.error(f"Error processing file: {e}")

    logging.info(f"Processed {processed_files} DICOM files out of {total_files} files scanned.")

def main():
    if len(sys.argv) < 2:
        print("Usage: python fix_uids_with_sop_fix.py <input_folder>")
        sys.exit(1)

    input_folder = os.path.abspath(sys.argv[1])
    if not os.path.isdir(input_folder):
        logging.error(f"Input folder '{input_folder}' does not exist or is not a directory.")
        sys.exit(1)

    logging.info(f"Starting UID fix process in directory: {input_folder}")
    process_directory(input_folder)
    logging.info("UID fix process completed.")

if __name__ == "__main__":
    main()
