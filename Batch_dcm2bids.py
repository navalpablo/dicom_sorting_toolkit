#!/usr/bin/env python3

import os
import subprocess
import sys
import argparse
from datetime import datetime
import pandas as pd
import glob

"""
Simplified DICOM Processing Script
This script is designed to process DICOM files, executing dcm2bids for each subject and session,
and maintaining a record of study dates.

Usage:
    python script_name.py [options]

Options:
    --dicomin         Specify the path to the DICOM input directory. Default is "sourcedata".
    --nobids          Skip the conversion to BIDS format.
    --config          Specify the path to the dcm2bids configuration JSON file. Default is "dcm2bids_config.json".
    --bidsdir         Specify the path for the BIDS output directory. Default is "BIDSDIR" in the script's directory.
"""

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Processes DICOM files, executing dcm2bids for each subject and session."
    )
    parser.add_argument(
        '--dicomin',
        default="sourcedata",
        help='Specify the path to the DICOM input directory. Default is "sourcedata".'
    )
    parser.add_argument(
        '--nobids',
        action='store_true',
        help='Skip the conversion to BIDS format.'
    )
    parser.add_argument(
        '--config',
        default="dcm2bids_config.json",
        help='Path to the dcm2bids configuration JSON file. Default is "dcm2bids_config.json".'
    )
    parser.add_argument(
        '--bidsdir',
        default=None,
        help='Path for the BIDS output directory. Default is "BIDSDIR" in the script\'s directory.'
    )
    return parser.parse_args()



def read_existing_studies(studies_file):
    if os.path.exists(studies_file):
        df = pd.read_csv(studies_file, sep='\t')
        return {(row['subject'], row['date']): row['session'] for _, row in df.iterrows()}
    return {}

def get_next_session_number(existing_sessions, subject):
    subject_sessions = [int(session.split('-')[1]) for subj, session in existing_sessions.items() if subj == subject]
    return f"ses-{str(max(subject_sessions + [0]) + 1).zfill(2)}"

def process_sessions(sourcedata_dir, bidsdir_folder, dcm2bids_config):
    studies_file = os.path.join(bidsdir_folder, "studies.tsv")
    existing_studies = read_existing_studies(studies_file)

    # Write header if file doesn't exist
    if not os.path.exists(studies_file):
        with open(studies_file, "w") as file:
            file.write("subject\tsession\tdate\n")

    subjects = sorted([d for d in os.listdir(sourcedata_dir) if os.path.isdir(os.path.join(sourcedata_dir, d))])
    
    for subject in subjects:
        subject_dir = os.path.join(sourcedata_dir, subject)
        sessions = sorted([d for d in os.listdir(subject_dir) if os.path.isdir(os.path.join(subject_dir, d))])
        
        for session_dir in sessions:
            date = session_dir  # Assuming the folder name is the date
            
            # Check if this subject-date combination already exists
            if (subject, date) in existing_studies:
                session_label = existing_studies[(subject, date)]
            else:
                session_label = get_next_session_number(existing_studies, subject)
                existing_studies[(subject, date)] = session_label

            session_path = os.path.join(subject_dir, session_dir)
            dcm2bids_cmd = [
                "dcm2bids", "-d", session_path, "-p", subject,
                "-s", session_label, "-c", dcm2bids_config, "-o", bidsdir_folder
            ]
            print("Executing:", ' '.join(dcm2bids_cmd))
            result = subprocess.run(dcm2bids_cmd, capture_output=True, text=True)
            print(result.stdout)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            
            # Append this session's data to the studies.tsv file if it's new
            if (subject, date) not in existing_studies:
                with open(studies_file, "a") as file:
                    file.write(f"{subject}\t{session_label}\t{date}\n")

def main():
    args = parse_arguments()
    script_dir = os.path.dirname(os.path.realpath(__file__))
    os.chdir(script_dir)

    # Directory setup
    sourcedata_dir = os.path.abspath(args.dicomin)
    bidsdir_folder = args.bidsdir if args.bidsdir else os.path.join(script_dir, "BIDSDIR")
    dcm2bids_config = args.config

    # BIDS directory setup
    if not os.path.exists(bidsdir_folder):
        os.makedirs(bidsdir_folder, exist_ok=True)
        subprocess.run(["dcm2bids_scaffold", "-o", bidsdir_folder])

    # dcm2bids step
    if not args.nobids:
        process_sessions(sourcedata_dir, bidsdir_folder, dcm2bids_config)

    print("Batch process completed.")

if __name__ == "__main__":
    main()
