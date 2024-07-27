import os
import argparse
import pydicom
import warnings
import csv
import logging
from collections import OrderedDict
from tqdm import tqdm

warnings.filterwarnings("ignore", category=UserWarning, module="pydicom.valuerep")

def setup_logging(log_file):
    logging.basicConfig(filename=log_file, level=logging.WARNING, 
                        format='%(asctime)s - %(levelname)s - %(message)s')

def find_dicom_files(directory, read_all):
    dicom_files = []
    for root, dirs, files in os.walk(directory):
        for f in files:
            file_path = os.path.join(root, f)
            dicom_files.append(file_path)
    
    if not read_all:
        dicom_files = dicom_files[:5]
    return dicom_files

def hex_string_to_tag(hex_str):
    group, element = hex_str[:4], hex_str[4:]
    return (int(group, 16), int(element, 16))

def extract_dicom_info(file_path, fields):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            dicom = pydicom.dcmread(file_path, force=True)
        info = OrderedDict()
        for field in fields:
            tag = hex_string_to_tag(field)
            if tag in dicom:
                value = str(dicom[tag].value)
                info[field] = value
            else:
                info[field] = ''
        return info
    except Exception as e:
        logging.error(f"Error reading DICOM file {file_path}: {e}")
        return None

def main(dicom_dir, output_path, read_all=False):
    log_file = output_path.replace('.tsv', '.log')
    setup_logging(log_file)
    
    logging.warning(f"Starting script. Directory: {dicom_dir}, Output: {output_path}, Read all: {read_all}")

    dicom_field_mapping = {
        "00100020": "Patient ID",
        "00080020": "Study Date",
        "00180087": "Magnetic Field Strength",
        "00081090": "Manufacturer's Model Name",
        "00080080": "Institution Name",
        "00080050": "Accession Number",
        "0020000D": "Study Instance UID",
        "00200011": "Series Number",
        "0008103E": "Series Description",
        "0020000E": "Series Instance UID",
        "00540081": "Number of Slices",
        "00181310": "Acquisition Matrix",
        "00280030": "Pixel Spacing",
        "00180088": "Spacing Between Slices",
        "00180050": "Slice Thickness",
        "00180080": "Repetition Time",
        "00180081": "Echo Time",
        "00180086": "Echo Number(s)",
        "00180091": "Echo Train Length",
        "00180082": "Inversion Time",
        "00181314": "Flip Angle",
        "00189073": "Acquisition Duration",
        "00080008": "Image Type",
    }

    fields = list(dicom_field_mapping.keys())
    header_row = list(dicom_field_mapping.values())
    
    unique_sequences = {}
    all_files = find_dicom_files(dicom_dir, read_all)
    
    for file_path in tqdm(all_files, desc="Processing DICOM files", ncols=100):
        info = extract_dicom_info(file_path, fields)
        if info:
            unique_id = (
                info.get("0020000E", ""),  # Series Instance UID
                info.get("0008103E", ""),  # Series Description
                info.get("00200011", "")   # Series Number
            )
            if unique_id not in unique_sequences and any(unique_id):
                unique_sequences[unique_id] = info

    logging.warning(f"Writing {len(unique_sequences)} sequences to {output_path}")
    
    with open(output_path, 'w', newline='') as tsvfile:
        writer = csv.DictWriter(tsvfile, fieldnames=fields, delimiter='\t', extrasaction='ignore')
        writer.writerow(dict(zip(fields, header_row)))
        for sequence in unique_sequences.values():
            writer.writerow(sequence)

    print("\nSummary:")
    print(f"Total files processed: {len(all_files)}")
    print(f"Unique sequences found: {len(unique_sequences)}")
    print(f"Output file: {output_path}")
    print(f"Log file: {log_file}")
    print("Script completed successfully")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract and save unique DICOM sequence information to a CSV file. This script allows for the extraction of specific DICOM header fields from files in a given directory.",
        epilog="""Examples of use:
        
        # Basic usage to process first 5 DICOM files in a directory and save output:
        python extract_dicom_headers.py --dicom test --output out_test.tsv
        
        # Process all DICOM files in the directory:
        python extract_dicom_headers.py --dicom test --output out_test.tsv --read_all""",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("--dicom", required=True, help="Path to the directory containing DICOM files.")
    parser.add_argument("--output", required=True, help="Path to save the output CSV file.")
    parser.add_argument("--read_all", action='store_true', help="Read all DICOM files in the directory, not just the first 5.")

    args = parser.parse_args()

    main(args.dicom, args.output, args.read_all)