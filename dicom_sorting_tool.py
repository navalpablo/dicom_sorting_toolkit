#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import argparse
import pydicom
from pathvalidate import sanitize_filepath
from tqdm import tqdm
import re
import multiprocessing
import logging
import time
from datetime import datetime
import hashlib
import warnings


# Suppress specific warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pydicom.valuerep")

# Set up logging
log_file = 'dicom_processing.log'
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    filename=log_file,
                    filemode='w')

# Add console handler for error messages only
console = logging.StreamHandler()
console.setLevel(logging.ERROR)
formatter = logging.Formatter('%(levelname)s: %(message)s')
console.setFormatter(formatter)
logging.getLogger('').addHandler(console)

def get_dicom_attribute(dataset, attribute):
    try:
        return str(getattr(dataset, attribute))
    except AttributeError:
        return 'UNKNOWN'

def read_id_correlation(file_path):
    id_map = {}
    if file_path:
        with open(file_path, 'r') as file:
            for line in file:
                parts = re.split(r',|\s|\t', line.strip())
                if len(parts) >= 2:
                    old_id, new_id = parts[0], parts[1]
                    id_map[old_id] = new_id
                else:
                    logging.warning(f"Invalid line format: {line}")
    return id_map

def generate_dummy_date(original_date):
    if not original_date:
        return "20000101"  # Default to January 1, 2000 if no original date
    try:
        original = datetime.strptime(original_date, "%Y%m%d")
        dummy = datetime(2000, 1, 1) + (original - datetime(original.year, 1, 1))
        return dummy.strftime("%Y%m%d")
    except ValueError:
        return "20000101"  # Return default if original date is invalid

def generate_dummy_id(original_id):
    # Generate a consistent dummy ID based on the hash of the original ID
    hash_object = hashlib.md5(original_id.encode())
    return hash_object.hexdigest()[:8]  # Use first 8 characters of the hash


def generate_dummy_uid(original_uid):
    # Keep the prefix (1.2.840...) and replace the rest with numeric hash
    uid_parts = original_uid.split('.')
    prefix = '.'.join(uid_parts[:4])  # Keep the first 4 parts of the UID
    
    # Generate a numeric hash
    hash_object = hashlib.sha256(original_uid.encode())
    numeric_hash = ''.join([str(int(c, 16)) for c in hash_object.hexdigest()])
    
    # Use the first 16 digits of the numeric hash
    return f"{prefix}.{numeric_hash[:16]}"
    
    
def anonymize_dicom_tags(dataset, id_map=None, strict=False):
    # Keep SeriesDescription and StudyDescription
    series_description = dataset.get('SeriesDescription', '')
    study_description = dataset.get('StudyDescription', '')
    study_date = dataset.get('StudyDate', '')  # Preserve StudyDate

    # Handle PatientID first
    if 'PatientID' in dataset:
        if id_map and dataset.PatientID in id_map:
            dataset.PatientID = id_map[dataset.PatientID]
        else:
            dataset.PatientID = generate_dummy_id(dataset.PatientID)
            missing_ids.add(dataset.PatientID)
    
    # Set PatientName to be the same as PatientID
    if 'PatientName' in dataset:
        dataset.PatientName = dataset.PatientID
    
    if 'PatientBirthDate' in dataset:
        dataset.PatientBirthDate = generate_dummy_date(dataset.PatientBirthDate)

    if strict:
        # Remove all private tags
        dataset.remove_private_tags()
        
        # Anonymize other potentially identifying information
        for tag in dataset.dir():
            if tag.startswith('Patient'):
                if tag in ['PatientID', 'PatientName', 'PatientBirthDate']:
                    continue  # We've already handled these above
                elif tag in ['PatientSex', 'PatientAge', 'PatientWeight', 'PatientSize']:
                    # We now handle these fields in strict mode
                    if tag == 'PatientSex':
                        setattr(dataset, tag, 'O')  # 'O' for Other/Unknown
                    elif tag == 'PatientAge':
                        setattr(dataset, tag, '000Y')  # Set to unknown age
                    else:
                        setattr(dataset, tag, '')  # Clear weight and size
                elif 'Date' in tag and tag != 'StudyDate':
                    setattr(dataset, tag, generate_dummy_date(getattr(dataset, tag)))
                elif 'ID' in tag:
                    setattr(dataset, tag, generate_dummy_id(getattr(dataset, tag)))
                else:
                    setattr(dataset, tag, "ANONYMIZED")
        
        # Only anonymize UIDs in strict mode
        for tag in dataset.dir():
            if tag.endswith('UID'):
                original_uid = getattr(dataset, tag)
                setattr(dataset, tag, generate_dummy_uid(original_uid))

    # Restore SeriesDescription, StudyDescription, and StudyDate
    if series_description:
        dataset.SeriesDescription = series_description
    if study_description:
        dataset.StudyDescription = study_description
    if study_date:
        dataset.StudyDate = study_date

    return dataset

def generate_unique_filename(directory, filename):
    base_name, extension = os.path.splitext(filename)
    counter = 1
    new_filename = filename
    while os.path.exists(os.path.join(directory, new_filename)):
        new_filename = f"{base_name}_{counter}{extension}"
        counter += 1
    return new_filename

def sanitize_series_description(description):
    description = description.replace(' ', '_').replace('*', '').replace('.', '_')
    invalid_chars = r'<>:"/\|?*'
    description = re.sub(f'[{re.escape(invalid_chars)}]', '', description)
    return sanitize_filepath(description, platform='auto')

def decompress_dataset(dataset):
    try:
        dataset.decompress()
    except Exception as e:
        logging.error(f"Error decompressing dataset: {str(e)}")
    return dataset

def is_derived_image(dataset):
    if 'ImageType' in dataset:
        image_type = dataset.ImageType
        return ('PRIMARY' not in image_type) or ('DERIVED' in image_type) or ('SECONDARY' in image_type)
    return False  # If ImageType is not present, assume it's not derived

def has_burned_in_annotation(dataset):
    return dataset.get('BurnedInAnnotation', '').upper() == 'YES'

def copy_dicom_image(src_file, dest_base_dir, pattern, anonymize=False, id_map=None, decompress=False, strict_anonymize=False):
    non_dicom_extensions = ['.png', '.jpeg', '.jpg', '.gif', '.bmp']
    if any(src_file.lower().endswith(ext) for ext in non_dicom_extensions):
        return

    try:
        dataset = pydicom.dcmread(src_file)
    except Exception as e:
        logging.error(f'Error reading DICOM file {src_file}: {str(e)}')
        return

    if anonymize or id_map:
        dataset = anonymize_dicom_tags(dataset, id_map, strict_anonymize)

    if decompress:
        dataset = decompress_dataset(dataset)

    for attribute in ['PatientID', 'StudyDate', 'SeriesNumber', 'SeriesDescription']:
        value = get_dicom_attribute(dataset, attribute)
        if attribute == 'SeriesDescription':
            value = sanitize_series_description(value)
        pattern = pattern.replace(f'%{attribute}%', value)

    dest_directory = sanitize_filepath(os.path.join(dest_base_dir, pattern), platform='auto')
    os.makedirs(dest_directory, exist_ok=True)
    
    unique_filename = generate_unique_filename(dest_directory, os.path.basename(src_file))
    dataset.save_as(os.path.join(dest_directory, unique_filename))



def process_file(args):
    file, dest_dir, pattern, anonymize, id_map, decompress, strict_anonymize, skip_derived, skip_burned_in = args
    try:
        dataset = pydicom.dcmread(file)
        
        if skip_derived and is_derived_image(dataset):
            logging.info(f"Skipping derived image: {file}")
            return file, False

        if skip_burned_in and has_burned_in_annotation(dataset):
            logging.info(f"Skipping image with burned-in annotation: {file}")
            return file, False

        copy_dicom_image(file, dest_dir, pattern, anonymize, id_map, decompress, strict_anonymize)
        return file, True
    except Exception as e:
        logging.error(f"Error processing file {file}: {str(e)}")
        return file, False

def copy_directory(src_dir, dest_dir, pattern, anonymize, id_map, decompress, strict_anonymize, skip_derived, skip_burned_in, progress_callback=None, cancel_flag=None):
    all_files = [os.path.join(root, file) for root, _, files in os.walk(src_dir) for file in files]
    total_files = len(all_files)
    
    args_list = [(file, dest_dir, pattern, anonymize, id_map, decompress, strict_anonymize, skip_derived, skip_burned_in) for file in all_files]

    success_count = 0
    failure_count = 0

    with multiprocessing.Pool(processes=multiprocessing.cpu_count()) as pool:
        for i, (file, success) in enumerate(pool.imap_unordered(process_file, args_list)):
            if cancel_flag and cancel_flag.value:
                pool.terminate()
                logging.info("Sorting process was cancelled.")
                return

            if success:
                success_count += 1
            else:
                failure_count += 1
            if progress_callback:
                progress_callback(int((i + 1) / total_files * 100))

    print(f"\nProcessing completed. Successes: {success_count}, Failures: {failure_count}")
    logging.info(f"Processing completed. Successes: {success_count}, Failures: {failure_count}")

def sort_dicom(input_dir, output_dir, anonymize, id_map, decompress, strict_anonymize, skip_derived, skip_burned_in, progress_callback=None, cancel_flag=None):
    pattern = '%PatientID%/%StudyDate%/%SeriesDescription%'
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    copy_directory(input_dir, output_dir, pattern, anonymize, id_map, decompress, strict_anonymize, skip_derived, skip_burned_in, progress_callback, cancel_flag)

missing_ids = set()

def main():
    parser = argparse.ArgumentParser(description="This script copies, optionally anonymizes, and optionally decompresses DICOM files into a structured directory. It can also replace PatientID based on a correlation file.",
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('--dicomin', type=str, required=True, help='Path to the input directory containing unsorted DICOM files.')
    parser.add_argument('--dicomout', type=str, required=True, help='Path to the output directory where structured and optionally anonymized DICOM files will be stored.')
    parser.add_argument('--anonymize', action='store_true', help='If specified, anonymizes DICOM tags such as PatientName and PatientBirthDate.')
    parser.add_argument('--anonymize_strict', action='store_true', help='If specified, performs stricter anonymization, including removal of private tags and anonymizing additional fields.')
    parser.add_argument('--ID_correlation', type=str, help='Optional path to a correlation file mapping old PatientIDs to new PatientIDs. \nExpected format: oldID,newID per line.')
    parser.add_argument('--decompress', action='store_true', help='If specified, decompresses DICOM files during processing.')
    parser.add_argument('--skip_derived', action='store_true', help='If specified, skips DICOM files that are derived or secondary images.')
    parser.add_argument('--skip_burned_in_images', action='store_true', help='If specified, skips DICOM files with burned-in annotations.')
    args = parser.parse_args()


    id_map = read_id_correlation(args.ID_correlation) if args.ID_correlation else None

    start_time = time.time()
    sort_dicom(args.dicomin, args.dicomout, args.anonymize or args.anonymize_strict, id_map, args.decompress, args.anonymize_strict, args.skip_derived, args.skip_burned_in_images)
    end_time = time.time()

    print(f"Total processing time: {end_time - start_time:.2f} seconds")
    logging.info(f"Total processing time: {end_time - start_time:.2f} seconds")

    if missing_ids:
        log_file_path = 'missing_patient_ids.log'
        with open(log_file_path, 'w') as log_file:
            for missing_id in missing_ids:
                log_file.write(f'{missing_id}\n')
        print(f"Missing PatientIDs logged in '{log_file_path}'.")
        logging.info(f"Missing PatientIDs logged in '{log_file_path}'.")

if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()