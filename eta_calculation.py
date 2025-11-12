'''
This file is for functions to edit bus data, making it ready to use.
1. calc_eta (bus_order, stop_order, route) -> get ETA for a bus
2. get_upcoming_buses -> combined_df
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
from tweak_bus_data import filter_bus, map_index
'''==== CONSTANTS ===='''

load_dotenv()

STEP_ORDER = 5
DEFAULT_SPEED = 20
ORDERS_PER_KM = 1000 // STEP_ORDER 
API_URL = "https://smartbus-pk-api.phuket.cloud/api/bus-news-2/"
ETA_COLS = ["licence", "stop_name", "stop_index", "bus_index", "eta_min", "prediction_time", "predicted_arrival_time"]
BASE_DIR = os.path.dirname(__file__)
ETA_LOG = "eta_log.csv"
ETA_ASSESSED = "eta_assessed.csv"
HISTORY_LOG = "bus_history.csv"
BUFFER_STOPS = 15   # safety buffer after passing stop
CHECK_INTERVAL = 30 # 


'''==== FUNCTIONS ===='''

def calc_eta(bus_order, stop_order, route):
    constant_speed = DEFAULT_SPEED

    # If Dragon Line -> skip all speed/schedule
    if route == "Dragon Line":
        # handle cyclic route for dragon line
        ORDERS_TOTAL = 1011

        if bus_order > stop_order:
            stop_order += ORDERS_TOTAL  # dist from bus to 0 + dist from 0 to stop

        # get ETA using constant speed
        distance_orders = stop_order - bus_order
        if distance_orders <= 0:
            return 0

        distance_km = (distance_orders * STEP_ORDER) / 1000.0
        travel_time_min = int((distance_km / constant_speed) * 60)
        return travel_time_min

    # if normal route
    start_km = int(bus_order / ORDERS_PER_KM)
    end_km = int(stop_order / ORDERS_PER_KM)
    if start_km > end_km:
        return 0

    # load avg_speeds
    avg_speeds_file = direction_map[route].get("speeds_path", None)
    avg_speeds_df = None

    if avg_speeds_file:
        try:
            if avg_speeds_file.endswith(".csv"):
                avg_speeds_df = pd.read_csv(avg_speeds_file)
            else:
                with open(avg_speeds_file, "r") as f:
                    avg_speeds_loaded = json.load(f)
                avg_speeds_df = pd.DataFrame(avg_speeds_loaded)
        except Exception:
            avg_speeds_df = None  # fallback if unreadable
    else:
        avg_speeds_df = None

    # if no avg speed -> use constant speed
    if avg_speeds_df is None or avg_speeds_df.empty:
        distance_orders = stop_order - bus_order
        if distance_orders <= 0:
            return 0
        distance_km = (distance_orders * STEP_ORDER) / 1000.0
        travel_time_min = int((distance_km / constant_speed) * 60)
        return travel_time_min

    # calculation for bus with speeds data
    segment_range = list(range(start_km, end_km + 1))
    required_segments_df = pd.DataFrame({'km_interval': segment_range})

    if 'km_interval' in avg_speeds_df.columns:
        avg_speeds_df['km_interval'] = avg_speeds_df['km_interval'].astype(str)
        required_segments_df['km_interval'] = required_segments_df['km_interval'].astype(str)

    if 'avg_speed' in avg_speeds_df.columns:
        merge_cols = ['km_interval', 'avg_speed']
    elif 'spd' in avg_speeds_df.columns:
        avg_speeds_df = avg_speeds_df.rename(columns={'spd': 'avg_speed'})
        merge_cols = ['km_interval', 'avg_speed']
    else:
        merge_cols = ['km_interval']

    required_segments_df = required_segments_df.merge(
        avg_speeds_df[merge_cols],
        on='km_interval',
        how='left'
    )

    required_segments_df['avg_speed'] = required_segments_df.get('avg_speed', pd.Series(dtype=float)).fillna(constant_speed)
    required_segments_df['segment_start_order'] = required_segments_df['km_interval'].astype(int) * ORDERS_PER_KM
    required_segments_df['segment_end_order'] = required_segments_df['segment_start_order'] + ORDERS_PER_KM

    required_segments_df['segment_start_order_clipped'] = np.clip(required_segments_df['segment_start_order'], bus_order, stop_order)
    required_segments_df['segment_end_order_clipped'] = np.clip(required_segments_df['segment_end_order'], bus_order, stop_order)
    required_segments_df['segment_distance_orders'] = required_segments_df['segment_end_order_clipped'] - required_segments_df['segment_start_order_clipped']

    required_segments_df = required_segments_df[required_segments_df['segment_distance_orders'] > 0]
    if required_segments_df.empty:
        return 0

    required_segments_df['segment_distance_km'] = (required_segments_df['segment_distance_orders'] * STEP_ORDER) / 1000.0
    required_segments_df['avg_speed'] = required_segments_df['avg_speed'].replace(0, constant_speed)
    required_segments_df['travel_time_hr'] = required_segments_df['segment_distance_km'] / required_segments_df['avg_speed']

    total_travel_time_min = int((required_segments_df['travel_time_hr'] * 60).sum())
    return total_travel_time_min

def get_upcoming_buses(mapped_df, stop_name, route):
    now = datetime.now()
    today = date.today()
    all_cols = ['licence', 'lon', 'lat', 'spd', 'bus_index', 'stop_name', 'stop_index', 'dist_steps', 'dist_km', 'eta_min', 'prediction_time', 'eta_time']


    # load file from path to df
    avg_speeds_path = direction_map[route]["speeds_path"]
    # read CSV
    try:
        avg_speeds_df = pd.read_csv(avg_speeds_path)
    except Exception as e:
        print(f"[ERROR] Could not read/find speeds file: {e}, ignore if Old Town Bus")
        avg_speeds_df = pd.DataFrame(columns=['km_interval', 'avg_speed'])

    # === active buses ===
    stop_index = None
    stop_list = direction_map[route]["stop_list"]
    for stop in stop_list:
        if stop['stop_name_eng'] == stop_name:
            stop_index = stop['index']
            break

    if stop_index is None:
        return pd.DataFrame(columns=all_cols)

    # dragon line (cyclic)
    if route == "Dragon Line":
        total_points = 1011
        mapped_df["eta_distance"] = (
            (stop_index - mapped_df["bus_index"]) % total_points
        )
        active_buses_df = mapped_df.copy()
    else:
        # Linear routes
        active_buses_df = mapped_df[mapped_df["bus_index"] < stop_index].copy()
        active_buses_df["eta_distance"] = stop_index - active_buses_df["bus_index"]

    active_buses_df = mapped_df[mapped_df['bus_index'] < stop_index].copy() if not mapped_df.empty else pd.DataFrame(columns=all_cols)
    
    if not active_buses_df.empty:
        active_buses_df['dist_steps'] = stop_index - active_buses_df['bus_index']
        active_buses_df['dist_km'] = active_buses_df['dist_steps'] * STEP_ORDER / 1000.0
        active_buses_df['spd'] = active_buses_df['spd'].replace(0, DEFAULT_SPEED)
        active_buses_df['eta_min'] = active_buses_df['bus_index'].apply(lambda x: calc_eta(x, stop_index, route))
        active_buses_df['prediction_time'] = now.isoformat()
        active_buses_df['eta_time'] = active_buses_df['eta_min'].apply(lambda x: (now + timedelta(minutes=x)).isoformat())

    # === scheduled buses ===

    if active_buses_df.empty:
        schedule_df = pd.DataFrame()
        schedule_path = direction_map[route].get("schedule_path", None)

        if schedule_path:
            try:
                if os.path.exists(schedule_path):
                    schedule_df = pd.read_csv(schedule_path)
            except Exception as e:
                print(f"[ERROR] Could not load schedule for route '{route}': {e}")
                schedule_df = pd.DataFrame()

        scheduled_df = pd.DataFrame(columns=all_cols)

        if not schedule_df.empty:
            departure_col = schedule_df.columns[0]
            departure_times = pd.to_datetime(schedule_df[departure_col], format='%H:%M', errors='coerce').dropna()
            departure_times = departure_times.apply(lambda dt: datetime.combine(today, dt.time()))
            upcoming_departures = departure_times[departure_times > now]

            scheduled_buses = []
            base_travel_time_min = calc_eta(0, stop_index, route)

            for depart_dt in upcoming_departures:
                minutes_until_departure = (depart_dt - now).total_seconds() / 60.0
                total_eta = int(round(minutes_until_departure + base_travel_time_min))
                scheduled_buses.append({
                    'licence': 'Scheduled',
                    'spd': avg_speeds_df['avg_speed'].mean() if not avg_speeds_df.empty else DEFAULT_SPEED,
                    'lon': None,
                    'lat': None,
                    'buffer': direction_map[route].get('buffer', 0),
                    'bus_index': 0,
                    'dist_steps': stop_index,
                    'dist_km': round((stop_index * STEP_ORDER) / 1000.0, 3),
                    'eta_min': total_eta,
                    'prediction_time': now.isoformat(),
                    'eta_time': (now + timedelta(minutes=total_eta)).isoformat()
                })

            if scheduled_buses:
                scheduled_df = pd.DataFrame(scheduled_buses)
    
    else:
        # no need for scheudled buses if there is an active bus

        scheduled_df = pd.DataFrame(columns=all_cols)

    # === combine active + scheduled buses ===
    concatenate_df = [df for df in [active_buses_df, scheduled_df] if not df.empty]
    if concatenate_df:
        combined_df = pd.concat(concatenate_df, ignore_index=True)
    else:
        combined_df = pd.DataFrame(columns=all_cols)
    
    if not combined_df.empty:
        combined_df = combined_df.sort_values(by='eta_min').reset_index(drop=True)

    if 'bus_index' not in combined_df.columns:
        combined_df['bus_index'] = combined_df.get('index', -1)
    else:
        combined_df['bus_index'] = combined_df['bus_index'].fillna(combined_df.get('index', -1))

    combined_df['stop_name'] = stop_name
    combined_df['stop_index'] = stop_index

    return combined_df[all_cols]
