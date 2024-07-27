import csv
import argparse
import json
from collections import defaultdict

def parse_criteria_json(criteria_json):
    """
    Parses the JSON string specifying the series descriptions and any OR conditions.
    """
    try:
        criteria = json.loads(criteria_json)
        return criteria
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format: {e}")

def create_dummy_table_from_tsv(input_tsv_path, criteria_json):
    """
    Reads an existing TSV file to create a dummy table based on complex criteria.
    """
    patient_series = defaultdict(lambda: defaultdict(int))
    criteria = parse_criteria_json(criteria_json)

    with open(input_tsv_path, 'r', newline='') as tsvfile:
        reader = csv.DictReader(tsvfile, delimiter='\t')
        for row in reader:
            patient_id = row.get("Patient ID", "")
            series_description = row.get("Series Description", "")
            
            for dummy, conditions in criteria.items():
                if isinstance(conditions, list):  # OR condition
                    if any(crit in series_description for crit in conditions):
                        patient_series[patient_id][dummy] += 1
                elif conditions in series_description:
                    patient_series[patient_id][dummy] += 1

    columns = ["Patient ID"] + list(criteria.keys())
    output_dummy_path = input_tsv_path.replace('.tsv', '_dummy.tsv')

    with open(output_dummy_path, 'w', newline='') as tsvfile:
        writer = csv.writer(tsvfile, delimiter='\t')
        writer.writerow(columns)
        for patient_id, series_counts in patient_series.items():
            row = [patient_id] + [series_counts.get(dummy, 0) for dummy in criteria.keys()]
            writer.writerow(row)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate a dummy table from an existing .tsv file containing DICOM sequence information, with support for complex OR conditions specified in JSON format.",
        epilog="""Examples of use:
python create_dummy.py --input out_test.tsv --criteria_json "{\"T1\": \"T1\", \"FLAIR\": \"FLAIR\", \"NOMS_VISUAL\": [\"NOMS VISUAL\", \"NOMS_VISUAL\"], \"NOMS_AUD\": [\"NOMS AUD\", \"NOMS_AUD\"]}"

python create_dummy.py --input another_test.tsv --criteria_json "{\"T2\": \"T2\", \"GD_CON\": [\"GD\", \"CON\"], \"VERBS\": [\"VERBS VIS\", \"VERBS_VIS\"]}" 

python create_dummy.py --input out_test.tsv --criteria_json "{\"T1\": \"T1\",\"T2\": \"T2\",\"FLAIR\": \"FLAIR\", \"GADO\": [\"GADO\",\"GD\",\"CONTRA\"],\"NOMS_VISUAL\": [\"NOMS VISUAL\", \"NOMS_VISUAL\"], \"NOMS_AUD\": [\"NOMS AUD\", \"NOMS_AUD\"], \"VERBS_VISUAL\": [\"VERBS VISUAL\", \"VERBS_VISUAL\"], \"VERBS_AUD\": [\"VERBS AUD\", \"VERBS_AUD\"]}"

""",



        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", required=True, help="Path to the input .tsv file.")
    parser.add_argument("--criteria_json", required=True, help="JSON string specifying the series descriptions and any OR conditions.")

    args = parser.parse_args()

    create_dummy_table_from_tsv(args.input, args.criteria_json)
