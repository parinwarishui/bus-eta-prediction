import os
import time
import pandas as pd
import numpy as np
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv

# === Import from services ===
from services import (
    get_bus_data, 
    collect_bus_history, 
    filter_bus, 
    map_index_df, 
    calc_eta, 
    ORDERS_PER_KM
)
from stop_access import direction_map

# Config
CHECK_INTERVAL_SEC = 30
EVALUATION_CSV = "eta_predictions_stops_benchmark.csv"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Define prediction intervals
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
    if not os.path.exists(EVALUATION_CSV):
        cols = [
            "licence", "route", "start_bus_index", "stop_name", "stop_route_index", 
            "prediction_timestamp", "arrival_time"
        ]
        for t in PRED_INTERVALS:
            cols.append(f"eta_min_T{t}")
        
        df = pd.DataFrame(columns=cols)
        with csv_lock:
            df.to_csv(EVALUATION_CSV, index=False)
        print("[SYSTEM] CSV initialized.")

def register_new_bus_rows(route_name, licence, start_index, target_stops, prediction_time):
    rows = []
    for stop in target_stops:
        row = {
            "licence": licence,
            "route": route_name,
            "start_bus_index": start_index,
            "stop_name": stop['stop_name_eng'],
            "stop_route_index": stop['index'], # ใช้ค่า index จาก stop_list โดยตรง
            "prediction_timestamp": prediction_time,
            "arrival_time": pd.NA
        }
        for t in PRED_INTERVALS:
            row[f"eta_min_T{t}"] = pd.NA
        rows.append(row)

    if not rows:
        return

    df_new = pd.DataFrame(rows)
    with csv_lock:
        try:
            # Append mode: header=False if file exists
            header = not os.path.exists(EVALUATION_CSV)
            df_new.to_csv(EVALUATION_CSV, mode='a', header=header, index=False)
        except Exception as e:
            print(f"[{route_name}] Error registering bus {licence}: {e}")

    print(f"[{route_name}] NEW BUS: {licence} (Tracking {len(rows)} future stops)")

def update_actual_arrival(route_name, licence, stop_name, actual_time):
    with csv_lock:
        try:
            df = pd.read_csv(EVALUATION_CSV)
            mask = (
                (df["licence"] == licence) & 
                (df["route"] == route_name) & 
                (df["stop_name"] == stop_name)
            )
            if mask.any():
                # Only update if not already arrived
                if pd.isna(df.loc[mask, "arrival_time"]).to_numpy().flatten().any():
                    df.loc[mask, "arrival_time"] = actual_time
                    df.to_csv(EVALUATION_CSV, index=False)
                    print(f"[{route_name}] {licence} ARRIVED at {stop_name}")
        except Exception as e:
            print(f"[{route_name}] Error updating actuals: {e}")

def batch_update_predictions(route_name, updates):
    if not updates: return
    with csv_lock:
        try:
            df = pd.read_csv(EVALUATION_CSV)
            # Create match key for faster lookup
            df['match_key'] = df['route'] + "_" + df['licence'] + "_" + df['stop_name']
            
            updated_count = 0
            for u in updates:
                key = f"{route_name}_{u['licence']}_{u['stop_name']}"
                mask = df['match_key'] == key
                if mask.any():
                    # Overwrite to get latest prediction
                    df.loc[mask, u['col_name']] = round(u['value'], 2)
                    updated_count += 1
            
            df.drop(columns=['match_key'], inplace=True)
            df.to_csv(EVALUATION_CSV, index=False)
            # if updated_count > 0:
            #     print(f"[{route_name}] Updated {updated_count} predictions.")
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
        stop_list = route_config.stop_list
        
        # Debug: Print first stop to verify index loading
        if stop_list:
            print(f"[{route_name}] Loaded {len(stop_list)} stops. First stop index: {stop_list[0].get('index')}")
            
    except Exception as e:
        print(f"[{route_name}] Setup failed: {e}")
        return

    while not shutdown_event.is_set():
        try:
            now = datetime.now()
            
            # 1. Get Data via SERVICES
            df_raw = get_bus_data(API_URL, API_KEY)
            # df_hist = collect_bus_history(df_raw) # Optional: Enable if history needed
            buses_on_route = filter_bus(df_raw, route_name)
            mapped_df = map_index_df(buses_on_route, route_name)

            batch_eta_updates = []
            
            if not mapped_df.empty:
                for _, bus_row in mapped_df.iterrows():
                    licence = bus_row["licence"]
                    if pd.isna(bus_row["bus_index"]): continue
                    current_idx = int(bus_row["bus_index"])
                    
                    # --- A. NEW BUS REGISTRATION ---
                    is_new = licence not in tracked_buses
                    
                    if not is_new:
                        prev_idx = tracked_buses[licence]["last_pos"]
                        # Loop detection
                        if current_idx < prev_idx - (ORDERS_PER_KM * 2):
                            print(f"[{route_name}] {licence} RESTART detected ({prev_idx} -> {current_idx}).")
                            is_new = True

                    if is_new:
                        future_stops = []
                        for stop in stop_list:
                            # DIRECT ACCESS to 'index' as per your file structure
                            s_idx = stop.get('index')
                            
                            # Safety fallback only if key missing (should not happen based on your info)
                            if s_idx is None: 
                                print(f"[WARNING] Stop {stop.get('stop_name_eng')} missing index!")
                                continue

                            # Add if bus hasn't passed it yet
                            if s_idx > current_idx:
                                future_stops.append(stop)
                        
                        if future_stops:
                            tracked_buses[licence] = {
                                "active_targets": future_stops,
                                "last_pos": current_idx,
                                "processed_intervals": set(),
                                "start_time": now
                            }
                            register_new_bus_rows(route_name, licence, current_idx, future_stops, now)
                        else:
                            # Bus is past all stops (end of route)
                            pass

                    if licence not in tracked_buses:
                        continue

                    # --- B. MOVEMENT & ARRIVAL UPDATES ---
                    bus_state = tracked_buses[licence]
                    prev_pos = bus_state["last_pos"]
                    
                    if current_idx > prev_pos:
                        remaining_targets = []
                        for stop in bus_state["active_targets"]:
                            s_idx = stop['index']
                            if current_idx >= s_idx:
                                # Bus passed stop index -> ARRIVED
                                update_actual_arrival(route_name, licence, stop['stop_name_eng'], now)
                            else:
                                remaining_targets.append(stop)
                        
                        bus_state["active_targets"] = remaining_targets
                        bus_state["last_pos"] = current_idx

                    # --- C. INTERVAL CHECK ---
                    bus_elapsed_min = (now - bus_state["start_time"]).total_seconds() / 60
                    
                    for interval_t in PRED_INTERVALS:
                        if bus_elapsed_min >= interval_t and interval_t not in bus_state["processed_intervals"]:
                            
                            if bus_state["active_targets"]:
                                col_name = f"eta_min_T{interval_t}"
                                for stop in bus_state["active_targets"]:
                                    stop_idx = stop['index']
                                    stop_name = stop['stop_name_eng']
                                    
                                    try:
                                        eta = calc_eta(current_idx, stop_idx, route_name)
                                        if eta is not None and eta >= 0:
                                            batch_eta_updates.append({
                                                "licence": licence,
                                                "stop_name": stop_name,
                                                "col_name": col_name,
                                                "value": eta
                                            })
                                    except: pass
                            
                            bus_state["processed_intervals"].add(interval_t)

            # 3. Execute Batch Writes
            if batch_eta_updates:
                batch_update_predictions(route_name, batch_eta_updates)

        except Exception as e:
            print(f"[{route_name}] LOOP ERROR: {e}")
        
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