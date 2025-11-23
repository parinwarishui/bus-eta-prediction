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
EVALUATION_CSV = "eta_predictions_2111_2.csv"

# Define prediction intervals (minutes from BUS DISCOVERY)
PRED_INTERVALS = [0, 15, 30, 45, 60, 75, 90, 105, 120] 

load_dotenv()
API_KEY = os.getenv("API_KEY")
API_URL = "https://smartbus-pk-api.phuket.cloud/api/bus-news-2/"

csv_lock = threading.Lock()
shutdown_event = threading.Event()

# =========================================================
#   CSV HELPERS
# =========================================================

def initialize_csv_if_needed():
    """Creates the CSV with the dynamic time columns if it doesn't exist."""
    if not os.path.exists(EVALUATION_CSV):
        cols = [
            "licence", 
            "route", 
            "start_bus_index", 
            "target_km", 
            "target_index", 
            "prediction_timestamp",  # This is T0 (Bus Start Time)
            "arrival_time"
        ]
        
        # Add dynamic columns for ETA intervals
        for t in PRED_INTERVALS:
            cols.append(f"eta_min_T{t}")
        
        df = pd.DataFrame(columns=cols)
        with csv_lock:
            df.to_csv(EVALUATION_CSV, index=False)
        print("[SYSTEM] CSV initialized.")

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
            "prediction_timestamp": prediction_time,
            "arrival_time": pd.NA
        }
        # Initialize ETA columns as NaN
        for t in PRED_INTERVALS:
            row[f"eta_min_T{t}"] = pd.NA
        rows.append(row)

    df_new = pd.DataFrame(rows)
    
    with csv_lock:
        try:
            # Append mode
            df_new.to_csv(EVALUATION_CSV, mode='a', header=False, index=False)
        except Exception as e:
            print(f"[{route_name}] Error registering bus {licence}: {e}")

    print(f"[{route_name}] NEW BUS: {licence} (Start Time: {prediction_time.strftime('%H:%M:%S')})")

def update_actual_arrival(route_name, licence, target_index, actual_time):
    """Updates the arrival_time when a target is hit."""
    with csv_lock:
        try:
            df = pd.read_csv(EVALUATION_CSV)
            
            # STRICT MATCH: Route + Licence + Target
            mask = (
                (df["licence"] == licence) & 
                (df["route"] == route_name) & 
                (df["target_index"] == target_index)
            )
            
            if mask.any():
                # Robust check: convert to numpy array and flatten to handle 
                # potential duplicate columns or Series/DataFrame ambiguity.
                # This returns a simple boolean if ANY matching row has a NaN arrival time.
                if pd.isna(df.loc[mask, "arrival_time"]).to_numpy().flatten().any():
                    df.loc[mask, "arrival_time"] = actual_time
                    df.to_csv(EVALUATION_CSV, index=False)
                    print(f"[{route_name}] {licence} ARRIVED at target {target_index}")

        except Exception as e:
            print(f"[{route_name}] Error updating actuals: {e}")

def batch_update_predictions(route_name, updates):
    """Efficiently updates multiple ETA predictions at once."""
    if not updates:
        return

    with csv_lock:
        try:
            df = pd.read_csv(EVALUATION_CSV)
            
            # Key format: "RouteName_Licence_TargetIndex"
            df['match_key'] = df['route'] + "_" + df['licence'] + "_" + df['target_index'].astype(str)
            
            for u in updates:
                key = f"{route_name}_{u['licence']}_{u['target_index']}"
                mask = df['match_key'] == key
                if mask.any():
                    df.loc[mask, u['col_name']] = round(u['value'], 2)
            
            df.drop(columns=['match_key'], inplace=True)
            df.to_csv(EVALUATION_CSV, index=False)
            print(f"[{route_name}] Recorded {len(updates)} ETA predictions.")
            
        except Exception as e:
            print(f"[{route_name}] Error in batch update: {e}")

# =========================================================
#   MAIN EVALUATION LOOP
# =========================================================

def evaluate_bus_eta(route_name):
    print(f"\n--- [{route_name}] Thread Started ---")

    # tracked_buses stores state per bus
    tracked_buses = {} 
    
    try:
        coords = load_route_coords(direction_map[route_name]["geojson_path"])
        max_route_index = max(o for o, lon, lat in coords)
    except Exception as e:
        print(f"[{route_name}] Setup failed (geojson error?): {e}")
        return

    while not shutdown_event.is_set():
        try:
            now = datetime.now()

            # 1. Get Data
            df_raw = get_bus_data(API_URL, API_KEY)
            df_hist = collect_bus_history(df_raw)
            buses_on_route = filter_bus(df_hist, route_name)
            mapped_df = map_index_df(buses_on_route, route_name)

            # 2. Process Buses
            batch_eta_updates = []
            
            if not mapped_df.empty:
                for _, bus_row in mapped_df.iterrows():
                    licence = bus_row["licence"]
                    current_idx = int(bus_row["bus_index"])
                    
                    # --- A. NEW BUS REGISTRATION ---
                    is_new = licence not in tracked_buses
                    
                    # Check for restart (looping)
                    if not is_new:
                        prev_idx = tracked_buses[licence]["last_pos"]
                        if current_idx < prev_idx - (ORDERS_PER_KM * 2):
                            print(f"[{route_name}] {licence} RESTART (Jump {prev_idx} -> {current_idx}). Resetting.")
                            is_new = True

                    if is_new:
                        start_km = (current_idx // ORDERS_PER_KM) + 1
                        first_target = start_km * ORDERS_PER_KM
                        targets = list(range(first_target, max_route_index + 1, ORDERS_PER_KM))
                        if max_route_index not in targets:
                            targets.append(max_route_index)
                        
                        tracked_buses[licence] = {
                            "active_targets": set(targets),
                            "last_pos": current_idx,
                            "processed_intervals": set(),
                            "start_time": now  # Set T0 for this specific bus
                        }
                        
                        register_new_bus_rows(route_name, licence, current_idx, targets, now)
                    
                    # --- B. MOVEMENT & ARRIVAL UPDATES ---
                    bus_state = tracked_buses[licence]
                    prev_pos = bus_state["last_pos"]
                    
                    if current_idx > prev_pos:
                        # Stop calculating for rows passed
                        passed_targets = sorted([t for t in bus_state["active_targets"] if prev_pos < t <= current_idx])
                        for t in passed_targets:
                            update_actual_arrival(route_name, licence, t, now)
                            bus_state["active_targets"].discard(t) # REMOVES target from future calcs
                        bus_state["last_pos"] = current_idx

                    # --- C. INTERVAL CHECK (INDIVIDUAL) ---
                    bus_elapsed_min = (now - bus_state["start_time"]).total_seconds() / 60
                    
                    for interval_t in PRED_INTERVALS:
                        if bus_elapsed_min >= interval_t and interval_t not in bus_state["processed_intervals"]:
                            
                            if bus_state["active_targets"]:
                                col_name = f"eta_min_T{interval_t}"
                                
                                # Calculate predictions only for ACTIVE targets
                                for t_idx in list(bus_state["active_targets"]):
                                    
                                    # SAFETY CHECK: Ensure we don't calc for passed targets
                                    if current_idx >= t_idx:
                                        continue 

                                    try:
                                        eta = calc_eta(current_idx, t_idx, route_name)
                                        if eta is not None and eta >= 0:
                                            batch_eta_updates.append({
                                                "licence": licence,
                                                "target_index": t_idx,
                                                "col_name": col_name,
                                                "value": eta
                                            })
                                    except Exception:
                                        pass 
                            
                            bus_state["processed_intervals"].add(interval_t)

            # 3. Execute Batch Writes
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
        print(f"[SYSTEM] Thread launched: {route}")

    print(f"\n[SYSTEM] Monitoring active. Waiting for buses...")

    try:
        while any(t.is_alive() for t in threads):
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[SYSTEM] Stopping threads...")
        shutdown_event.set()
        for t in threads:
            t.join()
    print("[SYSTEM] Done.")

if __name__ == "__main__":
    ROUTES = [
        "Airport -> Rawai",
        "Rawai -> Airport",
        "Patong -> Bus 1 -> Bus 2",
        "Bus 2 -> Bus 1 -> Patong",
        "Dragon Line",
    ]

    start_multi_route_monitor(ROUTES)