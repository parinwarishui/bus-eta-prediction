import os
import time
import pandas as pd
import numpy as np
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv

# External imports
from load_files import get_bus_data, collect_bus_history, load_route_coords
from tweak_bus_data import filter_bus, map_index_df, ORDERS_PER_KM
from eta_calculation import calc_eta
from stop_access import direction_map

# Config
CHECK_INTERVAL_SEC = 30
EVALUATION_CSV = "eta_predictions_1911.csv"

# Define prediction intervals (minutes from script start)
PRED_INTERVALS = [0, 15, 30, 45, 60, 75, 90] 

load_dotenv()
API_KEY = os.getenv("API_KEY")
API_URL = "https://smartbus-pk-api.phuket.cloud/api/bus-news-2/"

csv_lock = threading.Lock()
shutdown_event = threading.Event()
SCRIPT_START_TIME = datetime.now()

# =========================================================
#   CSV HELPERS
# =========================================================

def initialize_csv_if_needed():
    """Creates the CSV with the dynamic time columns if it doesn't exist."""
    if not os.path.exists(EVALUATION_CSV):
        # Added prediction_timestamp and arrival_time columns
        cols = [
            "licence", 
            "route", 
            "start_bus_index", 
            "target_km", 
            "target_index", 
            "prediction_timestamp",  # NEW: Time at startup
            "arrival_time"           # NEW: Time at actual arrival
        ]
        
        # Add dynamic columns for ETA intervals
        for t in PRED_INTERVALS:
            cols.append(f"eta_min_T{t}")
        
        df = pd.DataFrame(columns=cols)
        with csv_lock:
            df.to_csv(EVALUATION_CSV, index=False)
        print("[SYSTEM] CSV initialized with timestamp columns.")

def register_new_bus_rows(route_name, licence, start_index, targets, prediction_time):
    """Writes the skeleton rows for a new bus."""
    rows = []
    for t_idx in targets:
        row = {
            "licence": licence,
            "route": route_name,
            "start_bus_index": start_index,
            "target_km": t_idx // ORDERS_PER_KM,
            "target_index": t_idx,
            "prediction_timestamp": prediction_time, # RECORD STARTUP TIME
            "arrival_time": pd.NA                    # WAIT FOR ARRIVAL
        }
        # Initialize ETA columns as NaN
        for t in PRED_INTERVALS:
            row[f"eta_min_T{t}"] = pd.NA
        rows.append(row)

    df_new = pd.DataFrame(rows)
    
    with csv_lock:
        try:
            df_new.to_csv(EVALUATION_CSV, mode='a', header=False, index=False)
        except Exception as e:
            print(f"[{route_name}] Error registering bus {licence}: {e}")

    print(f"[{route_name}] Registered bus {licence} at {prediction_time.strftime('%H:%M:%S')}")

def update_actual_arrival(route_name, licence, target_index, actual_time):
    """Updates the arrival_time when a target is hit."""
    with csv_lock:
        try:
            df = pd.read_csv(EVALUATION_CSV)
            mask = (df["licence"] == licence) & (df["target_index"] == target_index)
            if mask.any():
                # Update the arrival_time column
                df.loc[mask, "arrival_time"] = actual_time
                df.to_csv(EVALUATION_CSV, index=False)
                print(f"[{route_name}] {licence} HIT target {target_index} at {actual_time.time()}")
        except Exception as e:
            print(f"[{route_name}] Error updating actuals: {e}")

def batch_update_predictions(route_name, updates):
    """Efficiently updates multiple ETA predictions at once."""
    if not updates:
        return

    with csv_lock:
        try:
            df = pd.read_csv(EVALUATION_CSV)
            df['match_key'] = df['licence'] + "_" + df['target_index'].astype(str)
            
            for u in updates:
                key = f"{u['licence']}_{u['target_index']}"
                mask = df['match_key'] == key
                if mask.any():
                    df.loc[mask, u['col_name']] = round(u['value'], 2)
            
            df.drop(columns=['match_key'], inplace=True)
            df.to_csv(EVALUATION_CSV, index=False)
            print(f"[{route_name}] Batch updated {len(updates)} predictions.")
            
        except Exception as e:
            print(f"[{route_name}] Error in batch update: {e}")

# =========================================================
#   MAIN EVALUATION LOOP
# =========================================================

def evaluate_bus_eta(route_name):
    print(f"\n--- [{route_name}] Starting Fleet Monitor ---")

    tracked_buses = {} 
    coords = load_route_coords(direction_map[route_name]["geojson_path"])
    max_route_index = max(o for o, lon, lat in coords)

    while not shutdown_event.is_set():
        try:
            # 1. Time Management
            now = datetime.now()
            elapsed_min = (now - SCRIPT_START_TIME).total_seconds() / 60
            
            current_interval_tag = None
            for t in PRED_INTERVALS:
                if t <= elapsed_min < (t + 1.5): 
                    current_interval_tag = t
                    break

            # 2. Get Data
            df_raw = get_bus_data(API_URL, API_KEY)
            df_hist = collect_bus_history(df_raw)
            buses_on_route = filter_bus(df_hist, route_name)
            mapped_df = map_index_df(buses_on_route, route_name)

            if mapped_df.empty:
                time.sleep(CHECK_INTERVAL_SEC)
                continue

            # 3. Process Each Bus Found
            batch_eta_updates = []
            
            for _, bus_row in mapped_df.iterrows():
                licence = bus_row["licence"]
                current_idx = int(bus_row["bus_index"])
                
                # --- A. NEW BUS DETECTION ---
                if licence not in tracked_buses:
                    start_km = (current_idx // ORDERS_PER_KM) + 1
                    first_target = start_km * ORDERS_PER_KM
                    targets = list(range(first_target, max_route_index + 1, ORDERS_PER_KM))
                    if max_route_index not in targets:
                        targets.append(max_route_index)
                    
                    tracked_buses[licence] = {
                        "active_targets": set(targets),
                        "last_pos": current_idx,
                        "processed_intervals": set()
                    }
                    
                    # Pass 'now' as the prediction_timestamp
                    register_new_bus_rows(route_name, licence, current_idx, targets, now)
                
                # --- B. ACTUAL ARRIVAL UPDATES ---
                bus_state = tracked_buses[licence]
                prev_pos = bus_state["last_pos"]
                
                if current_idx > prev_pos:
                    passed_targets = sorted([t for t in bus_state["active_targets"] if prev_pos < t <= current_idx])
                    
                    for t in passed_targets:
                        update_actual_arrival(route_name, licence, t, now)
                        bus_state["active_targets"].discard(t)
                    
                    bus_state["last_pos"] = current_idx

                # --- C. PERIODIC ETA PREDICTION ---
                if current_interval_tag is not None:
                    if current_interval_tag not in bus_state["processed_intervals"]:
                        
                        col_name = f"eta_min_T{current_interval_tag}"
                        print(f"[{route_name}] Calculating {col_name} for {licence}...")
                        
                        for t_idx in list(bus_state["active_targets"]):
                            try:
                                eta = calc_eta(current_idx, t_idx, route_name)
                                if eta is not None and eta >= 0:
                                    batch_eta_updates.append({
                                        "licence": licence,
                                        "target_index": t_idx,
                                        "col_name": col_name,
                                        "value": eta
                                    })
                            except Exception as e:
                                pass 

                        bus_state["processed_intervals"].add(current_interval_tag)

            # 4. Execute Batch Writes
            if batch_eta_updates:
                batch_update_predictions(route_name, batch_eta_updates)

        except Exception as e:
            print(f"[{route_name}] LOOP ERROR: {e}")

        time.sleep(CHECK_INTERVAL_SEC)

# =========================================================
#              MULTI-ROUTE SUPERVISOR
# =========================================================

def start_multi_route_monitor(route_list):
    initialize_csv_if_needed()
    
    threads = []
    for route in route_list:
        t = threading.Thread(target=evaluate_bus_eta, args=(route,), daemon=True)
        t.start()
        threads.append(t)
        print(f"[SYSTEM] Started route thread: {route}")

    print(f"\n[SYSTEM] Monitoring started at {SCRIPT_START_TIME}. Press CTRL+C to stop.\n")

    try:
        while any(t.is_alive() for t in threads):
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[SYSTEM] Shutdown requested.")
        shutdown_event.set()
        for t in threads:
            t.join()
    print("[SYSTEM] All threads stopped cleanly.")

if __name__ == "__main__":
    ROUTES = [
        "Airport -> Rawai",
        "Rawai -> Airport",
        "Patong -> Bus 1 -> Bus 2",
        "Bus 2 -> Bus 1 -> Patong",
        "Dragon Line",
    ]

    start_multi_route_monitor(ROUTES)