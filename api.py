from fastapi import FastAPI
from contextlib import asynccontextmanager
import asyncio
import json
import time
from datetime import datetime
from dotenv import load_dotenv
import os


# === Import your existing worker functions ===
from load_files import get_bus_data, collect_bus_history
from tweak_bus_data import filter_bus, map_index_df
from eta_calculation import get_upcoming_buses
from stop_access import line_options, direction_map

# === Setup ===
load_dotenv()
API_KEY = os.getenv("API_KEY")
API_URL = "https://smartbus-pk-api.phuket.cloud/api/bus-news-2/"
OUTPUT_FILENAME = "all_etas.json"

# === WORKER FUNCTION ===
def calculate_all_etas():
    """Fetch, process, and save ETA data for all routes"""
    all_routes_data = {}

    # === GET BUS DATA ===
    print("worker: Fetching live bus data...")
    try:
        bus_df = get_bus_data(API_URL, API_KEY)
        bus_df = collect_bus_history(bus_df)
    except Exception as e:
        print(f"[ERROR] fetching bus data: {e}")
        return

    # === PROCESS EACH ROUTE ===
    print(f"worker: Processing {len(line_options)} routes...")
    for route_name in line_options:
        stop_list = direction_map[route_name]["stop_list"]
        stop_names = [stop["stop_name_eng"] for stop in stop_list]

        filtered_df = filter_bus(bus_df, route_name)
        mapped_df = map_index_df(filtered_df, route_name)

        all_stop_etas = {}
        for stop_name in stop_names:
            upcoming_buses_df = get_upcoming_buses(mapped_df, stop_name, route_name)
            if not upcoming_buses_df.empty:
                next_bus = upcoming_buses_df.iloc[0].to_dict()
                all_stop_etas[stop_name] = next_bus
            else:
                all_stop_etas[stop_name] = None

        all_routes_data[route_name] = {
            "route": route_name,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "stops": all_stop_etas,
        }

    # === SAVE TO JSON ===
    try:
        with open(OUTPUT_FILENAME, "w") as f:
            json.dump(all_routes_data, f, indent=2)
        print(f"worker: Successfully updated {OUTPUT_FILENAME}")
    except Exception as e:
        print(f"worker: ERROR writing to {OUTPUT_FILENAME}: {e}")

# === BACKGROUND LOOP ===
async def update_worker_loop():
    """Run the worker continuously every 60 seconds"""
    while True:
        print(f"--- Worker run START ({datetime.now()}) ---")
        try:
            calculate_all_etas()
        except Exception as e:
            print(f"worker: error in run: {e}")
        print(f"--- Worker run END ({datetime.now()}) ---\n")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: start background worker
    task = asyncio.create_task(update_worker_loop())
    print("🚀 Background worker started.")
    yield  # <-- FastAPI runs your app here
    # Shutdown: cancel worker task
    task.cancel()
    print("🛑 Background worker stopped.")

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def get_all_etas():
    """Return all ETA data from the JSON file"""
    try:
        with open(OUTPUT_FILENAME, "r") as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        return {"error": "ETA data not yet generated. Please wait."}
    except Exception as e:
        return {"error": f"An error occurred: {e}"}