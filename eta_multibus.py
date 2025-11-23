import os
import time
import pandas as pd
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv

# External imports
from load_files import get_bus_data, collect_bus_history, load_route_coords
from tweak_bus_data import filter_bus, map_index_df, ORDERS_PER_KM
from eta_calculation import calc_eta
from stop_access import direction_map

CHECK_INTERVAL_SEC = 30
ETA_INTERVAL_MIN = 15
KM_CSV = "eta_km_intervals.csv"
STOP_CSV = "eta_bus_stops.csv"

load_dotenv()
API_KEY = os.getenv("API_KEY")
API_URL = "https://smartbus-pk-api.phuket.cloud/api/bus-news-2/"

csv_lock = threading.Lock()
shutdown_event = threading.Event()


# ======================
# CSV UTILITIES
# ======================
def write_initial_predictions(licence, route_name, predictions, csv_file, id_col):
    rows = []
    for p in predictions:
        rows.append({
            "licence": licence,
            "route": route_name,
            "start_index": p.get("start_index"),
            id_col: p[id_col],
            "eta_0min": p["eta_0min"],
            "predicted_arrival_time_0min": p["predicted_arrival_time_0min"],
            "actual_arrival_time": "",
            "time_difference_min": ""
        })
    df = pd.DataFrame(rows).sort_values(id_col)
    with csv_lock:
        df.to_csv(csv_file, mode="a", index=False, header=not os.path.exists(csv_file))


def write_initial_stop_predictions(licence, route_name, predictions, csv_file):
    rows = []
    for p in predictions:
        rows.append({
            "licence": licence,
            "route": route_name,
            "start_index": p.get("start_index"),
            "stop_index": p["stop_index"],
            "stop_no": p["stop_no"],
            "stop_name_eng": p["stop_name_eng"],
            "stop_name_th": p["stop_name_th"],
            "eta_0min": p["eta_0min"],
            "predicted_arrival_time_0min": p["predicted_arrival_time_0min"],
            "actual_arrival_time": "",
            "time_difference_min": ""
        })
    df = pd.DataFrame(rows).sort_values("stop_index")
    with csv_lock:
        df.to_csv(csv_file, mode="a", index=False, header=not os.path.exists(csv_file))


def update_prediction_interval(licence, route_name, id_value, eta, csv_file, id_col, elapsed_min):
    col_name = f"eta_{int(elapsed_min)}min"
    with csv_lock:
        try:
            df = pd.read_csv(csv_file)
            if col_name not in df.columns:
                df[col_name] = ""
            mask = (df["licence"] == licence) & (df[id_col] == id_value)
            df.loc[mask, col_name] = eta
            df.to_csv(csv_file, index=False)
        except Exception as e:
            print(f"[{route_name}] ERROR writing ETA interval to {csv_file}: {e}")


def update_actual_arrival(licence, route_name, id_value, actual_time, diff_min, csv_file, id_col):
    with csv_lock:
        try:
            df = pd.read_csv(csv_file)
            mask = (df["licence"] == licence) & (df[id_col] == id_value)
            if not mask.any():
                return
            df.loc[mask, "actual_arrival_time"] = actual_time
            df.loc[mask, "time_difference_min"] = diff_min
            df.to_csv(csv_file, index=False)
        except Exception as e:
            print(f"[{route_name}] ERROR updating actual arrival in {csv_file}: {e}")


# ======================
# BUS ETA MONITORING
# ======================
def monitor_route(route_name):
    print(f"[{route_name}] Starting monitoring thread...")
    try:
        df_bus = get_bus_data(API_URL, API_KEY)
        df_bus = collect_bus_history(df_bus)
        buses = filter_bus(df_bus, route_name)
        mapped = map_index_df(buses, route_name)

        if mapped.empty:
            print(f"[{route_name}] No buses found.")
            return

        stops = [stop['index'] for stop in direction_map[route_name]['stop_list']]
        coords = load_route_coords(direction_map[route_name]["geojson_path"])
        max_index = max(o for o, lon, lat in coords)

        t_now = datetime.now()
        active_buses = {}

        # Initialize all active buses
        for _, bus in mapped.iterrows():
            licence = bus["licence"]
            start_index = int(bus["bus_index"])
            active_buses[licence] = {
                "start_index": start_index,
                "last_eta_time": t_now,
                "predictions_km": [],
                "predictions_stops": []
            }

            # KM interval predictions
            km_targets = list(range(((start_index // ORDERS_PER_KM)+1)*ORDERS_PER_KM, max_index+1, ORDERS_PER_KM))
            if max_index not in km_targets:
                km_targets.append(max_index)
            for idx in km_targets:
                eta = calc_eta(start_index, idx, route_name)
                if eta is None or eta < 0:
                    continue
                active_buses[licence]["predictions_km"].append({
                    "target_index": idx,
                    "eta_0min": eta,
                    "predicted_arrival_time_0min": t_now,
                    "start_index": start_index
                })
            write_initial_predictions(licence, route_name, active_buses[licence]["predictions_km"], KM_CSV, "target_index")

            # Stop predictions with metadata
            for stop in direction_map[route_name]['stop_list']:
                stop_idx = stop['index']
                eta_stop = calc_eta(start_index, stop_idx, route_name)
                if eta_stop is None or eta_stop < 0:
                    continue
                active_buses[licence]["predictions_stops"].append({
                    "stop_index": stop_idx,
                    "eta_0min": eta_stop,
                    "predicted_arrival_time_0min": t_now,
                    "start_index": start_index,
                    "stop_no": stop['no'],
                    "stop_name_eng": stop['stop_name_eng'],
                    "stop_name_th": stop['stop_name_th']
                })
            write_initial_stop_predictions(licence, route_name, active_buses[licence]["predictions_stops"], STOP_CSV)

        # ======================
        # Monitoring Loop
        # ======================
        while active_buses and not shutdown_event.is_set():
            if shutdown_event.wait(CHECK_INTERVAL_SEC):
                break

            df_bus = get_bus_data(API_URL, API_KEY)
            df_bus = collect_bus_history(df_bus)

            for licence, bus_data in list(active_buses.items()):
                bus_row = df_bus[df_bus["licence"] == licence]
                if bus_row.empty:
                    active_buses.pop(licence)
                    continue

                new_index = int(map_index_df(bus_row, route_name).iloc[0]["bus_index"])
                current_index = bus_data["start_index"]
                now = datetime.now()

                # Update actual arrival for km intervals
                passed_km = [p for p in bus_data["predictions_km"] if current_index < p["target_index"] <= new_index]
                for p in passed_km:
                    diff = (now - p["predicted_arrival_time_0min"]).total_seconds() / 60
                    update_actual_arrival(licence, route_name, p["target_index"], now, diff, KM_CSV, "target_index")

                # Update actual arrival for stops
                passed_stops = [p for p in bus_data["predictions_stops"] if current_index < p["stop_index"] <= new_index]
                for p in passed_stops:
                    diff = (now - p["predicted_arrival_time_0min"]).total_seconds() / 60
                    update_actual_arrival(licence, route_name, p["stop_index"], now, diff, STOP_CSV, "stop_index")

                # Interval ETA recalculation
                elapsed_min = (now - bus_data["last_eta_time"]).total_seconds() / 60
                if elapsed_min >= ETA_INTERVAL_MIN:
                    for p in bus_data["predictions_km"]:
                        eta_new = calc_eta(new_index, p["target_index"], route_name)
                        if eta_new is not None:
                            update_prediction_interval(licence, route_name, p["target_index"], eta_new, KM_CSV, "target_index", elapsed_min)
                    for p in bus_data["predictions_stops"]:
                        eta_new = calc_eta(new_index, p["stop_index"], route_name)
                        if eta_new is not None:
                            update_prediction_interval(licence, route_name, p["stop_index"], eta_new, STOP_CSV, "stop_index", elapsed_min)

                    bus_data["last_eta_time"] = now

                bus_data["start_index"] = new_index

    except Exception as e:
        print(f"[{route_name}] CRITICAL ERROR: {e}")


# ======================
# MULTI-ROUTE SUPERVISOR
# ======================
def start_multi_route_monitor(routes):
    threads = []
    for route in routes:
        t = threading.Thread(target=monitor_route, args=(route,), daemon=True)
        t.start()
        threads.append(t)
        print(f"[SYSTEM] Started route thread: {route}")

    try:
        while any(t.is_alive() for t in threads):
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[SYSTEM] Shutdown requested.")
        shutdown_event.set()
        for t in threads:
            t.join()

    print("[SYSTEM] All threads stopped cleanly.")


# ======================
# MAIN ENTRY
# ======================
if __name__ == "__main__":
    ROUTES = list(direction_map.keys())  # Uni-directional routes
    start_multi_route_monitor(ROUTES)
