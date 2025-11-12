import time
import json
import os
from dotenv import load_dotenv

from load_files import get_bus_data, collect_bus_history
from tweak_bus_data import filter_bus, map_index_df
from eta_calculation import get_upcoming_buses
from stop_access import line_options, direction_map, bus_stop_list
from datetime import datetime

load_dotenv()
API_KEY = os.getenv('API_KEY')
API_URL = "https://smartbus-pk-api.phuket.cloud/api/bus-news-2/"
OUTPUT_FILENAME = "all_etas.json"

def calculate_all_etas():

    all_routes_data = {}

    # === GET BUS DATA ===
    print("worker.py: Fetching live bus data...")
    try:
        bus_df = get_bus_data(API_URL, API_KEY)
        bus_df = collect_bus_history(bus_df)
    except Exception as e:
        print(f"[ERROR] worker.py: fetching bus data: {e}")
        return
    
    # === PROCESS BUS DATA TO EACH ROUTE: FILTER FOR EACH ROUTE, MAP BUS TO INDEX ===
    print(f"worker.py: Processing {len(line_options)} routes...")
    for route_name in line_options:
        # Get stop list for this route
        stop_list = direction_map[route_name]["stop_list"]
        stop_names = [stop['stop_name_eng'] for stop in stop_list]
        
        # Filter and map buses for this specific route
        filtered_df = filter_bus(bus_df, route_name)
        mapped_df = map_index_df(filtered_df, route_name)
        
        all_stop_etas = {}
        
        # GET ETA FOR EACH BUS STOP IN ROUTE
        for stop_name in stop_names:
            upcoming_buses_df = get_upcoming_buses(mapped_df, stop_name, route_name)
            
            if not upcoming_buses_df.empty:
                # Get the first upcoming bus aka next bus
                next_bus = upcoming_buses_df.iloc[0].to_dict()
                
                # assign the bus (value) to the stop name (key)
                all_stop_etas[stop_name] = next_bus
            else:
                # if the bus stop has no upcoming buses (in both active bus and scheduled buses)
                all_stop_etas[stop_name] = None

        # store each route's data to the dict containing every route
        all_routes_data[route_name] = {
            "route": route_name,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "stops": all_stop_etas 
        }

    # === SAVE DATA TO JSON FILE ===
    try:
        with open(OUTPUT_FILENAME, "w") as f:
            json.dump(all_routes_data, f, indent=2)
        print(f"worker.py: Successfully updated {OUTPUT_FILENAME}")
    except Exception as e:
        print(f"worker.py: ERROR writing to {OUTPUT_FILENAME}: {e}")


# === RUN EVERY 60 SECONDS IN N8N ===
if __name__ == "__main__":
    print(f"--- Worker single run START ({datetime.now()}) ---")
    try:
        calculate_all_etas()
    except Exception as e:
        print(f"worker.py: error in worker run: {e}")
    
    print(f"--- Worker single run END ({datetime.now()}) ---")