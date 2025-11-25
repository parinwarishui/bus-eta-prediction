import os
import time
import pandas as pd
import numpy as np
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv

# --- DEBUG PRINT: Check if imports work ---
print("[SYSTEM] Imports successful. Starting configuration...")

# Import from the monolithic services file
try:
    from services import (
        get_bus_data, 
        collect_bus_history, 
        load_route_coords, 
        filter_bus, 
        map_index_df, 
        calc_eta, 
        ORDERS_PER_KM
    )
    from stop_access import direction_map
except ImportError as e:
    print(f"\n[CRITICAL ERROR] Could not import helper files: {e}")
    print("Ensure 'services.py' and 'stop_access.py' are in the same folder.\n")
    exit(1)

# Config
CHECK_INTERVAL_SEC = 30
STALL_THRESHOLD_MIN = 10
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# FIX: Force CSV to be created in the exact same folder as this script
EVALUATION_CSV = os.path.join(BASE_DIR, "eta_predictions_with_stall_logic.csv")

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
    print(f"[SYSTEM] Checking CSV at: {EVALUATION_CSV}")
    if not os.path.exists(EVALUATION_CSV):
        print("[SYSTEM] CSV not found. Creating new file...")
        cols = ["licence", "route", "start_bus_index", "target_km", "target_index", "prediction_timestamp", "arrival_time"]
        for t in PRED_INTERVALS:
            cols.append(f"eta_min_T{t}")
        df = pd.DataFrame(columns=cols)
        with csv_lock:
            try:
                df.to_csv(EVALUATION_CSV, index=False)
                print("[SYSTEM] CSV successfully created.")
            except PermissionError:
                print(f"[CRITICAL] Permission denied. Cannot write to {EVALUATION_CSV}")
            except Exception as e:
                print(f"[CRITICAL] Failed to create CSV: {e}")
    else:
        print("[SYSTEM] CSV exists. Appending to existing file.")

def register_new_bus_rows(route_name, licence, start_index, targets, prediction_time):
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
        for t in PRED_INTERVALS:
            row[f"eta_min_T{t}"] = pd.NA
        rows.append(row)
    df_new = pd.DataFrame(rows)
    with csv_lock:
        try:
            df_new.to_csv(EVALUATION_CSV, mode='a', header=False, index=False)
        except Exception as e:
            print(f"[{route_name}] Error registering bus {licence}: {e}")
    print(f"[{route_name}] NEW BUS: {licence} (Start Time: {prediction_time.strftime('%H:%M:%S')})")

def update_actual_arrival(route_name, licence, target_index, actual_time):
    with csv_lock:
        try:
            df = pd.read_csv(EVALUATION_CSV)
            mask = ((df["licence"] == licence) & (df["route"] == route_name) & (df["target_index"] == target_index))
            if mask.any():
                subset = df.loc[mask, "arrival_time"]
                if pd.isna(subset).any():
                    df.loc[mask, "arrival_time"] = actual_time
                    df.to_csv(EVALUATION_CSV, index=False)
                    print(f"[{route_name}] {licence} ARRIVED at target {target_index}")
        except Exception as e:
            print(f"[{route_name}] Error updating actuals: {e}")

def batch_update_predictions(route_name, updates):
    if not updates: return
    with csv_lock:
        try:
            df = pd.read_csv(EVALUATION_CSV)
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
    tracked_buses = {} 
    
    try:
        route_config = direction_map[route_name]
        geojson_full_path = os.path.join(BASE_DIR, route_config.geojson_path)
        coords = load_route_coords(geojson_full_path)
        max_route_index = max(o for o, lon, lat in coords)
    except Exception as e:
        print(f"[{route_name}] Setup failed: {e}")
        return

    while not shutdown_event.is_set():
        try:
            now = datetime.now()
            
            # 1. Fetch and Process Data
            df_raw = get_bus_data(API_URL, API_KEY)
            df_hist = collect_bus_history(df_raw)
            buses_on_route = filter_bus(df_hist, route_name)
            mapped_df = map_index_df(buses_on_route, route_name)
            
            batch_eta_updates = []
            current_active_licences = set()

            if not mapped_df.empty:
                for _, bus_row in mapped_df.iterrows():
                    licence = bus_row["licence"]
                    if pd.isna(bus_row["bus_index"]): continue
                    
                    current_idx = int(bus_row["bus_index"])
                    velocity = bus_row.get("velocity", 0) 
                    current_active_licences.add(licence)

                    # --- A. Initialize or Reset Bus ---
                    is_new = licence not in tracked_buses
                    
                    if not is_new:
                        prev_idx = tracked_buses[licence]["last_pos"]
                        if current_idx < prev_idx - (ORDERS_PER_KM * 2):
                            is_new = True

                    if is_new:
                        start_km = (current_idx // ORDERS_PER_KM) + 1
                        first_target = start_km * ORDERS_PER_KM
                        targets = list(range(first_target, max_route_index + 1, ORDERS_PER_KM))
                        
                        if max_route_index not in targets and max_route_index > current_idx: 
                            targets.append(max_route_index)
                        
                        if not targets:
                            continue

                        tracked_buses[licence] = {
                            "active_targets": set(targets),
                            "last_pos": current_idx,
                            "processed_intervals": set(),
                            "start_time": now,
                            "last_move_time": now,
                            "is_stalled": False
                        }
                        register_new_bus_rows(route_name, licence, current_idx, targets, now)
                    
                    # --- B. Update Status ---
                    bus_state = tracked_buses[licence]
                    
                    if velocity > 0.5:
                        bus_state["last_move_time"] = now
                        bus_state["is_stalled"] = False
                    else:
                        time_stationary = (now - bus_state["last_move_time"]).total_seconds() / 60
                        if time_stationary > STALL_THRESHOLD_MIN:
                            if not bus_state["is_stalled"]:
                                print(f"[{route_name}] Bus {licence} STALLED (No move > {STALL_THRESHOLD_MIN} min)")
                            bus_state["is_stalled"] = True

                    prev_pos = bus_state["last_pos"]
                    if current_idx > prev_pos:
                        passed_targets = sorted([t for t in bus_state["active_targets"] if prev_pos < t <= current_idx])
                        for t in passed_targets:
                            update_actual_arrival(route_name, licence, t, now)
                            bus_state["active_targets"].discard(t)
                        bus_state["last_pos"] = current_idx

                    # --- C. Trigger ETA Prediction ---
                    if not bus_state["is_stalled"] and bus_state["active_targets"]:
                        bus_elapsed_min = (now - bus_state["start_time"]).total_seconds() / 60
                        
                        for interval_t in PRED_INTERVALS:
                            if bus_elapsed_min >= interval_t and interval_t not in bus_state["processed_intervals"]:
                                col_name = f"eta_min_T{interval_t}"
                                
                                # FIX: Sort targets to ensure we calculate closest -> furthest
                                sorted_targets = sorted(list(bus_state["active_targets"]))
                                last_valid_eta = 0 
                                
                                for t_idx in sorted_targets:
                                    if current_idx >= t_idx: continue
                                    
                                    try:
                                        eta = calc_eta(current_idx, t_idx, route_name)
                                        
                                        # --- MONOTONIC SANITY CHECK ---
                                        # If calculated ETA is LESS than the previous stop's ETA, 
                                        # it's a glitch (data gap or math error). Correct it.
                                        if eta is not None:
                                            if eta < last_valid_eta and last_valid_eta > 0:
                                                # Auto-fix: Assume it takes at least 1 min more than previous stop
                                                eta = last_valid_eta + 1.0 
                                            
                                            # If ETA is 0 but distance is significant (e.g. > 1km), fix it
                                            if eta == 0 and (t_idx - current_idx) > ORDERS_PER_KM:
                                                eta = max(1.0, last_valid_eta + 1.0)

                                        if eta is not None and eta >= 0:
                                            batch_eta_updates.append({
                                                "licence": licence,
                                                "target_index": t_idx,
                                                "col_name": col_name,
                                                "value": eta
                                            })
                                            last_valid_eta = eta
                                            
                                    except Exception: pass
                                
                                bus_state["processed_intervals"].add(interval_t)
                    
                    # --- D. Cleanup ---
                    if not bus_state["active_targets"]:
                        print(f"[{route_name}] Bus {licence} COMPLETED route. Removing.")
                        del tracked_buses[licence]
                        current_active_licences.discard(licence) 
                        break 

            # Remove vanished buses
            known_licences = list(tracked_buses.keys())
            for lic in known_licences:
                if lic not in current_active_licences:
                    del tracked_buses[lic]

            if batch_eta_updates:
                batch_update_predictions(route_name, batch_eta_updates)

        except Exception as e:
            print(f"[{route_name}] LOOP ERROR: {e}")
            import traceback
            traceback.print_exc()
        
        time.sleep(CHECK_INTERVAL_SEC)

def start_multi_route_monitor(route_list):
    initialize_csv_if_needed()
    threads = []
    for route in route_list:
        t = threading.Thread(target=evaluate_bus_eta, args=(route,), daemon=True)
        t.start()
        threads.append(t)
        print(f"[SYSTEM] Thread launched: {route}")

    try:
        while any(t.is_alive() for t in threads):
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown_event.set()
        print("\n[SYSTEM] Stopping threads...")
        for t in threads:
            t.join()
        print("[SYSTEM] Shutdown complete.")

if __name__ == "__main__":
    ROUTES = [
        "Airport -> Rawai",
        "Rawai -> Airport",
        "Patong -> Bus 1 -> Bus 2",
        "Bus 2 -> Bus 1 -> Patong",
        "Dragon Line",
    ]
    start_multi_route_monitor(ROUTES)