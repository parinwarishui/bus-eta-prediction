'''
FILES:
1) load_files.py : helper functions to load route coordinates, fetch bus data, and store in history
2) tweak_bus_data.py : filter buses to selected route, map each bus to index of the chosen route
3) eta_calculation.py : calculate ETA from known bus index, stop index, and select route + compile list of upcoming buses

'''

import os
from dotenv import load_dotenv
from load_files import get_bus_data, collect_bus_history
from tweak_bus_data import filter_bus, map_index_df
from eta_calculation import get_upcoming_buses
from pprint import pprint

'''==== CONSTANTS ===='''

load_dotenv()
API_KEY = os.getenv('API_KEY')
STEP_ORDER = 5
DEFAULT_SPEED = 30
ORDERS_PER_KM = 1000 // STEP_ORDER 
API_URL = "https://smartbus-pk-api.phuket.cloud/api/bus-news-2/"
ETA_COLS = ["licence", "stop_name", "stop_index", "bus_index", "eta_min", "prediction_time", "predicted_arrival_time"]
BASE_DIR = os.path.dirname(__file__)
ETA_LOG = "eta_log.csv"
ETA_ASSESSED = "eta_assessed.csv"
HISTORY_LOG = "bus_history.csv"
BUFFER_STOPS = 15   # safety buffer after passing stop
CHECK_INTERVAL = 30 # seconds_COLS = ["licence", "stop_name", "stop_index", "bus_index", "eta_min", "prediction_time", "predicted_arrival_time"]

'''=== RUN ==='''

def main(api_url, api_key, stop_name, route):
    bus_df = get_bus_data(api_url, api_key)
    bus_df = collect_bus_history(bus_df)

    filtered_df = filter_bus(bus_df, route)
    mapped_df = map_index_df(filtered_df, route)
    print(filtered_df)
    print(mapped_df)
    combined_df = get_upcoming_buses(mapped_df, stop_name, route)

    # Convert DataFrame to JSON string
    combined_json_str = combined_df.to_json(orient="records")  # list of dicts

    #return combined_df
    return combined_json_str

print(main(API_URL, API_KEY, "Sai Yuan", "Airport -> Rawai"))