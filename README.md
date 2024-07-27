# DICOM Sorting Tool

This tool provides functionality for sorting and anonymizing DICOM files. It was developed by Pablo Naval Baudin in 2024.

## Features:
- DICOM file sorting
- Basic and strict anonymization options
- In-place files transfer syntax decompression. 
- GUI for easy operation

##  Download:
The executable for this tool is available in the releases section of this repository.

##  Usage:
1. Download the executable from the releases section.
2. Run the executable (it has been tested on a Windows 10 machine).
3. Use the GUI to select your input and output directories, and choose your desired options.
4. Click "Execute Sorting" to process your DICOM files.

## Script version usage:

### Environment 
The script requires Python 3 and additional packages: `tqdm`, `pydicom`, and `pathvalidate`. Install these dependencies with:
```pip install tqdm pydicom pathvalidate```


### Commands

Basic usage for sorting DICOM files:

```bash
python dicom_sorting_anonimyzing_tool.py --dicomin /path/to/unsorted --dicomout /path/to/sorted
```

To also anonymize DICOM files (removing Patient Name and Date of Birth, but not Patient ID):

```bash
python dicom_sorting_anonimyzing_tool.py --dicomin /path/to/unsorted --dicomout /path/to/sorted --anonymize
```

To perform strict anonymization of DICOM files:

```bash
python dicom_sorting_anonimyzing_tool.py --dicomin /path/to/unsorted --dicomout /path/to/sorted --anonymize --anonymize_strict
```


To replace PatientID based on a correlation table:

```bash
python dicom_sorting_anonimyzing_tool.py --dicomin /path/to/unsorted --dicomout /path/to/sorted --anonymize --ID_correlation /path/to/ID_correlation.txt
```

### Arguments

- **`--dicomin`**: Path to the directory containing unsorted DICOM files.
- **`--dicomout`**: Path to the directory where the sorted DICOM files will be stored based on their metadata.
- **`--anonymize`**: (Optional) If specified, anonymizes DICOM tags such as PatientName and PatientBirthDate.
- **`--anonymize_strict`**: (Optional) If specified, performs stricter anonymization, including removal of private tags and anonymizing additional fields.
- **`--decompress`**: (Optional) If specified, decompresses transfer syntax DICOM files during processing.
- **`--ID_correlation`**: (Optional) Path to a correlation file for anonymizing PatientID. The file should contain old and new IDs, separated by a comma, space, or tab.
- **`--skip_derived`**: (Optional) If specified, skips DICOM files that are derived or secondary images.
- **`--skip_burned_in_images`**: (Optional) If specified, skips DICOM files with burned-in annotations.
  
  
## Note:
This tool is for internal use only. It is not validated with DICOM standards, and we do not guarantee its accuracy or reliability. Use at your own risk.

For any issues or feature requests, please open an issue in this repository."# dicom_tool" 
