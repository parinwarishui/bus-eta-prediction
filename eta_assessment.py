'''
Bus ETA Prediction Accuracy Assessment System

This script:
1. Every 5 mins: Picks a random stop, logs the first bus's ETA prediction
2. Every 1 min: Checks if any predicted buses have arrived at their stops
3. Calculates accuracy (predicted vs actual arrival time)
4. Saves all data to CSV for analysis
'''

import os
import pandas as pd
import numpy as np
import json
import time
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pprint import pprint

# Import your existing modules
from stop_access import direction_map
from load_files import get_bus_data, collect_bus_history
from tweak_bus_data import filter_bus, map_index_df
from eta_calculation import get_upcoming_buses

'''==== CONSTANTS ===='''
load_dotenv()
API_KEY = os.getenv('API_KEY')
API_URL = "https://smartbus-pk-api.phuket.cloud/api/bus-news-2/"

# Assessment settings
AVAILABLE_ROUTES = ["Airport -> Rawai", "Rawai -> Airport", "Patong -> Bus 1 -> Bus 2", "Bus 2 -> Bus 1 -> Patong", "Dragon Line"]
PREDICTION_INTERVAL = 3 * 60  # 3 minutes in seconds
CHECK_INTERVAL = 30  # 1 minute in seconds
PREDICTIONS_FILE = "eta_prediction_stop_new.csv"
ASSESSMENTS_FILE = "eta_assessments_new.csv"
ARRIVAL_TOLERANCE = 50  # meters - how close bus needs to be to stop to count as "arrived"
STEP_ORDER = 5  # From your constants

'''==== HELPER FUNCTIONS ===='''

def initialize_csv_files():
    """Create CSV files with headers if they don't exist"""
    
    # Predictions CSV
    if not os.path.exists(PREDICTIONS_FILE):
        predictions_df = pd.DataFrame(columns=[
            'prediction_id',
            'prediction_time',
            'route',
            'stop_name',
            'stop_index',
            'licence',
            'bus_index',
            'predicted_eta_min',
            'predicted_arrival_time',
            'assessed',
            'actual_arrival_time',
            'accuracy_min'
        ])
        predictions_df.to_csv(PREDICTIONS_FILE, index=False)
        print(f"✓ Created {PREDICTIONS_FILE}")
    
    # Assessments summary CSV
    if not os.path.exists(ASSESSMENTS_FILE):
        assessments_df = pd.DataFrame(columns=[
            'prediction_id',
            'route',
            'stop_name',
            'licence',
            'predicted_eta_min',
            'actual_eta_min',
            'accuracy_min',
            'accuracy_percentage',
            'prediction_time',
            'actual_arrival_time'
        ])
        assessments_df.to_csv(ASSESSMENTS_FILE, index=False)
        print(f"✓ Created {ASSESSMENTS_FILE}")

def get_random_stop(route):
    """Get a random stop from the route"""
    stop_list = direction_map[route]["stop_list"]
    if not stop_list:
        return None
    return random.choice(stop_list)

def make_prediction(route, stop_name):
    """
    Make an ETA prediction for the first bus arriving at a stop
    Returns: dict with prediction data or None
    """
    try:
        # Get current bus data
        bus_df = get_bus_data(API_URL, API_KEY)
        if bus_df.empty:
            print("⚠ No bus data available")
            return None
        
        bus_df = collect_bus_history(bus_df)
        
        # Filter and map buses
        filtered_df = filter_bus(bus_df, route)
        if filtered_df.empty:
            print(f"⚠ No buses found on route {route}")
            return None
        
        mapped_df = map_index_df(filtered_df, route)
        
        # Get upcoming buses for this stop
        upcoming_df = get_upcoming_buses(mapped_df, stop_name, route)
        
        if upcoming_df.empty:
            print(f"⚠ No upcoming buses for {stop_name}")
            return None
        
        # Get first bus (shortest ETA)
        first_bus = upcoming_df.iloc[0]
        
        # Skip scheduled buses (they don't have real-time tracking)
        if first_bus['licence'] == 'Scheduled':
            print(f"⚠ First bus is scheduled (not real), skipping...")
            return None
        
        prediction_time = datetime.now()
        predicted_arrival = prediction_time + timedelta(minutes=int(first_bus['eta_min']))
        
        prediction = {
            'prediction_id': f"{int(prediction_time.timestamp())}_{first_bus['licence']}_{stop_name.replace(' ', '_')}",
            'prediction_time': prediction_time.isoformat(),
            'route': route,
            'stop_name': stop_name,
            'stop_index': int(first_bus['stop_index']),
            'licence': first_bus['licence'],
            'bus_index': int(first_bus['bus_index']),
            'predicted_eta_min': int(first_bus['eta_min']),
            'predicted_arrival_time': predicted_arrival.isoformat(),
            'assessed': False,
            'actual_arrival_time': None,
            'accuracy_min': None
        }
        
        print(f"\n📊 NEW PREDICTION")
        print(f"   Stop: {stop_name}")
        print(f"   Bus: {first_bus['licence']}")
        print(f"   ETA: {first_bus['eta_min']} minutes")
        print(f"   Distance: {first_bus['dist_km']:.2f} km")
        
        return prediction
        
    except Exception as e:
        print(f"❌ Error making prediction: {e}")
        import traceback
        traceback.print_exc()
        return None

def save_prediction(prediction):
    """Save a prediction to the CSV file"""
    try:
        df = pd.read_csv(PREDICTIONS_FILE)
        new_row = pd.DataFrame([prediction])
        df = pd.concat([df, new_row], ignore_index=True)
        df.to_csv(PREDICTIONS_FILE, index=False)
        print(f"✓ Saved prediction {prediction['prediction_id']}")
        return True
    except Exception as e:
        print(f"❌ Error saving prediction: {e}")
        return False

def check_bus_arrival(prediction, current_bus_df):
    """
    Check if a predicted bus has arrived at its stop
    Returns: True if arrived, False otherwise
    """
    licence = prediction['licence']
    stop_index = prediction['stop_index']
    
    # Find the bus in current data
    bus = current_bus_df[current_bus_df['licence'] == licence]
    
    if bus.empty:
        return False
    
    bus_data = bus.iloc[0]
    bus_index = bus_data.get('bus_index', -1)
    
    # Check if bus has passed or is at the stop
    # Allow a small buffer (STEP_ORDER * 10 = ~50 meters)
    index_tolerance = 10
    
    if bus_index >= stop_index - index_tolerance and bus_index <= stop_index + index_tolerance:
        return True
    
    # Also check if bus has passed the stop significantly
    if bus_index > stop_index + index_tolerance:
        return True
    
    return False

def assess_predictions():
    """
    Check all unassessed predictions to see if buses have arrived
    """
    try:
        # Load predictions
        predictions_df = pd.read_csv(PREDICTIONS_FILE)
        
        # Filter unassessed predictions
        unassessed = predictions_df[predictions_df['assessed'] == False].copy()
        
        if unassessed.empty:
            return
        
        print(f"\n🔍 Checking {len(unassessed)} unassessed predictions...")
        
        # Get current bus data
        bus_df = get_bus_data(API_URL, API_KEY)
        if bus_df.empty:
            print("⚠ No bus data available for assessment")
            return
        
        bus_df = collect_bus_history(bus_df)
        
        for idx, prediction in unassessed.iterrows():
            route = prediction['route']
            
            # Filter and map buses for this route
            filtered_df = filter_bus(bus_df, route)
            if filtered_df.empty:
                continue
            
            mapped_df = map_index_df(filtered_df, route)
            
            # Check if bus has arrived
            if check_bus_arrival(prediction, mapped_df):
                actual_arrival_time = datetime.now()
                prediction_time = pd.to_datetime(prediction['prediction_time'])
                predicted_arrival_time = pd.to_datetime(prediction['predicted_arrival_time'])
                
                # Calculate actual ETA (time from prediction to now)
                actual_eta_min = (actual_arrival_time - prediction_time).total_seconds() / 60
                
                # Calculate accuracy (difference between predicted and actual)
                accuracy_min = actual_eta_min - prediction['predicted_eta_min']
                
                # Calculate percentage accuracy
                if prediction['predicted_eta_min'] > 0:
                    accuracy_percentage = 100 - (abs(accuracy_min) / prediction['predicted_eta_min'] * 100)
                else:
                    accuracy_percentage = 0
                
                # Update predictions CSV
                predictions_df.loc[idx, 'assessed'] = True
                predictions_df.loc[idx, 'actual_arrival_time'] = actual_arrival_time.isoformat()
                predictions_df.loc[idx, 'accuracy_min'] = round(accuracy_min, 2)
                
                # Save to assessments CSV
                assessment = {
                    'prediction_id': prediction['prediction_id'],
                    'route': prediction['route'],
                    'stop_name': prediction['stop_name'],
                    'licence': prediction['licence'],
                    'predicted_eta_min': prediction['predicted_eta_min'],
                    'actual_eta_min': round(actual_eta_min, 2),
                    'accuracy_min': round(accuracy_min, 2),
                    'accuracy_percentage': round(accuracy_percentage, 2),
                    'prediction_time': prediction['prediction_time'],
                    'actual_arrival_time': actual_arrival_time.isoformat()
                }
                
                assessments_df = pd.read_csv(ASSESSMENTS_FILE)
                new_row = pd.DataFrame([assessment])
                assessments_df = pd.concat([assessments_df, new_row], ignore_index=True)
                assessments_df.to_csv(ASSESSMENTS_FILE, index=False)
                
                print(f"\n✅ ASSESSMENT COMPLETE")
                print(f"   Stop: {prediction['stop_name']}")
                print(f"   Bus: {prediction['licence']}")
                print(f"   Predicted ETA: {prediction['predicted_eta_min']} min")
                print(f"   Actual ETA: {actual_eta_min:.1f} min")
                print(f"   Accuracy: {accuracy_min:+.1f} min ({accuracy_percentage:.1f}%)")
        
        # Save updated predictions
        predictions_df.to_csv(PREDICTIONS_FILE, index=False)
        
    except Exception as e:
        print(f"❌ Error assessing predictions: {e}")
        import traceback
        traceback.print_exc()

def print_statistics():
    """Print summary statistics of assessments"""
    try:
        assessments_df = pd.read_csv(ASSESSMENTS_FILE)
        
        if assessments_df.empty:
            print("\n📊 No assessments yet")
            return
        
        print(f"\n📊 ASSESSMENT STATISTICS")
        print(f"   Total Assessments: {len(assessments_df)}")
        print(f"   Average Accuracy: {assessments_df['accuracy_percentage'].mean():.1f}%")
        print(f"   Average Error: {assessments_df['accuracy_min'].mean():+.1f} min")
        print(f"   Std Dev: {assessments_df['accuracy_min'].std():.1f} min")
        print(f"   Min Error: {assessments_df['accuracy_min'].min():+.1f} min")
        print(f"   Max Error: {assessments_df['accuracy_min'].max():+.1f} min")
        
    except Exception as e:
        print(f"❌ Error printing statistics: {e}")

'''==== MAIN ASSESSMENT LOOP ===='''

def run_assessment(duration_hours=None):
    """
    Run the assessment system
    
    Args:
        duration_hours: How long to run (None = run forever)
    """
    print("="*60)
    print("🚍 BUS ETA ACCURACY ASSESSMENT SYSTEM")
    print("="*60)
    print(f"Routes: {', '.join(AVAILABLE_ROUTES)}")
    print(f"Prediction Interval: {PREDICTION_INTERVAL//60} minutes")
    print(f"Check Interval: {CHECK_INTERVAL} seconds")
    print("="*60)
    
    # Initialize CSV files
    initialize_csv_files()
    
    # Timing variables
    start_time = time.time()
    last_prediction_time = 0
    last_check_time = 0
    
    if duration_hours:
        end_time = start_time + (duration_hours * 3600)
        print(f"\n⏱️  Running for {duration_hours} hours")
    else:
        end_time = None
        print(f"\n⏱️  Running indefinitely (press Ctrl+C to stop)")
    
    print("\n🚀 Starting assessment loop...\n")
    
    try:
        iteration = 0
        while True:
            iteration += 1
            current_time = time.time()
            
            # Check if duration exceeded
            if end_time and current_time >= end_time:
                print("\n⏱️  Duration reached. Stopping...")
                break
            
            # === MAKE NEW PREDICTION (every 5 mins) ===
            if current_time - last_prediction_time >= PREDICTION_INTERVAL:
                print(f"\n{'='*60}")
                print(f"🔄 Iteration {iteration} - {datetime.now().strftime('%H:%M:%S')}")
                print(f"{'='*60}")
                
                current_route = random.choice(AVAILABLE_ROUTES)
                stop = get_random_stop(current_route)
                if stop:
                    prediction = make_prediction(current_route, stop['stop_name_eng'])
                    if prediction:
                        save_prediction(prediction)
                                
                last_prediction_time = current_time
            
            # === CHECK EXISTING PREDICTIONS (every 1 min) ===
            if current_time - last_check_time >= CHECK_INTERVAL:
                assess_predictions()
                last_check_time = current_time
                
                # Print statistics every 10 checks
                if iteration % 10 == 0:
                    print_statistics()
            
            # Sleep for a short time to avoid busy waiting
            time.sleep(10)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        print("\n" + "="*60)
        print("📊 FINAL STATISTICS")
        print("="*60)
        print_statistics()
        print("\n✓ Assessment system stopped")
        print(f"✓ Data saved to: {PREDICTIONS_FILE} and {ASSESSMENTS_FILE}")

'''==== ENTRY POINT ===='''

if __name__ == "__main__":
    import sys
    
    # Optional: specify duration in hours as command line argument
    duration = None
    if len(sys.argv) > 1:
        try:
            duration = float(sys.argv[1])
            print(f"Duration set to {duration} hours")
        except:
            print("Usage: python bus_eta_assessment.py [duration_in_hours]")
            sys.exit(1)
    
    run_assessment(duration_hours=duration)