import time
import json
import os
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime
import uvicorn
import threading
from fastapi import FastAPI, HTTPException

from load_files import get_bus_data, collect_bus_history
from tweak_bus_data import filter_bus, map_index_df
from eta_calculation import get_upcoming_buses
from stop_access import line_options, direction_map 

load_dotenv()
API_KEY = os.getenv('API_KEY')
API_URL = "https://smartbus-pk-api.phuket.cloud/api/bus-news-2/"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_SOURCE_FILE = os.path.join(BASE_DIR, "all_etas.json")
RUN_INTERVAL_SECONDS = 60

# === FASTAPI SETUP ===
app = FastAPI(title="Phuket Bus ETA API")

@app.get("/api/eta/all")
async def get_all_etas():
    try:
        if not os.path.exists(DATA_SOURCE_FILE):
             raise HTTPException(status_code=503, detail="Data file not ready yet.")

        with open(DATA_SOURCE_FILE, "r") as f:
            data = json.load(f)
        return data
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")

# === WORKER FUNCTION FOR ETA CALCULATION ===
def calculate_all_etas():
    """Fetches live data and saves the JSON file once."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] WORKER: Starting data fetch...")
    all_routes_data = {}
    
    try:
        bus_df = get_bus_data(API_URL, API_KEY)
        bus_df = collect_bus_history(bus_df) 
        
        for route_name in line_options:
            stop_list = direction_map[route_name]["stop_list"]
            stop_names = [stop['stop_name_eng'] for stop in stop_list]
            
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
                "updated_at": datetime.now().isoformat(),
                "stops": all_stop_etas 
            }

        with open(DATA_SOURCE_FILE, "w") as f:
            json.dump(all_routes_data, f, indent=2)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] WORKER: Data update successful.")
        
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] WORKER ERROR: {e}")

# === RUN THE WORKER FUNCTION AS LOOP ===
def worker_loop():
    print(f"WORKER THREAD STARTED. Running every {RUN_INTERVAL_SECONDS} seconds.")
    calculate_all_etas()
    while True:
        time.sleep(RUN_INTERVAL_SECONDS)
        calculate_all_etas()

# MAIN EXECUTION
if __name__ == "__main__":
    worker_thread = threading.Thread(target=worker_loop)
    worker_thread.daemon = True
    worker_thread.start()

    print("\n--- API SERVER STARTING ---")
    print(f"API will be available at: http://127.0.0.1:8000 (Use ngrok for public access)")
    uvicorn.run(app, host="127.0.0.1", port=8000)