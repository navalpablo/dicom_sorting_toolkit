import os
import subprocess
import argparse
from tqdm import tqdm
from shutil import which
from concurrent.futures import ThreadPoolExecutor, as_completed

def is_tool_available(name):
    """Check if tool is available in PATH and executable."""
    return which(name) is not None

def decompress_file(file_path):
    try:
        # Attempt to decompress the file, overwriting the original
        subprocess.run(["dcmdjpeg", file_path, file_path], check=True)
        return file_path, True  # Return True if successful
    except subprocess.CalledProcessError:
        # This error is raised for non-DICOM files or other failures
        return file_path, False  # Return False on failure

def walk_and_process(directory):
    # Collect all files to process to calculate the progress
    file_paths = []
    for root, _, files in os.walk(directory):
        for file in files:
            file_paths.append(os.path.join(root, file))

    # Initialize the progress bar
    progress_bar = tqdm(total=len(file_paths), desc="Decompressing files", unit="file")
    
    # Use ThreadPoolExecutor for parallel processing
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(decompress_file, file_path): file_path for file_path in file_paths}
        
        for future in as_completed(futures):
            file_path, result = future.result()
            # Update the description on the progress bar
            progress_bar.set_description(f"Processing {os.path.basename(file_path)}")
            progress_bar.set_postfix(success=result)
            progress_bar.update(1)

def main():
    parser = argparse.ArgumentParser(description='Recursively decompress DICOM files in a directory tree.')
    parser.add_argument('path', type=str, help='Path to the directory to process.')
    args = parser.parse_args()

    # Check if dcmdjpeg is available in PATH
    if not is_tool_available("dcmdjpeg"):
        print("Error: 'dcmdjpeg' is not available on the system's PATH.")
        print("Please ensure that DCMTK is installed and 'dcmdjpeg' is added to the PATH.")
        print("DCMTK can be downloaded from: https://dicom.offis.de/dcmtk.php.en")
        return  # Exit the script if the required tool is not found

    # Change to specified directory
    os.chdir(args.path)
    print(f"Current working directory set to: {os.getcwd()}")

    # Start processing
    walk_and_process(os.getcwd())

if __name__ == "__main__":
    main()
