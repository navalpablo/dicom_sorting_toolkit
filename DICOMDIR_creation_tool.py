#!/usr/bin/env python3
"""
DICOMDIR_creation_tool.py

This script organizes a tree of unorganized DICOM files (which might not have an extension)
into a structured hierarchy with sequential folder and file names meeting DICOMDIR requirements.
Folders are named with fixed 7-character basenames:
  - Patients: PA00001, PA00002, … 
  - Studies:  ST00001, ST00002, … (within each patient)
  - Series:   SE00001, SE00002, … (within each study; if a series has more than 1000 images,
             the series is split across multiple SE folders)
  - Images:   DI00001, DI00002, … (no extension is added)
Duplicate images (i.e. with the same SeriesInstanceUID and SOPInstanceUID) are discarded.
After sorting, the script calls the dcmmkdir utility to create a DICOMDIR file.

Additionally, before saving, the script converts files from LittleEndianImplicit to
LittleEndianExplicit (if needed) so that dcmmkdir will accept them.
    
Usage:
    python DICOMDIR_creation_tool.py --dicomin /path/to/input --dicomout /path/to/output
"""

import os
import sys
import argparse
import logging
import subprocess
from math import ceil

import pydicom
from pydicom.errors import InvalidDicomError
from pydicom.uid import ExplicitVRLittleEndian
from tqdm import tqdm

# Maximum images per series folder
MAX_IMAGES_PER_FOLDER = 1000

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def format_code(prefix, number):
    """
    Return a code with the given prefix and a 5-digit number.
    e.g. prefix="PA", number=1 returns "PA00001"
    """
    return f"{prefix}{number:05d}"


def check_output_directory(out_dir):
    """Create the output directory if needed. If it exists and is not empty, raise an error."""
    if os.path.exists(out_dir):
        if os.listdir(out_dir):
            logging.error(f"Output directory '{out_dir}' is not empty.")
            sys.exit(f"Error: Output directory '{out_dir}' must be empty.")
    else:
        os.makedirs(out_dir)
        logging.info(f"Created output directory: {out_dir}")


def is_dicom_file(filepath):
    """
    Try to read the file with pydicom.
    Returns the dataset if valid, else None.
    Uses stop_before_pixels for performance.
    """
    try:
        ds = pydicom.dcmread(filepath, stop_before_pixels=True, force=True)
        # Minimal check: must have SOPInstanceUID
        if hasattr(ds, 'SOPInstanceUID'):
            return ds
    except (InvalidDicomError, Exception):
        pass
    return None


def normalize_sh(ds):
    """
    Recursively traverse the dataset and trim any SH (Short String) values
    that exceed the 16-character limit.
    """
    for elem in ds:
        if elem.VR == "SH" and isinstance(elem.value, str) and len(elem.value) > 16:
            new_val = elem.value[:16]
            logging.info(f"Trimming SH value of tag {elem.tag} from {elem.value} to {new_val}")
            elem.value = new_val
        elif elem.VR == "SQ":
            for item in elem.value:
                normalize_sh(item)
    return ds

from pydicom.uid import ExplicitVRLittleEndian

def convert_to_explicit(ds):
    """
    Convert the dataset to use Explicit VR Little Endian.
    If the dataset is compressed, decompress it first.
    Then, normalize any SH (Short String) values to be 16 characters or less.
    """
    if ds.file_meta.TransferSyntaxUID != ExplicitVRLittleEndian:
        try:
            ds.decompress()
            logging.info("Decompressed dataset successfully.")
        except Exception as e:
            logging.error(f"Failed to decompress dataset: {e}")
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.is_implicit_VR = False
    ds = normalize_sh(ds)
    return ds


def scan_input_directory(in_dir):
    """
    Walk through the input directory recursively.
    Returns a nested dictionary:
      data[patient_id][study_instance_uid][series_instance_uid] = list of filepaths
    Also removes duplicate images based on (SeriesInstanceUID, SOPInstanceUID).
    """
    data = {}
    seen_images = set()
    total_files = 0
    valid_files = 0

    for root, _, files in os.walk(in_dir):
        for file in files:
            total_files += 1
            full_path = os.path.join(root, file)
            ds = is_dicom_file(full_path)
            if ds is None:
                continue

            # Ensure the key attributes exist; if not, use "UNKNOWN"
            patient_id = getattr(ds, "PatientID", "UNKNOWN")
            study_uid = getattr(ds, "StudyInstanceUID", "UNKNOWN")
            series_uid = getattr(ds, "SeriesInstanceUID", "UNKNOWN")
            sop_uid = getattr(ds, "SOPInstanceUID", None)
            if sop_uid is None:
                continue

            key_image = (series_uid, sop_uid)
            if key_image in seen_images:
                # Duplicate image found; skip it.
                logging.info(f"Duplicate found, skipping file: {full_path}")
                continue
            seen_images.add(key_image)
            valid_files += 1

            data.setdefault(patient_id, {})
            data[patient_id].setdefault(study_uid, {})
            data[patient_id][study_uid].setdefault(series_uid, [])
            data[patient_id][study_uid][series_uid].append(full_path)

    logging.info(f"Scanned {total_files} files, found {valid_files} valid DICOM files.")
    return data


def copy_sorted_files(data, out_dir):
    """
    Copy DICOM files into the output directory using sequential naming.
    The directory structure is:
      out_dir/PAxxxxx/STxxxxx/SExxxxx/DIxxxxx
    If a series has more than MAX_IMAGES_PER_FOLDER images, it is split into multiple series folders.
    Files are re-read and re-saved with Explicit VR Little Endian to meet DICOMDIR requirements.
    """
    patient_counter = 1

    # Loop over patients sorted by original patient ID (for reproducibility)
    for patient_id in sorted(data.keys()):
        patient_code = format_code("PA", patient_counter)
        patient_dir = os.path.join(out_dir, patient_code)
        os.makedirs(patient_dir, exist_ok=True)
        logging.info(f"Created patient folder: {patient_dir}")

        study_counter = 1
        # Process each study for this patient
        for study_uid in sorted(data[patient_id].keys()):
            study_code = format_code("ST", study_counter)
            study_dir = os.path.join(patient_dir, study_code)
            os.makedirs(study_dir, exist_ok=True)
            logging.info(f"  Created study folder: {study_dir}")

            series_counter = 1  # For naming series folders within this study

            # Process each series in the study
            for series_uid in sorted(data[patient_id][study_uid].keys()):
                file_list = data[patient_id][study_uid][series_uid]
                num_images = len(file_list)
                # Determine how many series folders are needed for this series group
                num_folders = ceil(num_images / MAX_IMAGES_PER_FOLDER)

                # Sort the images in some order (for example by filename)
                file_list = sorted(file_list)

                for folder_index in range(num_folders):
                    series_code = format_code("SE", series_counter)
                    series_dir = os.path.join(study_dir, series_code)
                    os.makedirs(series_dir, exist_ok=True)
                    logging.info(f"    Created series folder: {series_dir}")

                    # For each folder, reset image counter
                    image_counter = 1
                    start = folder_index * MAX_IMAGES_PER_FOLDER
                    end = start + MAX_IMAGES_PER_FOLDER
                    for src_filepath in file_list[start:end]:
                        dest_filepath = os.path.join(series_dir, format_code("DI", image_counter))
                        try:
                            # Read the full dataset (force=True)
                            ds = pydicom.dcmread(src_filepath, force=True)
                            ds = convert_to_explicit(ds)
                            ds.save_as(dest_filepath, write_like_original=False)
                        except Exception as e:
                            logging.error(f"Error converting file {src_filepath} to explicit VR: {e}")
                        image_counter += 1
                    series_counter += 1
            study_counter += 1
        patient_counter += 1


def create_dicomdir(out_dir):
    """
    Call the dcmmkdir command to create a DICOMDIR file in the output directory.
    The DICOMDIR file will be created as out_dir/DICOMDIR.
    """
    dicomdir_path = os.path.join(out_dir, "DICOMDIR")
    command = [
        "dcmmkdir",
        "+r",            # Recurse
        "+id", out_dir,  # Set the input directory to the sorted output
        "+D", dicomdir_path,  # Specify the output DICOMDIR file
        "-Pgp",          # Use general purpose profile (for CD/DVD media)
        "-A",            # Replace existing DICOMDIR
        "+I"             # Invent missing type 1 attributes if needed
    ]
    logging.info(f"Running dcmmkdir command: {' '.join(command)}")
    try:
        subprocess.run(command, check=True)
        logging.info(f"DICOMDIR created successfully at {dicomdir_path}")
    except subprocess.CalledProcessError as e:
        logging.error(f"dcmmkdir failed: {e}")
        sys.exit("Error: Failed to create DICOMDIR using dcmmkdir.")


def main():
    parser = argparse.ArgumentParser(
        description="Sort unorganized DICOM files into a DICOMDIR-compliant structure and create a DICOMDIR file."
    )
    parser.add_argument("--dicomin", type=str, required=True, help="Input directory containing unorganized DICOM files.")
    parser.add_argument("--dicomout", type=str, required=True, help="Output directory for sorted DICOM files and DICOMDIR file.")
    args = parser.parse_args()

    input_dir = os.path.abspath(args.dicomin)
    output_dir = os.path.abspath(args.dicomout)

    logging.info(f"Input directory: {input_dir}")
    logging.info(f"Output directory: {output_dir}")

    # Check output directory: it must be empty (or not exist)
    check_output_directory(output_dir)

    # Scan and group the input DICOM files
    data = scan_input_directory(input_dir)
    if not data:
        logging.error("No valid DICOM files found in the input directory.")
        sys.exit("Error: No valid DICOM files found.")

    # Copy files into the new structure with conversion as needed
    copy_sorted_files(data, output_dir)

    # Create the DICOMDIR file using dcmmkdir
    create_dicomdir(output_dir)


if __name__ == '__main__':
    main()
