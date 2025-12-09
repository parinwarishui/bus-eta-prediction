import os
import time
import pandas as pd
import numpy as np
import threading
import traceback
from datetime import datetime, timedelta
from dotenv import load_dotenv

# --- DEBUG PRINT: Check if imports work ---
print("[SYSTEM] Imports successful. Starting configuration...")

try:
    from services import (
        get_bus_data, 
        collect_bus_history, 
        load_route_coords, 
        filter_bus, 
        map_index_df, 
        calc_eta, 
        ORDERS_PER_KM,
        API_KEY,
        API_URL
    )
    from stop_access import direction_map, line_options
except ImportError as e:
    print(f"\n[CRITICAL ERROR] Could not import helper files: {e}")
    print("Ensure 'services.py' and 'stop_access.py' are in the same folder.\n")
    exit(1)

# Config
CHECK_INTERVAL_SEC = 30
STALL_THRESHOLD_MIN = 10
OFFLINE_GRACE_PERIOD_MIN = 5  
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Files
ACTIVE_CSV = os.path.join(BASE_DIR, "eta_accuracy_by_stop.csv") 
ARCHIVE_CSV = os.path.join(BASE_DIR, "eta_accuracy_archive.csv")  

# Define prediction intervals
PRED_INTERVALS = [0, 15, 30, 45, 60, 75, 90, 105, 120] 

load_dotenv()

csv_lock = threading.Lock()
shutdown_event = threading.Event()

# =========================================================
#   ARCHIVE & CSV HELPERS
# =========================================================

def get_expected_columns():
    cols = [
        "licence", "route", "stop_id", "stop_name", "stop_index", 
        "registration_time", "arrival_time"
    ]
    for t in PRED_INTERVALS:
        cols.append(f"eta_min_T{t}")
        cols.append(f"eta_ts_T{t}")
        cols.append(f"error_T{t}")
    return cols

def validate_and_recreate_csv(filepath, cols):
    """Checks if CSV exists and has correct headers. If not, recreates it."""
    recreate = False
    if os.path.exists(filepath):
        try:
            df_test = pd.read_csv(filepath, nrows=0)
            if 'stop_index' not in df_test.columns:
                print(f"[SYSTEM] Corrupted headers in {os.path.basename(filepath)}. Recreating...")
                recreate = True
        except Exception:
            print(f"[SYSTEM] Could not read {os.path.basename(filepath)}. Recreating...")
            recreate = True
    else:
        recreate = True

    if recreate:
        try:
            pd.DataFrame(columns=cols).to_csv(filepath, index=False)
            print(f"[SYSTEM] Initialized clean file: {os.path.basename(filepath)}")
        except Exception as e:
            print(f"[CRITICAL] Failed to create CSV {filepath}: {e}")

def initialize_csvs():
    """Validates/Creates the ARCHIVE file and DESTROYS/Re-creates the ACTIVE file."""
    cols = get_expected_columns()

    with csv_lock:
        validate_and_recreate_csv(ARCHIVE_CSV, cols)

        if os.path.exists(ACTIVE_CSV):
            try:
                os.remove(ACTIVE_CSV)
                print(f"[SYSTEM] Removed old active file: {os.path.basename(ACTIVE_CSV)}")
            except OSError as e:
                print(f"[SYSTEM] Warning: Could not delete old active file: {e}")

        try:
            pd.DataFrame(columns=cols).to_csv(ACTIVE_CSV, index=False)
            print(f"[SYSTEM] Created fresh active file: {os.path.basename(ACTIVE_CSV)}")
        except Exception as e:
            print(f"[CRITICAL] Failed to create active CSV: {e}")

def transfer_to_archive(row_index, df_current):
    try:
        row_to_move = df_current.iloc[[row_index]]
        row_to_move.to_csv(ARCHIVE_CSV, mode='a', header=False, index=False)
        df_updated = df_current.drop(row_index)
        return df_updated
    except Exception as e:
        print(f"[ARCHIVE ERROR] Failed to transfer data: {e}")
        return df_current

# =========================================================
#   CORE LOGIC
# =========================================================

def register_new_bus_stops(route_name, licence, upcoming_stops, reg_time, current_speed, current_idx):
    reg_time_iso = reg_time.isoformat()
    new_rows = []
    
    existing_stop_indices = set()
    
    with csv_lock:
        try:
            if os.path.exists(ACTIVE_CSV):
                df = pd.read_csv(ACTIVE_CSV)
                if 'licence' in df.columns and 'stop_index' in df.columns:
                    mask = (
                        (df['licence'] == licence) & 
                        (df['route'] == route_name) & 
                        (df['arrival_time'].isna())
                    )
                    if mask.any():
                        existing_stop_indices = set(df.loc[mask, 'stop_index'].astype(int).tolist())
        except: pass

    # === [UPDATED] GET LAYOVER CONFIG ===
    route_config = direction_map.get(route_name)
    current_layover_idx = None
    if route_config and route_config.layover:
        current_layover_idx = route_config.layover.get('stop_index')

    for stop in upcoming_stops:
        if stop['index'] in existing_stop_indices: continue

        t0_eta = pd.NA
        t0_ts = pd.NA
        try:
            eta_val = calc_eta(
                current_idx, 
                stop['index'], 
                route_name, 
                current_speed,
                layover_idx=current_layover_idx  # <--- Pass Index
            )
            if eta_val is not None and eta_val >= 0:
                t0_eta = eta_val
                t0_ts = (reg_time + timedelta(minutes=eta_val)).isoformat()
        except: pass

        row = {
            "licence": licence, "route": route_name,
            "stop_id": str(stop['no']), "stop_name": stop['stop_name_eng'],
            "stop_index": stop['index'], "registration_time": reg_time_iso,
            "arrival_time": pd.NA,
            "eta_min_T0": t0_eta,
            "eta_ts_T0": t0_ts,
            "error_T0": pd.NA 
        }
        
        for t in PRED_INTERVALS:
            if t == 0: continue 
            row[f"eta_min_T{t}"] = pd.NA
            row[f"eta_ts_T{t}"] = pd.NA
            row[f"error_T{t}"] = pd.NA
            
        new_rows.append(row)

    if new_rows:
        df_new = pd.DataFrame(new_rows)
        with csv_lock:
            try:
                df_new.to_csv(ACTIVE_CSV, mode='a', header=False, index=False)
                print(f"[{route_name}] NEW BUS: {licence} (Registered {len(new_rows)} stops with T0)")
            except Exception as e:
                print(f"[{route_name}] Error registering: {e}")

def update_actual_arrival(route_name, licence, stop_index, actual_time):
    with csv_lock:
        try:
            df = pd.read_csv(ACTIVE_CSV)
            if 'stop_index' not in df.columns: return

            df['clean_stop_idx'] = df['stop_index'].apply(lambda x: str(int(float(x))) if pd.notna(x) else "")
            target_idx_str = str(int(float(stop_index)))
            
            mask = (
                (df["licence"] == licence) & 
                (df["route"] == route_name) & 
                (df["clean_stop_idx"] == target_idx_str) &
                (df["arrival_time"].isna())
            )
            
            if mask.any():
                row_idx = df[mask].index[-1]
                df.at[row_idx, "arrival_time"] = actual_time.isoformat()
                
                for t in PRED_INTERVALS:
                    ts_col = f"eta_ts_T{t}"
                    err_col = f"error_T{t}"
                    if pd.notna(df.at[row_idx, ts_col]):
                        try:
                            pred_dt = pd.to_datetime(df.at[row_idx, ts_col])
                            diff = (actual_time - pred_dt).total_seconds() / 60.0
                            df.at[row_idx, err_col] = round(diff, 2)
                        except: pass

                df = df.drop(columns=['clean_stop_idx'])
                df = transfer_to_archive(row_idx, df)
                df.to_csv(ACTIVE_CSV, index=False)
                print(f"[{route_name}] {licence} ARRIVED @ {stop_index} -> Archived")
        except Exception as e:
            print(f"[{route_name}] Update Error: {e}")
            traceback.print_exc()

def batch_update_predictions(route_name, updates):
    if not updates: return
    with csv_lock:
        try:
            df = pd.read_csv(ACTIVE_CSV)
            if 'stop_index' not in df.columns: return

            def clean_stop_idx(val):
                try: return str(int(float(val)))
                except: return str(val)
                
            df['clean_stop_idx'] = df['stop_index'].apply(clean_stop_idx)
            df['match_key'] = df['route'] + "_" + df['licence'] + "_" + df['clean_stop_idx']
            
            for u in updates:
                key = f"{route_name}_{u['licence']}_{str(u['stop_index'])}"
                mask = df['match_key'] == key
                
                if mask.any():
                    active_indices = df[mask & df['arrival_time'].isna()].index
                    for idx in active_indices:
                        for col, val in u['updates'].items():
                            curr = df.at[idx, col]
                            if pd.isna(curr) or str(curr).strip() == "":
                                df.at[idx, col] = val
            
            df.drop(columns=['match_key', 'clean_stop_idx'], inplace=True)
            df.to_csv(ACTIVE_CSV, index=False)
            print(f"[{route_name}] Updated {len(updates)} predictions.")
        except Exception as e:
            print(f"[{route_name}] Batch Update Error: {e}")
            traceback.print_exc()

# =========================================================
#   MAIN LOOP
# =========================================================

def evaluate_bus_eta(route_name):
    print(f"\n--- [{route_name}] Thread Started ---")
    tracked_buses = {} 
    
    try:
        route_config = direction_map[route_name]
    except Exception as e:
        print(f"[{route_name}] Setup failed: {e}")
        return

    # === [UPDATED] PRE-LOAD LAYOVER INDEX FOR THIS THREAD ===
    current_layover_idx = None
    if route_config and route_config.layover:
        current_layover_idx = route_config.layover.get('stop_index')

    while not shutdown_event.is_set():
        try:
            now = datetime.now()
            df_raw = get_bus_data(API_URL, API_KEY)
            df_hist = collect_bus_history(df_raw)
            buses_on_route = filter_bus(df_hist, route_name)
            buses_on_route = buses_on_route.loc[:, ~buses_on_route.columns.duplicated()]
            mapped_df = map_index_df(buses_on_route, route_name)
            
            batch_updates = []
            current_active_licences = set()

            if not mapped_df.empty:
                for _, bus_row in mapped_df.iterrows():
                    licence = bus_row["licence"]
                    if pd.isna(bus_row.get("bus_index")): continue
                    
                    current_idx = int(bus_row["bus_index"])
                    velocity = float(bus_row.get("spd", 0))
                    current_active_licences.add(licence)

                    # --- A. Initialize Bus ---
                    is_new = licence not in tracked_buses
                    if not is_new:
                        if current_idx < tracked_buses[licence]["last_pos"] - (ORDERS_PER_KM * 2):
                            is_new = True 

                    if is_new:
                        if current_idx < 50 and velocity == 0: continue
                        stops_dict_values = route_config.stop_list.values()
                        upcoming_stops = [s for s in stops_dict_values if s['index'] > current_idx]
                        if not upcoming_stops: continue
                        upcoming_stops.sort(key=lambda x: x['index'])

                        register_new_bus_stops(route_name, licence, upcoming_stops, now, velocity, current_idx)

                        tracked_buses[licence] = {
                            "active_stop_indices": [s['index'] for s in upcoming_stops],
                            "last_pos": current_idx,
                            "processed_intervals": {0}, 
                            "start_time": now,
                            "last_seen_time": now,
                            "last_move_time": now,
                            "is_stalled": False
                        }
                    else:
                        tracked_buses[licence]["last_seen_time"] = now

                    bus_state = tracked_buses.get(licence)
                    if not bus_state: continue

                    if velocity > 0.5:
                        bus_state["last_move_time"] = now
                        bus_state["is_stalled"] = False
                    else:
                        if (now - bus_state["last_move_time"]).total_seconds() / 60 > STALL_THRESHOLD_MIN:
                            bus_state["is_stalled"] = True

                    prev_pos = bus_state["last_pos"]
                    passed_indices = [idx for idx in bus_state["active_stop_indices"] if prev_pos < idx <= current_idx]
                    
                    for p_idx in passed_indices:
                        update_actual_arrival(route_name, licence, p_idx, now)
                        bus_state["active_stop_indices"].remove(p_idx)
                    
                    bus_state["last_pos"] = current_idx

                    if not bus_state["is_stalled"] and bus_state["active_stop_indices"]:
                        elapsed_min = (now - bus_state["start_time"]).total_seconds() / 60.0
                        for t in PRED_INTERVALS:
                            if t == 0: continue 
                            
                            if elapsed_min >= t and t not in bus_state["processed_intervals"]:
                                for stop_idx in bus_state["active_stop_indices"]:
                                    try:
                                        # === [UPDATED] PASS LAYOVER INDEX ===
                                        eta_min = calc_eta(
                                            current_idx, 
                                            stop_idx, 
                                            route_name, 
                                            velocity,
                                            layover_idx=current_layover_idx  # <--- HERE
                                        )
                                        if eta_min is not None and eta_min >= 0:
                                            pred_ts = now + timedelta(minutes=eta_min)
                                            batch_updates.append({
                                                "licence": licence,
                                                "stop_index": stop_idx,
                                                "updates": {
                                                    f"eta_min_T{t}": eta_min,
                                                    f"eta_ts_T{t}": pred_ts.isoformat()
                                                }
                                            })
                                    except: pass
                                bus_state["processed_intervals"].add(t)

                    if not bus_state["active_stop_indices"]:
                        if licence in tracked_buses: del tracked_buses[licence]
                        current_active_licences.discard(licence)

            keys_to_delete = []
            for lic, state in tracked_buses.items():
                if lic not in current_active_licences:
                    time_offline = (now - state["last_seen_time"]).total_seconds() / 60.0
                    if time_offline > OFFLINE_GRACE_PERIOD_MIN:
                        keys_to_delete.append(lic)
            
            for lic in keys_to_delete:
                print(f"[{route_name}] Bus {lic} timed out.")
                del tracked_buses[lic]

            if batch_updates:
                batch_update_predictions(route_name, batch_updates)

        except Exception as e:
            print(f"[{route_name}] LOOP ERROR: {e}")
            traceback.print_exc()
        
        time.sleep(CHECK_INTERVAL_SEC)

def start_multi_route_monitor(route_list):
    initialize_csvs()
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
        for t in threads: t.join()

if __name__ == "__main__":
    from stop_access import line_options
    print("Starting Auto-Archiving Accuracy Monitor...")
    start_multi_route_monitor(line_options)