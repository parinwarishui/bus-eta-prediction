'''
This file is for functions to load other files.

1. load_route_coords(file) 
-> list of tuples (index, lon, lat)

2. get_bus_data(api_url, api_key) 
-> bus_df ['licence', 'lon', 'lat', 'spd', 'azm', 'route_direction', 'timestamp']

3. collect_bus_history(bus_df) 
-> bus_df ['licence', 'lon', 'lat', 'spd', 'azm', 'route_direction', 'timestamp'] updated with history, prevent case of API failures

'''

'''==== IMPORT ===='''

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

'''==== CONSTANTS ===='''

load_dotenv()
API_KEY = os.getenv('API_KEY')
API_URL = "https://smartbus-pk-api.phuket.cloud/api/bus-news-2/"
BASE_DIR = os.path.dirname(__file__)
HISTORY_LOG = "bus_history.csv"

'''==== FUNCTIONS ===='''

'''==== LOAD ROUTE COORDINATES FROM GEOJSON FILE ===='''
def load_route_coords(route_geojson):
    with open(route_geojson, "r") as f:
        route_geojson_loaded = json.load(f)
    return [
        (feat["properties"]["order"],
         feat["geometry"]["coordinates"][0],
         feat["geometry"]["coordinates"][1])
        for feat in route_geojson_loaded["features"]
    ]

'''==== GET BUS DATA FROM API: return bus_df ===='''
def get_bus_data(api_url, api_key):

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json; charset=UTF-8"
    }

    # call API for response
    try:
        response = requests.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"\nError fetching bus data: {e}")
        return pd.DataFrame()
    except ValueError:
        print("\nResponse is not valid JSON.")
        return pd.DataFrame()
    
    # add data of each bus to list
    bus_list = []
    for bus in data:
        bus_data = bus.get("data", {})
        licence = bus.get("licence")
        pos = bus_data.get("pos")
        buffer = bus.get("buffer")
        azm = bus_data.get("azm")

        route = bus_data.get("determineBusDirection")
        if route:
            route = route[0]
        else:
            route = None

        spd = bus_data.get("spd", 0)

        # get lon, lat values from pos
        lon, lat = float(pos[0]), float(pos[1])
        # if no lon or lat then skip
        if lon is None or lat is None:
            continue
        
        # add dict of datas to bus_list
        bus_list.append({
            'licence': str(licence),
            'lon': lon,
            'lat': lat,
            'spd': spd,
            'buffer': buffer,
            'azm': azm,
            'route': route,
            'timestamp': datetime.now(),
        })

    # convert to DataFrame type
    bus_df = pd.DataFrame(bus_list)
    print("Successfully fetched buses from API")

    return bus_df

'''==== UPDATE HISTORICAL BUS DATA FOR API ERROR PREVENTION ===='''
def collect_bus_history(bus_df):
    now = datetime.now()

    # Load existing history csv file or create new
    if os.path.exists(HISTORY_LOG):
        try:
            bus_history_df = pd.read_csv(HISTORY_LOG, parse_dates=['timestamp'])
        except Exception:
            print("Corrupted bus history file, creating new history.")
            bus_history_df = pd.DataFrame(columns=['licence', 'lon', 'lat', 'spd', 'buffer', 'azm', 'route', 'timestamp'])
    else:
        bus_history_df = pd.DataFrame(columns=['licence', 'lon', 'lat', 'spd', 'buffer', 'azm', 'route', 'timestamp'])

    # convert to datetime type
    if not bus_history_df.empty and 'timestamp' in bus_history_df.columns:
        bus_history_df['timestamp'] = pd.to_datetime(bus_history_df['timestamp'])

    # iterate rows in bus_df
    for idx, row in bus_df.iterrows():
        licence = row['licence']
        buffer = row.get('buffer', None)
        route = row.get('route', None)

        # check if license exists in history
        hist_row = bus_history_df[bus_history_df['licence'] == licence]

        # CASE 1: buffer is None, recover from history 
        if buffer == None or buffer == '-':
            if not hist_row.empty:
                hist_time = hist_row.iloc[0]['timestamp']
                minutes_old = (now - hist_time).total_seconds() / 60.0

                # only recover if history < 5 mins old
                if minutes_old <= 5:
                    # Replace buffer & route from history, but DO NOT update timestamp
                    bus_df.loc[idx, 'buffer'] = hist_row.iloc[0]['buffer']
                    bus_df.loc[idx, 'route'] = hist_row.iloc[0]['route']
                    bus_df.loc[idx, 'azm'] = hist_row.iloc[0]['azm']
                    # do nothing to history timestamp
                else:
                    # History too old → treat as unknown, do not recover
                    pass
        
        # CASE 2: buffer is known from current data -> update history to latest
        else:
            new_hist = {
                'licence': licence,
                'lon': row['lon'],
                'lat': row['lat'],
                'spd': row.get('spd', 0),
                'buffer': buffer,
                'azm': row['azm'],
                'route': route,
                'timestamp': now
            }

            if not hist_row.empty:
                hist_i = hist_row.index[0]
                for k, v in new_hist.items():
                    bus_history_df.at[hist_i, k] = v
            else:
                # Insert new row
                bus_history_df = pd.concat([bus_history_df, pd.DataFrame([new_hist])], ignore_index=True)
      
    bus_history_df.to_csv(HISTORY_LOG, index=False)

    return bus_df



