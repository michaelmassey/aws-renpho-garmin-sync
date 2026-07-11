import os
from datetime import datetime
import time
import boto3
from renpho import RenphoClient
from garminconnect import Garmin

def get_ssm_parameter(param_name):
    """Retrieve decrypted parameter from SSM Parameter Store."""
    ssm = boto3.client('ssm')
    response = ssm.get_parameter(Name=param_name, WithDecryption=True)
    return response['Parameter']['Value']

def handler(event, context):
    print("Initializing Renpho to Garmin sync...")
    
    # Retrieve environment variables
    table_name = os.environ.get('TABLE_NAME')
    renpho_email_param = os.environ.get('RENPHO_EMAIL_PARAM_NAME')
    renpho_password_param = os.environ.get('RENPHO_PASSWORD_PARAM_NAME')
    garmin_email_param = os.environ.get('GARMIN_EMAIL_PARAM_NAME')
    garmin_password_param = os.environ.get('GARMIN_PASSWORD_PARAM_NAME')
    
    print(f"DynamoDB Table: {table_name}")
    
    try:
        # Fetch secure credentials from SSM
        print("Fetching credentials from SSM Parameter Store...")
        renpho_email = get_ssm_parameter(renpho_email_param)
        renpho_password = get_ssm_parameter(renpho_password_param)
        garmin_email = get_ssm_parameter(garmin_email_param)
        garmin_password = get_ssm_parameter(garmin_password_param)
        
        print("Successfully retrieved credentials from SSM.")
        
        # Authenticate Renpho
        print("Logging into Renpho API...")
        renpho_client = RenphoClient(renpho_email, renpho_password)
        renpho_client.login()
        print("Renpho login successful.")

        # Authenticate Garmin (Letting the native cascading fallback handle 429s)
        print("Logging into Garmin Connect...")
        garmin_client = Garmin(garmin_email, garmin_password)
        garmin_client.login()
        print("Garmin login successful.")
        
        # 1. BULK DYNAMODB SCAN: Pull only the IDs into memory (paginated)
        print("Scanning DynamoDB state registry...")
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(table_name)
        
        synced_ids = set()
        scan_kwargs = {'ProjectionExpression': 'id'}
        while True:
            response = table.scan(**scan_kwargs)
            for item in response.get('Items', []):
                synced_ids.add(item['id'])
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
            
        print(f"Found {len(synced_ids)} previously synchronized record IDs in memory.")

        # 2. FETCH RENPHO HISTORY
        print("Fetching measurements from Renpho...")
        measurements = renpho_client.get_all_measurements()
        print(f"Found {len(measurements)} records in Renpho Health.")

        # Sort newest to oldest so newest measurements are synced first
        print("Sorting measurements...")
        measurements.sort(key=lambda x: int(x.get('timeStamp', 0)), reverse=True)

        # In case the Renpho Health account has a large number of historical records, we define
        # a safe ceiling per execution to respect AWS Lambda runtime limits and Garmin API limits.
        # If the batch limit is reached, the remaining records will be processed in the next run.
        # After historical syncing is complete, only new daily measurements will be synced, so the
        # batch limit will no longer be relevant.

        # Retrieve the limit from the environment variable (defaulting to 1 if not set).
        batch_limit_env = os.environ.get('BATCH_LIMIT', '1')
        try:
            batch_limit = int(batch_limit_env)
        except ValueError:
            print(f"Warning: Invalid BATCH_LIMIT environment variable '{batch_limit_env}'. Defaulting to 1.")
            batch_limit = 1
            
        synced_count = 0

        # 3. THE SYNC LOOP
        for entry in measurements:

            # Check if we have hit our defensive batch size cap for this run
            if synced_count >= batch_limit:
                print(f"Batch limit of {batch_limit} reached. Stopping early to protect Garmin API limits.")
                print("Remaining historical records will be synchronized during subsequent executions.")
                break

            m_id = str(entry['id'])
            
            # O(1) local RAM check against DynamoDB cache
            if m_id in synced_ids:
                continue 

            # Parse the correct 'timeStamp' key into a datetime object
            timestamp_raw = entry.get('timeStamp')
            if not timestamp_raw:
                print(f"Skipping record {m_id} because it lacks a timestamp.")
                continue
            measurement_dt = datetime.fromtimestamp(int(timestamp_raw))
            formatted_date = measurement_dt.strftime('%Y-%m-%d %H:%M:%S')

            print(f"New entry found: {m_id} [Logged: {formatted_date}]. Syncing to Garmin...")
            
            # Extract metrics using the exact validated payload keys, keeping them as None
            # if they are missing or falsy to prevent pushing 0.0 values to Garmin.
            weight_kg = float(entry['weight'])
            percent_fat = float(entry['bodyfat']) if entry.get('bodyfat') else None
            percent_water = float(entry['water']) if entry.get('water') else None
            bmi = float(entry['bmi']) if entry.get('bmi') else None
            bone_mass = float(entry['bone']) if entry.get('bone') else None

            # Calculate absolute voluntary Skeletal Muscle Mass in kg to match Garmin's specification
            if entry.get('muscle'):
                muscle_mass = weight_kg * (float(entry['muscle']) / 100.0)
            else:
                muscle_mass = None

            # Convert datetime to ISO-8601 string format (e.g. YYYY-MM-DDTHH:MM:SS) expected by Garmin
            iso_timestamp = measurement_dt.isoformat()

            try:
                garmin_client.add_body_composition(
                    timestamp=iso_timestamp,
                    weight=weight_kg,
                    percent_fat=percent_fat,
                    percent_hydration=percent_water,
                    bmi=bmi,
                    bone_mass=bone_mass,
                    muscle_mass=muscle_mass
                )
                
                # Lock state row-by-row instantly
                table.put_item(Item={'id': m_id})
                print(f"Successfully locked state for record: {m_id}")
                synced_count += 1
                
                # Gentle pacing between Garmin API calls
                time.sleep(1)
                
            except Exception as e:
                print(f"Error syncing record {m_id}: {e}")
                continue

        print(f"Synchronization pipeline completed successfully. Synced {synced_count} new entries.")
        return {
            "statusCode": 200,
            "body": f"Sync run complete. {synced_count} new records added."
        }
        
    except Exception as e:
        print(f"Error during synchronization execution: {e}")
        return {
            "statusCode": 500,
            "body": f"Failed: {str(e)}"
        }