import pandas as pd
from datetime import datetime, timedelta

# Reload the dataset
df = pd.read_csv('eta_predictions_1911_2.xlsx - eta_predictions_1911_2.csv')

# Convert time columns to datetime objects
df['prediction_timestamp_dt'] = pd.to_datetime(df['prediction_timestamp'], format='%H:%M:%S', errors='coerce')
df['arrival_time_dt'] = pd.to_datetime(df['arrival_time'], format='%H:%M:%S', errors='coerce')

# Identify columns related to ETA predictions
eta_cols = [col for col in df.columns if col.startswith('eta_min_T')]

for col in eta_cols:
    # Extract the time offset X from the column name (e.g., 'eta_min_T15' -> 15)
    try:
        offset_minutes = int(col.split('T')[1])
    except ValueError:
        continue 

    # Create a new column name for the difference
    diff_col_name = f'diff_min_{col.split("_")[-1]}'

    # Calculate predicted arrival time for this specific T
    predicted_arrival = df['prediction_timestamp_dt'] + pd.to_timedelta(offset_minutes, unit='m') + pd.to_timedelta(df[col], unit='m')

    # Calculate the difference: Actual Arrival - Predicted Arrival
    diff = df['arrival_time_dt'] - predicted_arrival

    # Convert the difference to minutes
    df[diff_col_name] = diff.dt.total_seconds() / 60.0

# Select relevant columns
output_cols = ['licence', 'route', 'prediction_timestamp', 'arrival_time'] + eta_cols + [col for col in df.columns if col.startswith('diff_min_')]
result_df = df[output_cols]

# Save to CSV
result_df.to_csv('eta_diff_calculated.csv', index=False)
print("File 'eta_diff_calculated.csv' generated successfully.")