'''
This file is for functions to edit bus data, making it ready to use.
1. filter_buses_for_route
2. map_index
'''

import os
import pandas as pd
import numpy as np
import json
import requests
from math import cos, radians
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
from pprint import pprint
import time
from stop_access import bus_stop_list, line_options, direction_map
from load_files import load_route_coords, get_bus_data, collect_bus_history

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

INLET_CONFIG = {
    "Patong -> Bus 1 -> Bus 2": {
        "Surin Road": {
            "index_ranges":{
                "south": (3397, 3577),
                "north": (3883, 4063)
            },
            "azm_range": (75, 225)
        },
        "Phangnga Road": {
            "index_ranges": {
                "east": (3795, 3883),
                "west": (3577, 3666)
            },
            "azm_range": (5, 185)
        }
    },
    "Bus 2 -> Bus 1 -> Patong": {
        "Surin Road": {
            "index_ranges":{
                "south": (1223, 1412),
                "north": (1717, 1895)
            },
            "azm_range": (75, 225)
        },
        "Phangnga Road": {
            "index_ranges": {
                "west": (1412, 1500),
                "east": (1630, 1717)
            },
            "azm_range": (5, 185)
        }
    },
    "Dragon Line": {
        "dibuk_road": {
            "index_ranges":{
                "west": (917, 1011),
                "east": (1, 95)
            },
            "azm_range": (0, 180)
        },
        "phangnga_road": {
            "index_ranges": {
                "east": (264, 293),
                "west": (1412, 1500)
            },
            "azm_range": (5, 185)
        }
    }
}

'''=== FUNCTIONS ==='''

'''=== FILTER ONLY BUSES IN SELECT ROUTE ==='''
def filter_bus(bus_df, route):
    if bus_df.empty:
        print("Warning: bus_df is empty")
        return pd.DataFrame()
    
    buffer = direction_map[route]['buffer']
    line = direction_map[route]['line']
    print(f"Filtering for buffer: {buffer}")
    print(f"Available route_directions: {bus_df['route'].unique()}")

    filtered_df = bus_df[bus_df['route'].str.contains(line, na=False)].copy()

    if filtered_df.empty:
        print(f"Warning: No buses found for route {line}")
        return pd.DataFrame()
    
    print(f"Found {len(filtered_df)} buses for route")

    return filtered_df

'''=== MAP A BUS TO AN INDEX ON A ROUTE ==='''
def map_index(bus_lon, bus_lat, route_coords):
    #route_for_mapping = load_route_coords(direction_map[route]['geojson_path'])

    # check any errors
    if not route_coords or bus_lon is None or bus_lat is None:
        return -1
    
    min_dist = float("inf")
    nearest_index = -1
    cos_lat = cos(radians(bus_lat))

    for order, lon, lat in route_coords:
        if lon is None or lat is None:
            continue
        dx = (lon - bus_lon) * 111320 * cos_lat
        dy = (lat - bus_lat) * 110540
        d2 = dx*dx + dy*dy
        if d2 < min_dist:
            min_dist = d2
            nearest_index = order

    return nearest_index


def map_index_df(filtered_df, route):
    route_coords = load_route_coords(direction_map[route]['geojson_path'])
    print(f"route is {route}")

    # fetch inlet_config for the route
    inlet_config = INLET_CONFIG.get(route, None)

    if 'bus_index' not in filtered_df.columns:
        filtered_df['bus_index'] = np.nan

    for i, row in filtered_df.iterrows():
        
        # get data for each elements
        lon, lat = row['lon'], row['lat']
        azm = row.get('azm', None)
        licence = row.get('licence', 'Unknown')

        # 1) first_index : map normally
        first_index = map_index(lon, lat, route_coords)
        filtered_df.loc[i, 'bus_index'] = first_index

        # 2) if route has no special condition, continue to next bus
        if not inlet_config:
            continue

        # 3) if route has condition: check each road section
        for road_name, road_data in inlet_config.items():
            for direction, (idx_min, idx_max) in road_data["index_ranges"].items():
                if idx_min <= first_index <= idx_max:
                    # if bus is inside this road area, now check azimuth
                    if azm is None:
                        continue  # skip if azimuth missing
                    azm_min, azm_max = road_data["azm_range"]

                    # 4) determine which range to use
                    # if azimuth matches range -> use first item, else use second item
                    first_dir, first_range = list(road_data["index_ranges"].items())[0]
                    second_dir, second_range = list(road_data["index_ranges"].items())[1]

                    if azm_min <= azm <= azm_max:
                        chosen_range = first_range
                        chosen_dir = first_dir
                    else:
                        chosen_range = second_range
                        chosen_dir = second_dir

                    idx_min2, idx_max2 = chosen_range # get the index range for bus index mapping

                    # 5) trim the route to only the selected index range
                    inlet_coords = [
                        (order, lon_i, lat_i)
                        for order, lon_i, lat_i in route_coords
                        if idx_min2 <= order <= idx_max2
                    ]

                    second_index = map_index(lon, lat, inlet_coords)
                    filtered_df.loc[i, 'bus_index'] = second_index
                    filtered_df.loc[i, 'inlet_section'] = f"{road_name}_{chosen_dir}"

                    print(f"Bus {licence} remapped in {road_name} ({chosen_dir}) "
                          f"index {first_index} → {second_index}, azm={azm}")

                    # Done with this road
                    break

    return filtered_df


bus_df = get_bus_data(API_URL, API_KEY)
bus_df = collect_bus_history(bus_df)
filtered_df = filter_bus(bus_df, "Dragon Line")
mapped_df = map_index_df(filtered_df, "Dragon Line")
print(mapped_df)

print("mapped_df shape:", mapped_df.shape)
print("Columns:", mapped_df.columns.tolist())

    

    
