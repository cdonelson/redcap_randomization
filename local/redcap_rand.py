import requests
import config
import pandas as pd
import numpy as np
import random
import json
import sys
import logging
from datetime import datetime

# Operational variables
redcap_api_token = config.redcap_api_token
report_id = config.report_id
redcap_endpoint = config.redcap_endpoint
allocation_tablename = config.allocation_table
treatment_field = config.treatment_field
randomized_field = config.randomized_field
log_filename = './logs/redcap_rand_log_' + datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + '.log'
logging.basicConfig(filename=log_filename, filemode='w', encoding='utf-8', level=logging.INFO)

def pull_redcap_report():
    data = {
        'token': redcap_api_token,
        'content': 'report',
        'format': 'json',
        'report_id': report_id,
        'csvDelimiter': '',
        'rawOrLabel': 'raw',
        'rawOrLabelHeaders': 'raw',
        'exportCheckboxLabel': 'false',
        'returnFormat': 'json',
    }
    response = requests.post(url = redcap_endpoint, data = data)
    if response.status_code == 200:
        print('HTTP Status', str(response.status_code), response.reason, ": Records download successful")
        logging.info('HTTP Status:' + str(response.status_code) + ' ' + response.reason + ": Records download successful")
    else:
        print('HTTP Status', str(response.status_code), response.reason, ": Records failed to download")
        logging.info('HTTP Status:' + str(response.status_code) + ' ' + response.reason + ": Records failed to download")
        sys.exit(1)
    if len(response.json()) == 0:
        print("No eligible records in REDCap")
        logging.info("No eligible records in REDCap")
        sys.exit(1)
    return response.json()

def pull_redcap_codebook():
    data = {
        'token': redcap_api_token,
        'content': 'metadata',
        'format': 'json',
        'returnFormat': 'json'
    }
    try:
        response = requests.post(redcap_endpoint, data = data)
        print("Successfully fetched REDCap codebook")
        logging.info("Successfully fetched project codebook")
    except Exception as e:
        print("Failed to fetch REDCap codebook. Exiting.")
        logging.info("Failed to fetch project codebook. Exiting.")
        logging.info(e)
        sys.exit(1)
    return response.json()

def convert_codebook(full_codebook, criteria):
    codebook = {}
    # Create translation dictionary of {field_name: {label1: value1, label2: value2, etc}} from full_codebook
    for obj in full_codebook:
        # Check to make sure all criteria have label:value options.
        # Current supported field types include Multiple Choice (dropdown),  Multiple Choice (radio),
        # Checkboxes, Yes-No, and True-False.  Yes-No and True-False values are calculated within the code
        approved_field_types = ['dropdown', 'radio', 'checkbox']
        if obj['field_type'] == 'yesno':
            obj['select_choices_or_calculations'] = '1, Yes | 0, No'
        elif obj['field_type'] == 'truefalse':
            obj['select_choices_or_calculations'] = '1, True | 0, False'
        elif obj['field_type'] not in approved_field_types:
            logging.info("Codebook: Invalid field type " + obj['field_type'] + ' ' + obj['field_name'])
            continue
        logging.info("Codebook: Validated " + obj['field_name'] + ' of type ' + obj['field_type'])

        # Convert REDCap structure to dictionary structure
        if obj['select_choices_or_calculations'] and ((obj['field_name'] in criteria) or (obj['field_name'] == treatment_field)):
            try:
                pipe_split = obj['select_choices_or_calculations'].split('|')
                temp_dict = {}
                for pair in pipe_split:
                    kv_list = pair.split(',')
                    temp_dict[kv_list[1].strip()] = kv_list[0].strip()
                codebook[obj['field_name']] = temp_dict
                print("Codebook: Succesfully converted " + obj['field_name'])
                logging.info("Codebook: Succesfully converted " + obj['field_name'])
            except Exception as e:
                print("Codebook: Failed to convert " + obj['field_name'])
                logging.info("Codebook: Failed to convert " + obj['field_name'])
                print(e)
                sys.exit(1)
    return codebook

def pull_allocation_table():
    # Read in allocation table (csv or excel file) from local data folder
    filename = './data/' + allocation_tablename
    try:
        temp_df = pd.read_csv(filename)
    except:
        try:
            temp_df = pd.read_excel(filename)
        except Exception as e:
            print("Failed to read in " + allocation_tablename)
            logging.info("Failed to read in " + allocation_tablename)
            logging.info(e)
            sys.exit(1)
    print("Succesfully read in table" + allocation_tablename)
    logging.info("Successfully read in table " + allocation_tablename)
    return temp_df
    
def calculate_probabilities(grouped_df, less_criteria):
    # Probabilities of a random treatment are calculated from frequency of that
    # treatment, given a specific set of criteria in the allocation table.
    #
    # a) grouped_df: dataframe containing the frequency of each criteria-treatment combination
    # b) freq_df: dataframe containing the frequency of each criteria combination, irregardless of treatment
    # 
    # Probability for each criteria-treatment combination, given a set of criteria, is the quotient of a/b

    mapped_df = pd.DataFrame() # Dataframe to hold probabilities of criteria-treatment combinations
    freq_df = grouped_df.groupby(less_criteria, dropna=False, as_index=False)['size'].sum()
    for index, row in freq_df.iterrows(): # Step through each criteria combination
        for index2, row2 in grouped_df.iterrows(): # Step through each criteria-treatment combination
            try:
                if all(row[col] == row2[col] for col in less_criteria): # If criteria match then calculate probability
                    temp_row = row2
                    temp_row['probability'] = round(row2['size'] / (row['size']), 3)
                    temp_df = pd.DataFrame([temp_row])
                    mapped_df = pd.concat([mapped_df, temp_df], ignore_index=True)
                else:
                    pass
            except Exception as e:
                print("Failed to calculate probability on freq_df row " + row + " and grouped_df row " + row2)
                logging.info("Failed to calculate probability on freq_df row " + row + " and grouped_df row " + row2)
                logging.info(e)
                sys.exit(1)
    print("Succesfully calculated probabilities")
    logging.info("Succesfully calculated probabilities")
    mapped_df[randomized_field] = mapped_df[treatment_field]
    return mapped_df

def convert_to_values(full_criteria, mapped_df, translation_dict):
    # Convert labels to values so they can match with the eligibility_report
    # created earlier from REDCap codebook
    for column_name in full_criteria:
        try:
            mapped_df[column_name] = mapped_df[column_name].apply(lambda x: translation_dict[column_name].get(x, None))
        except Exception as e:
            print("Failed to convert " + column_name + " to value")
            logging.info("Failed to convert " + column_name + " to value")
            logging.info(e)
            sys.exit(1)
    mapped_df.replace({pd.NA: '', np.nan: ''}, inplace=True)
    return mapped_df

def create_probability_dict(mapped_df, less_criteria):
    # mapped_df is the dataframe containing probabilites of criteria-treatment combinations.
    # This function converts that dataframe into a dictionary where each key is a specific
    # combination of criteria values, and whose value is an inner dictionary that contains
    # the probabilities of each treatment option for that specific criteria combination.
    #
    # Format: "(criteria values) : {treatment1: prob1, treatment2: prob2...}"
    # Example probability dictionary:
    # (1, 1) : {1: 0.5, 2: 0.5}
    # (1, 2) : {1: 0.33, 2: 0.33, 3: 0.34}
    # (2, 1) : {1: 0.2, 2: 0.55, 3: 0.25}
    # (2, 2) : {1: 0.1, 2: 0.9}

    probability_dict = {}
    for index, row in mapped_df.iterrows():
        key = tuple(row[less_criteria])  # Create a tuple of values from specified columns.  Becomes the key in new dictionary.
        value_dict = probability_dict.get(key, {})  # Get the inner dictionary for that key, or create one if key doesn't exist.
        inner_key = row[randomized_field]   # Key for the inner dictionary is the value of treatment option.
        inner_value = row['probability']    # Value for the inner dictionary is the probability of that treatment.
        value_dict[inner_key] = inner_value
        probability_dict[key] = value_dict
    return probability_dict

def randomization_step(eligibility_report, less_criteria, probability_dict):
    # Each subject in eligibility_report is randomly assigned a treatment 
    # from the probability dictionary given their criteria values.

    for report_key, report_value in enumerate(eligibility_report):
        if all(key in report_value for key in less_criteria):
            tuple_key = tuple(report_value[key] for key in less_criteria)
            if tuple_key in probability_dict:
                multilevel_value = probability_dict[tuple_key]
                random_choice = random.choices(list(multilevel_value.keys()), weights=list(multilevel_value.values()), k=1)[0]
                eligibility_report[report_key][randomized_field] = random_choice
    return eligibility_report

def push_to_redcap(record_list):
        try:
            import_json = json.dumps(record_list)
            logging.info("Succesfully serialized records to json")
        except Exception as e:
            logging.info("Failed to serialize records to json")
            logging.info(e)
            sys.exit(1)
        data = {
            'token': redcap_api_token,
            'content': 'record',
            'format': 'json',
            'type': 'flat',
            'overwriteBehavior': 'normal',
            'forceAutoNumber': 'false',
            'data': import_json,
            'returnContent': 'count',
            'returnFormat': 'json'
        }
        response = requests.post(redcap_endpoint,data=data)
        if response.status_code == 200:
            print('HTTP Status', str(response.status_code), response.reason, ": Records import successful")
            logging.info('HTTP Status:' + str(response.status_code) + ' ' + response.reason + ": Records import successful")
        else:
            print('HTTP Status', str(response.status_code), response.reason, ": Records failed to import")
            logging.info('HTTP Status:' + str(response.status_code) + ' ' + response.reason + ": Records failed to import")
            sys.exit(1)

def main():
    # Pull reports from REDCap and create translation dictionary of labels to values
    eligibility_report = pull_redcap_report()
    original_codebook = pull_redcap_codebook()
    try:
        full_criteria = list(eligibility_report[0].keys())[1:] # Create list of criteria variables from REDCap report
        print("Criteria selected from REDCap: " + ', '.join(full_criteria))
        logging.info("Criteria selected from REDCap: " + ', '.join(full_criteria))
    except Exception as e:
        print("Failed to select criteria from REDCap.")
        logging.info("Failed to select criteria from REDCap.")
        logging.info(e)
        sys.exit(1)
    translation_dict = convert_codebook(original_codebook, full_criteria) 

    # Pull allocation table and count frequency of treatments by criteria
    allocation_df = pull_allocation_table()
    allocation_df.replace({pd.NA: '', np.nan: ''}, inplace=True)
    grouped_df = allocation_df.groupby(allocation_df.columns.to_list(), as_index=False, dropna=False).size()

    # Create list of criteria without the randomized_field
    less_criteria = full_criteria.copy()
    less_criteria.remove(randomized_field)
    logging.info("report criteria: " + ', '.join(sorted(full_criteria)))
    logging.info("table criteria: " + ', '.join(sorted(allocation_df.columns.drop(treatment_field).tolist())))

    # Check for matching criteria between cookbook and allocation_table
    if (sorted(full_criteria) == sorted(allocation_df.columns.drop(treatment_field).to_list())):
        print("Criteria fields matched")
    else:
        print("Criteria field mismatch")
        print("Cookbook criteria: " + ', '.join(sorted(less_criteria)))
        print("Table criteria: " + ', '.join(sorted(allocation_df.columns.drop(treatment_field).to_list())))
        sys.exit(1)

    # Calculate dataframe of criteria combinations and their probabilities
    mapped_df = calculate_probabilities(grouped_df, less_criteria)

    # Replace labels with values in mapped_df so it can match eligibility_report.
    mapped_df = convert_to_values(full_criteria, mapped_df, translation_dict)
    mapped_df[full_criteria] = mapped_df[full_criteria].replace(['',np.inf, -np.inf], np.nan).fillna(-1).astype(int)

     # Convert values from strings to integers in eligibility_report, or replace with -1 if empty
    eligibility_report = [{key: int(value) if value != '' else -1 for key, value in input_dict.items()} for input_dict in eligibility_report]

    # Create the multilevel dictionary to store probabilities
    probability_dict = create_probability_dict(mapped_df, less_criteria)

    # Assign appropriate treatments to randomized_field via probability distribution in probability_dict
    eligibility_report = randomization_step(eligibility_report, less_criteria, probability_dict)

    logging.info("Records to import...")
    for record in eligibility_report:
        for key, value in record.items():
            if value == -1:
                record[key] = None
        logging.info(record)

    # Push records back to REDCap via API
    push_to_redcap(eligibility_report)

if __name__ == "__main__":
    main()