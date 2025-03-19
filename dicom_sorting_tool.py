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
import random

# Suppress specific warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pydicom.valuerep")
missing_ids = set()
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

def generate_dummy_date(original_date, anonymize_to_first_of_year=False):
    if not original_date:
        return "20000101"  # Default to January 1, 2000 if no original date
    try:
        original = datetime.strptime(original_date, "%Y%m%d")
        if anonymize_to_first_of_year:
            dummy = datetime(original.year, 1, 1)
        else:
            dummy = original
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

def generate_dummy_accession_number():
    return ''.join([str(random.randint(0, 9)) for _ in range(16)])

def anonymize_dicom_tags(dataset, id_map=None, strict=False, id_from_name=False, anonymize_birth_date=False, 
                        anonymize_acquisition_date=False, preserve_private_tags=False, anonymize_accession=False):
    # List of tags to preserve in both basic and strict anonymization
    preserved_tags = [
        "00080070", "00081090", "00181030", "00189423", "00080020", "00180087",
        "00080080", "00200011", "0008103E", "00540081", "00181310", "00280030",
        "00180088", "00180050", "00180080", "00180081", "00180086", "00180091",
        "00180082", "00181314", "00080008", "00189073", "2001101B", "200110C8",
    #tags for dynamic studies
        "00080032", "00080033", "00200100", "00200110", "00209111", "00189074",
        # Add these Philips private tags that seem important for dynamic studies
        "20050010", # Philips MR Imaging DD 001
        "20050014", # Philips MR Imaging DD 005 
        "20051404", # Remapped from 2005,1004
        "20051406", # Remapped from 2005,1006
        "20010010", # Philips Imaging DD 001
        "20010011", # Philips Imaging DD 002
        "20010090", # Philips Imaging DD 129
        "20051000", "20051001", "20051002", 
        "20051008", "20051009", "2005100a", 
        "20051355"  
    ]

    # Store values of preserved tags
    preserved_values = {tag: dataset.get(tag) for tag in preserved_tags if tag in dataset}

    # Handle PatientID and PatientName
    original_id = dataset.PatientName if id_from_name else dataset.PatientID
    if id_map and original_id in id_map:
        new_id = id_map[original_id]
    else:
        new_id = generate_dummy_id(original_id)
        missing_ids.add(original_id)
    
    dataset.PatientID = new_id
    dataset.PatientName = new_id

    # Handle PatientBirthDate
    if 'PatientBirthDate' in dataset and anonymize_birth_date:
        dataset.PatientBirthDate = generate_dummy_date(dataset.PatientBirthDate, anonymize_to_first_of_year=True)

    # Handle AcquisitionDate
    if 'AcquisitionDate' in dataset and anonymize_acquisition_date:
        dataset.AcquisitionDate = generate_dummy_date(dataset.AcquisitionDate, anonymize_to_first_of_year=True)

    # Handle Accession Number only if anonymization is requested
    if anonymize_accession and '00080050' in dataset:
        dataset.AccessionNumber = generate_dummy_accession_number()

    if strict:
            # Remove all private tags unless preserve_private_tags is True
            if not preserve_private_tags:
                dataset.remove_private_tags()
            
            # List of UIDs to preserve for dynamic studies
            preserved_uids = ['StudyInstanceUID', 'SeriesInstanceUID', 'FrameOfReferenceUID']
            
            # Anonymize other potentially identifying information
            for tag in dataset.dir():
                if tag not in preserved_tags:
                    # Handle Patient-related tags
                    if tag.startswith('Patient'):
                        if tag in ['PatientID', 'PatientName', 'PatientBirthDate']:
                            continue  # Already handled these above
                        elif tag == 'PatientSex':
                            setattr(dataset, tag, 'O')  # 'O' for Other/Unknown
                        elif tag == 'PatientAge':
                            setattr(dataset, tag, '000Y')  # Set to unknown age
                        elif tag in ['PatientWeight', 'PatientSize']:
                            setattr(dataset, tag, '')  # Clear weight and size
                        elif 'Date' in tag:
                            setattr(dataset, tag, generate_dummy_date(getattr(dataset, tag)))
                        elif 'ID' in tag:
                            setattr(dataset, tag, generate_dummy_id(getattr(dataset, tag)))
                        else:
                            setattr(dataset, tag, "ANONYMIZED")
                    
                    # Handle UIDs
                    elif tag.endswith('UID'):
                        if tag in preserved_uids:
                            continue  # Skip modifying these critical UIDs
                        original_uid = getattr(dataset, tag)
                        setattr(dataset, tag, generate_dummy_uid(original_uid))
                        
    # Restore preserved tags
    for tag, value in preserved_values.items():
        setattr(dataset, tag, value)

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

# def is_derived_image(dataset):
#     if 'ImageType' in dataset:
#         image_type = dataset.ImageType
#         return ('PRIMARY' not in image_type) or ('DERIVED' in image_type) or ('SECONDARY' in image_type)
#     return False  # If ImageType is not present, assume it's not derived
# def is_derived_image(dataset):
#     if 'ImageType' in dataset:
#         image_type = dataset.ImageType
#         manufacturer = str(dataset.Manufacturer) if 'Manufacturer' in dataset else ''
#         series_number = str(dataset.SeriesNumber) if 'SeriesNumber' in dataset else ''
#         protocol_name = str(dataset.ProtocolName).lower() if 'ProtocolName' in dataset else ''
#         # is_derived = (
#         #     ('PRIMARY' not in image_type) or
#         #     ('DERIVED' in image_type) or
#         #     ('SECONDARY' in image_type) or
#         #     ('PROJECTION' in image_type) or
#         #     ('RCBV' in image_type) or
#         #     ('Philips' not in manufacturer) or
#         #     (not series_number.endswith('01')) or
#         #     ('surv' in protocol_name) 
#         # )
#         # return is_derived
#         if 'PRIMARY' in image_type:
#             return False
#         if 'DERIVED' in image_type or 'SECONDARY' in image_type or 'PROJECTION' in image_type or 'RCBV' in image_type:
#             return True
#         if 'Philips' in manufacturer:
#             return False
#         if series_number.endswith('01'):
#             return False
#         if 'surv' in protocol_name:
#             return True

#     return False  # If ImageType is not present, assume it's not derived

def is_derived_image(dataset):
    image_type = dataset.ImageType if 'ImageType' in dataset else []
    manufacturer = str(dataset.Manufacturer) if 'Manufacturer' in dataset else ''
    series_number = str(dataset.SeriesNumber) if 'SeriesNumber' in dataset else ''
    series_desc = str(dataset.SeriesDescription).upper() if 'SeriesDescription' in dataset else ''
    
    logging.info(f"Checking image: {series_desc}")
    logging.info(f"ImageType: {image_type}")
    logging.info(f"Manufacturer: {manufacturer}")
    logging.info(f"SeriesNumber: {series_number}")
    logging.info(f"SeriesDescription: {series_desc}")
    
    if 'FLAIR' in series_desc:
        logging.info(f"*** FLAIR image detected: {series_desc} ***")
    
    is_survey = (
        'SURVEY' in series_desc or 
        'SURV' in series_desc or
        'SMART' in series_desc or
        'SCOUT' in series_desc or
        'SV' in series_desc 
    )
    
    
    
    has_projection = any("PROJECTION" in item for item in image_type)
    has_derived = any("DERIVED" in item for item in image_type)
    has_primary = any("PRIMARY" in item for item in image_type)
    has_RCBV = any("RCBV" in item for item in image_type)
    has_secondary = any("SECONDARY" in item for item in image_type)
    has_adc = any("ADC" in item for item in image_type)
    
    is_derived = (
        not has_primary or
        'Philips' not in manufacturer or
        has_projection or
        has_RCBV or
        has_derived or
        has_secondary or
        has_adc or
        'REG' in series_desc or
        'ADC' in series_desc or
       # (not series_number.endswith('01')) or
        is_survey
    )
    
    if is_derived:
        reasons = []

        if not has_primary:
            reasons.append('Not PRIMARY')
        if has_derived:
            reasons.append('DERIVED found')
        if has_secondary:
            reasons.append('SECONDARY found')
        if has_projection:
            reasons.append('PROJECTION found')
        if has_RCBV:
            reasons.append('RCBV found')
        if has_adc:
            reasons.append('ADC found')
        if 'Philips' not in manufacturer:
            reasons.append('Not Philips')
        if 'REG' not in series_desc:
            reasons.append('Reg series')
        if 'ADC' not in series_desc:
            reasons.append('ADC series')
        if is_survey:
            reasons.append('Survey image')

            logging.info(f"Image marked as derived because: {', '.join(reasons)}")
    else:
        logging.info("Image not marked as derived")
        
    return is_derived
    

def has_burned_in_annotation(dataset):
    return dataset.get('BurnedInAnnotation', '').upper() == 'YES'


def copy_dicom_image(src_file, dest_base_dir, pattern, anonymize=False, id_map=None, decompress=False, strict_anonymize=False, id_from_name=False, anonymize_birth_date=False, anonymize_acquisition_date=False, preserve_private_tags=False, anonymize_accession=False):
    non_dicom_extensions = ['.png', '.jpeg', '.jpg', '.gif', '.bmp']
    if any(src_file.lower().endswith(ext) for ext in non_dicom_extensions):
        return

    try:
        dataset = pydicom.dcmread(src_file, force=True)
        logging.info(f"\nIn copy_dicom_image for file: {src_file}")
        logging.info(f"Copy phase - Tags:")
        logging.info(f"SeriesNumber: {dataset.get('SeriesNumber', 'NOT_FOUND')}")
        logging.info(f"SeriesDescription: {dataset.get('SeriesDescription', 'NOT_FOUND')}")
        
    except Exception as e:
        logging.error(f'Error reading DICOM file {src_file}: {str(e)}')
        return

    if anonymize or id_map:
        dataset = anonymize_dicom_tags(dataset, id_map, strict_anonymize, id_from_name, 
                                     anonymize_birth_date, anonymize_acquisition_date, 
                                     preserve_private_tags, anonymize_accession)

    if decompress:                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    
        dataset = decompress_dataset(dataset)

    # Combine SeriesNumber and SeriesDescription
    series_number = get_dicom_attribute(dataset, 'SeriesNumber').zfill(3)  # Pad with zeros to ensure proper sorting
    series_description = sanitize_series_description(get_dicom_attribute(dataset, 'SeriesDescription'))
    series_uid = get_dicom_attribute(dataset, 'SeriesInstanceUID')
    uid_suffix = series_uid.split('.')[-1][-5:]  
    series_dir = f"{series_number}_{series_description}_{uid_suffix}"

    # Handle StudyDate for folder structure
    study_date = get_dicom_attribute(dataset, 'StudyDate')
    if anonymize_acquisition_date and study_date != 'UNKNOWN':
        # If acquisition date is anonymized, use YYYY0101 format for the folder
        study_date = study_date[:4] + '0101'

    # Replace placeholders in the pattern
    pattern = pattern.replace('%PatientID%', get_dicom_attribute(dataset, 'PatientID'))
    pattern = pattern.replace('%StudyDate%', study_date)
    pattern = pattern.replace('%SeriesDescription%', series_dir)

    dest_directory = sanitize_filepath(os.path.join(dest_base_dir, pattern), platform='auto')
    os.makedirs(dest_directory, exist_ok=True)
    
    sop_instance_uid = get_dicom_attribute(dataset, 'SOPInstanceUID')
    new_filename = f"{sop_instance_uid}.dcm"
    dataset.save_as(os.path.join(dest_directory, new_filename))

def copy_directory(src_dir, dest_dir, pattern, anonymize, id_map, decompress, strict_anonymize, skip_derived, skip_burned_in, id_from_name, anonymize_birth_date, anonymize_acquisition_date, preserve_private_tags, anonymize_accession, progress_callback=None, cancel_flag=None):
    all_files = [os.path.join(root, file) for root, _, files in os.walk(src_dir) for file in files]
    total_files = len(all_files)
    
    args_list = [(file, dest_dir, pattern, anonymize, id_map, decompress, strict_anonymize, skip_derived, skip_burned_in, id_from_name, anonymize_birth_date, anonymize_acquisition_date, preserve_private_tags, anonymize_accession) for file in all_files]

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
    
def sort_dicom(input_dir, output_dir, anonymize, id_map, decompress, strict_anonymize, skip_derived, 
               skip_burned_in, id_from_name, anonymize_birth_date, anonymize_acquisition_date, 
               preserve_private_tags, anonymize_accession=False, progress_callback=None, cancel_flag=None):
    pattern = '%PatientID%/%StudyDate%/%SeriesDescription%'
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    copy_directory(input_dir, output_dir, pattern, anonymize, id_map, decompress, strict_anonymize, 
                   skip_derived, skip_burned_in, id_from_name, anonymize_birth_date, 
                   anonymize_acquisition_date, preserve_private_tags, anonymize_accession,
                   progress_callback, cancel_flag)

def process_file(args):
    file, dest_dir, pattern, anonymize, id_map, decompress, strict_anonymize, skip_derived, skip_burned_in, id_from_name, anonymize_birth_date, anonymize_acquisition_date, preserve_private_tags, anonymize_accession = args
    try:
        dataset = pydicom.dcmread(file, force=True)
        # series_desc = str(dataset.SeriesDescription) if 'SeriesDescription' in dataset else 'NO_DESC'
        
        logging.info(f"\nProcessing file: {file}")
        logging.info(f"Initial read - Tags:")
        logging.info(f"SeriesNumber: {dataset.get('SeriesNumber', 'NOT_FOUND')}")
        logging.info(f"SeriesDescription: {dataset.get('SeriesDescription', 'NOT_FOUND')}")
        logging.info(f"ProtocolName: {dataset.get('ProtocolName', 'NOT_FOUND')}")
        logging.info(f"ImageType: {dataset.get('ImageType', 'NOT_FOUND')}")
        
        if skip_derived:
            is_derived = is_derived_image(dataset)
            if is_derived:
                logging.info(f"SKIPPING derived image")
                return file, False
            else:
                logging.info(f"NOT derived, will process")


        if skip_burned_in and has_burned_in_annotation(dataset):
            logging.info(f"Skipping image with burned-in annotation: {file}")
            return file, False

        copy_dicom_image(file, dest_dir, pattern, anonymize, id_map, decompress, strict_anonymize, 
                        id_from_name, anonymize_birth_date, anonymize_acquisition_date, preserve_private_tags,
                        anonymize_accession)
        return file, True
    except Exception as e:
        logging.error(f"Error processing file {file}: {str(e)}")
        return file, False
        
        
def main():
    parser = argparse.ArgumentParser(description="This script copies, optionally anonymizes, and optionally decompresses DICOM files into a structured directory.", 
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('--dicomin', type=str, required=True, help='Path to the input directory containing unsorted DICOM files.')
    parser.add_argument('--dicomout', type=str, required=True, help='Path to the output directory where structured and optionally anonymized DICOM files will be stored.')
    parser.add_argument('--anonymize', action='store_true', help='If specified, anonymizes DICOM tags such as PatientName and PatientID.')
    parser.add_argument('--anonymize_strict', action='store_true', help='If specified, performs stricter anonymization, including removal of private tags and anonymizing additional fields.')
    parser.add_argument('--ID_correlation', type=str, help='Optional path to a correlation file mapping old PatientIDs to new PatientIDs. \nExpected format: oldID,newID per line.')
    parser.add_argument('--decompress', action='store_true', help='If specified, decompresses DICOM files during processing.')
    parser.add_argument('--skip_derived', action='store_true', help='If specified, skips DICOM files that are derived or secondary images.')
    parser.add_argument('--skip_burned_in_images', action='store_true', help='If specified, skips DICOM files with burned-in annotations.')
    parser.add_argument('--id_from_name', action='store_true', help='If specified, reads the original ID from PatientName instead of PatientID for ID correlation.')
    parser.add_argument('--anonymize_birth_date', action='store_true', help='If specified, anonymizes the PatientBirthDate to January 1st of the same year.')
    parser.add_argument('--anonymize_acquisition_date', action='store_true', help='If specified, anonymizes the AcquisitionDate to January 1st of the same year.')
    parser.add_argument('--preserve_private_tags', action='store_true', help='If specified, preserves private tags even in strict anonymization mode.')
    parser.add_argument('--anonymize_accession', action='store_true', help='If specified, anonymizes the Accession Number with a random 16-digit number.')
    args = parser.parse_args()

    id_map = read_id_correlation(args.ID_correlation) if args.ID_correlation else None

    start_time = time.time()

    sort_dicom(args.dicomin, args.dicomout, 
               args.anonymize or args.anonymize_strict, 
               id_map, 
               args.decompress, 
               args.anonymize_strict, 
               args.skip_derived, 
               args.skip_burned_in_images, 
               args.id_from_name,
               args.anonymize_birth_date,
               args.anonymize_acquisition_date,
               args.preserve_private_tags,
               args.anonymize_accession)

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
