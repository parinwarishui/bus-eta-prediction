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
EVALUATION_CSV = "eta_evaluation_predictions.csv"

load_dotenv()
API_KEY = os.getenv("API_KEY")
API_URL = "https://smartbus-pk-api.phuket.cloud/api/bus-news-2/"

csv_lock = threading.Lock()
shutdown_event = threading.Event()


# =========================================================
#   INITIAL CSV WRITE (all predictions written first)
# =========================================================

def write_initial_predictions(route_name, licence, start_bus_index, predictions):
    rows = []
    for p in predictions:
        rows.append({
            "licence": licence,
            "route": route_name,
            "start_bus_index": start_bus_index,
            "target_km_interval": p["target_index"] // ORDERS_PER_KM,
            "target_index": p["target_index"],
            "predicted_eta_min": p["predicted_eta_min"],
            "prediction_timestamp": p["prediction_timestamp"],
            "predicted_arrival_time": p["predicted_arrival_time"],
            "actual_arrival_time": "",
            "time_difference_min": ""
        })

    df = pd.DataFrame(rows).sort_values("target_index")

    with csv_lock:
        df.to_csv(EVALUATION_CSV, mode="a", index=False, header=not os.path.exists(EVALUATION_CSV))


    print(f"[{route_name}] Initial predictions written ({len(df)} rows).")


# =========================================================
#   UPDATE A SINGLE ROW
# =========================================================

def update_prediction_row(route_name, licence, target_index, actual_time, diff_min):
    with csv_lock:
        try:
            df = pd.read_csv(EVALUATION_CSV)
        except Exception as e:
            print(f"[{route_name}] ERROR reading CSV: {e}")
            return

        mask = (df["licence"] == licence) & (df["target_index"] == target_index)
        if not mask.any():
            print(f"[{route_name}] WARNING: target_index {target_index} not found.")
            return

        df.loc[mask, "actual_arrival_time"] = actual_time
        df.loc[mask, "time_difference_min"] = diff_min

        try:
            df.to_csv(EVALUATION_CSV, index=False)
        except Exception as e:
            print(f"[{route_name}] ERROR writing CSV: {e}")

    print(f"[{route_name}] CSV updated for target {target_index}.")


# =========================================================
#                 MAIN EVALUATION LOOP
# =========================================================

def evaluate_bus_eta(route_name):

    print(f"\n--- [{route_name}] Starting ETA Evaluation Thread ---")

    try:
        # -----------------------------------------------------
        # 1. GET BUS SNAPSHOT
        # -----------------------------------------------------
        df = get_bus_data(API_URL, API_KEY)
        df = collect_bus_history(df)
        buses = filter_bus(df, route_name)
        mapped = map_index_df(buses, route_name)

        if mapped.empty:
            print(f"[{route_name}] No buses found.")
            return

        mapped = mapped.sort_values("bus_index")
        selected = mapped.iloc[0]

        licence = selected["licence"]
        start_index = int(selected["bus_index"])

        print(f"[{route_name}] Selected bus {licence}, start_index={start_index}")

        # -----------------------------------------------------
        # 2. Calculate target indices
        # -----------------------------------------------------
        coords = load_route_coords(direction_map[route_name]["geojson_path"])
        max_index = max(o for o, lon, lat in coords)

        start_km = (start_index // ORDERS_PER_KM) + 1
        first_target = start_km * ORDERS_PER_KM

        targets = list(range(first_target, max_index + 1, ORDERS_PER_KM))
        if max_index not in targets:
            targets.append(max_index)

        print(f"[{route_name}] Targets: {targets}")

        # -----------------------------------------------------
        # 3. Initial predictions
        # -----------------------------------------------------
        t_now = datetime.now()
        predictions = []

        for idx in targets:
            try:
                eta = calc_eta(start_index, idx, route_name)
            except Exception as e:
                print(f"[{route_name}] calc_eta error at {idx}: {e}")
                continue

            if eta is None or eta < 0:
                continue

            predictions.append({
                "target_index": idx,
                "predicted_eta_min": eta,
                "prediction_timestamp": t_now,
                "predicted_arrival_time": t_now + timedelta(minutes=eta)
            })

        if not predictions:
            print(f"[{route_name}] No valid predictions.")
            return

        write_initial_predictions(route_name, licence, start_index, predictions)

        # -----------------------------------------------------
        # 4. MONITORING LOOP (robust)
        # -----------------------------------------------------
        active_targets = {p["target_index"] for p in predictions}
        current_index = start_index

        print(f"[{route_name}] Monitoring started...")

        while active_targets and not shutdown_event.is_set():

            # Sleep with interrupt ability
            if shutdown_event.wait(CHECK_INTERVAL_SEC):
                break

            try:
                # refresh bus data
                df = get_bus_data(API_URL, API_KEY)
                df = collect_bus_history(df)

                bus = df[df["licence"] == licence]
                if bus.empty:
                    print(f"[{route_name}] BUS LOST {licence}. Retrying...")
                    continue

                mapped = map_index_df(bus, route_name)
                if mapped.empty:
                    print(f"[{route_name}] Mapping failed. Retrying...")
                    continue

                new_index = int(mapped.iloc[0]["bus_index"])

            except Exception as e:
                print(f"[{route_name}] LOOP ERROR: {e}")
                continue  # avoid thread death

            if new_index <= current_index:
                continue

            print(f"[{route_name}] Bus moved {current_index} → {new_index}")

            # Determine passed targets
            passed = sorted(i for i in active_targets if current_index < i <= new_index)
            now = datetime.now()

            for t_idx in passed:
                try:
                    pred = next((p for p in predictions if p["target_index"] == t_idx), None)
                    if pred is None:
                        print(f"[{route_name}] Missing prediction for {t_idx}")
                        continue

                    diff = (now - pred["predicted_arrival_time"]).total_seconds() / 60

                    update_prediction_row(route_name, licence, t_idx, now, diff)
                    print(f"[{route_name}] TARGET HIT {t_idx} (diff={diff:.2f})")

                except Exception as e:
                    print(f"[{route_name}] ERROR updating target {t_idx}: {e}")

                active_targets.discard(t_idx)

            current_index = new_index

        print(f"[{route_name}] Monitoring finished.")

    except Exception as e:
        print(f"[{route_name}] CRITICAL ERROR: {e}")
        # DO NOT stop entire system — isolate failure


# =========================================================
#              MULTI-ROUTE SUPERVISOR
# =========================================================

def start_multi_route_monitor(route_list):
    threads = []

    for route in route_list:
        t = threading.Thread(target=evaluate_bus_eta, args=(route,), daemon=True)
        t.start()
        threads.append(t)
        print(f"[SYSTEM] Started route thread: {route}")

    print("\n[SYSTEM] All route threads started. Press CTRL+C to stop.\n")

    try:
        while any(t.is_alive() for t in threads):
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[SYSTEM] Shutdown requested.")
        shutdown_event.set()
        for t in threads:
            t.join()

    print("[SYSTEM] All threads stopped cleanly.")


# =========================================================
#              MAIN ENTRY POINT
# =========================================================

if __name__ == "__main__":
    ROUTES = [
        "Airport -> Rawai",
        "Rawai -> Airport",
        "Patong -> Bus 1 -> Bus 2",
        "Bus 2 -> Bus 1 -> Patong",
        "Dragon Line",
    ]

    start_multi_route_monitor(ROUTES)
