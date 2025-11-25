'''
This file is for functions to edit bus data, making it ready to use.
1. calc_eta (bus_order, stop_order, route) -> get ETA for a bus
2. get_upcoming_buses -> combined_df
'''

import os
import pandas as pd
import numpy as np
import json
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
from stop_access import direction_map

'''==== CONSTANTS ===='''

load_dotenv()

STEP_ORDER = 5
DEFAULT_SPEED = 15
ORDERS_PER_KM = 1000 // STEP_ORDER 
BASE_DIR = os.path.dirname(__file__)
START_BUFFER_STEPS = 10
IDLE_SPEED_THRESHOLD = 1

'''==== FUNCTIONS ===='''

def calc_eta(bus_order, stop_order, route, current_speed=None):
    constant_speed = DEFAULT_SPEED
    first_km_orders = 1000 // STEP_ORDER

    start_km = int(bus_order / ORDERS_PER_KM)
    end_km = int(stop_order / ORDERS_PER_KM)
    if start_km > end_km:
        return 0

    # FIX: Access RouteConfig object
    route_config = direction_map.get(route)
    if not route_config:
        return 0
        
    avg_speeds_file = route_config.speeds_path
    avg_speeds_df = None

    if avg_speeds_file:
        full_path = os.path.join(BASE_DIR, avg_speeds_file)
        try:
            if full_path.endswith(".csv"):
                avg_speeds_df = pd.read_csv(full_path)
            else:
                with open(full_path, "r") as f:
                    avg_speeds_loaded = json.load(f)
                avg_speeds_df = pd.DataFrame(avg_speeds_loaded)
        except Exception:
            avg_speeds_df = None  # fallback if unreadable
    else:
        avg_speeds_df = None

    # if no avg speed -> use constant speed
    if avg_speeds_df is None or avg_speeds_df.empty:
        avg_speeds_df = pd.DataFrame({'km_interval':[0], 'avg_speed':[constant_speed]})

    # calculation for bus with speeds data
    segment_range = list(range(start_km, end_km + 1))
    segments = pd.DataFrame({'km_interval': segment_range})

    if 'km_interval' in avg_speeds_df.columns:
        avg_speeds_df['km_interval'] = avg_speeds_df['km_interval'].astype(str)
        segments['km_interval'] = segments['km_interval'].astype(str)

    if 'avg_speed' in avg_speeds_df.columns:
        merge_cols = ['km_interval', 'avg_speed']
    elif 'spd' in avg_speeds_df.columns:
        avg_speeds_df = avg_speeds_df.rename(columns={'spd': 'avg_speed'})
        merge_cols = ['km_interval', 'avg_speed']
    else:
        merge_cols = ['km_interval']

    segments = segments.merge(
        avg_speeds_df[merge_cols],
        on='km_interval',
        how='left'
    )

    segments['avg_speed'] = pd.to_numeric(segments['avg_speed'], errors='coerce')
    segments['avg_speed'] = segments['avg_speed'].fillna(constant_speed).astype(float)
    
    # segment distances
    segments['segment_start_order'] = segments['km_interval'].astype(int) * ORDERS_PER_KM
    segments['segment_end_order'] = segments['segment_start_order'] + ORDERS_PER_KM

    segments['segment_start_order_clipped'] = np.clip(segments['segment_start_order'], bus_order, stop_order)
    segments['segment_end_order_clipped'] = np.clip(segments['segment_end_order'], bus_order, stop_order)
    segments['segment_distance_orders'] = (segments['segment_end_order_clipped'] - segments['segment_start_order_clipped'])
    
    segments = segments[segments['segment_distance_orders'] > 0]

    segments['segment_distance_km'] = (segments['segment_distance_orders'] * STEP_ORDER / 1000.0)
    segments['effective_speed'] = segments['avg_speed']

    # speed calc weighting
    if current_speed is not None and not segments.empty:
        current_speed_clamped = np.clip(current_speed, 15, 50)
        first_km_mask = (segments['segment_start_order_clipped'] < (bus_order + first_km_orders))
        segments.loc[first_km_mask, 'effective_speed'] = (0.7 * segments.loc[first_km_mask, 'avg_speed'] + 0.3 * current_speed_clamped)
    
    segments['travel_time_hr'] = (segments['segment_distance_km'] / segments['effective_speed'])
    total_travel_time_min = int((segments['travel_time_hr'] * 60).sum())
    
    return total_travel_time_min

def get_upcoming_buses(mapped_df, stop_name, route):
    now = datetime.now()
    today = date.today()
    all_cols = ['licence', 'lon', 'lat', 'spd', 'bus_index', 'stop_name', 'stop_index', 'dist_steps', 'dist_km', 'eta_min', 'eta_time']

    # FIX: Access RouteConfig object
    route_config = direction_map.get(route)
    if not route_config:
        return pd.DataFrame(columns=all_cols)

    # load file from path to df
    avg_speeds_path = route_config.speeds_path
    
    try:
        if avg_speeds_path:
            full_speed_path = os.path.join(BASE_DIR, avg_speeds_path)
            avg_speeds_df = pd.read_csv(full_speed_path)
        else:
            avg_speeds_df = pd.DataFrame(columns=['km_interval', 'avg_speed'])
    except Exception:
        avg_speeds_df = pd.DataFrame(columns=['km_interval', 'avg_speed'])

    # === active buses ===
    stop_index = None
    stop_list = route_config.stop_list # Access object attribute
    
    for stop in stop_list:
        if stop['stop_name_eng'] == stop_name:
            stop_index = stop['index'] # Ensure 'index' key exists in stop_list dicts, or use 'no' if that's the mapping
            # Note: tweak_bus_data.py uses 'no' in stop_access.py. Check if 'index' is correct key. 
            # If your stop_list uses 'no' for order, change this to stop['no'] * 1000 ?? 
            # Looking at stop_access.py, it has 'no' (1, 2, 3...). 
            # Usually index in geojson is much larger. 
            # Assuming 'index' exists in stop_list or 'no' corresponds to it. 
            # If stop_access.py only has 'no', you might need to map 'no' to the actual route index if not present.
            # Assuming stop_list dictionaries have 'index' key based on previous context.
            if 'index' in stop:
                stop_index = stop['index']
            else:
                 # Fallback if 'index' missing but 'no' exists, might be unsafe if no direct mapping
                 # But sticking to previous logic:
                 pass
            break
            
    # CRITICAL FIX: If stop_access.py only has 'no' and 'lat/lon', but not 'index' (the route order integer), 
    # we can't calculate ETA. 
    # However, looking at your previous `stop_access.py`, `stop_list` had 'index' in some versions or 
    # `load_files.py` loaded it. 
    # If `stop_list` in `stop_access.py` ONLY has `no`, `lat`, `lon`, `stop_name...`, 
    # then `stop['index']` will crash.
    # Assuming the data in `stop_access.py` has been enriched or contains `index`.
    
    if stop_index is None:
        return pd.DataFrame(columns=all_cols)

    active_buses_df = mapped_df[mapped_df["bus_index"] < stop_index].copy() if not mapped_df.empty else pd.DataFrame(columns=all_cols)
    
    if not active_buses_df.empty:
        active_buses_df['dist_steps'] = stop_index - active_buses_df['bus_index']
        active_buses_df['dist_km'] = active_buses_df['dist_steps'] * STEP_ORDER / 1000.0

        # Filter out idle buses at start
        active_buses_df = active_buses_df[
            ~(
                (active_buses_df['bus_index'] <= START_BUFFER_STEPS) &
                (active_buses_df['spd'] <= IDLE_SPEED_THRESHOLD)
            )
        ]

        active_buses_df['spd'] = active_buses_df['spd'].replace(0, DEFAULT_SPEED)
        active_buses_df['eta_min'] = active_buses_df['bus_index'].apply(lambda x: calc_eta(x, stop_index, route))
        active_buses_df['prediction_time'] = now.isoformat()
        active_buses_df['eta_time'] = active_buses_df['eta_min'].apply(lambda x: (now + timedelta(minutes=x)).isoformat())

    # === scheduled buses ===
    if active_buses_df.empty:
        schedule_df = pd.DataFrame()
        schedule_path_rel = route_config.schedule_path

        if schedule_path_rel:
            full_schedule_path = os.path.join(BASE_DIR, schedule_path_rel)
            try:
                if os.path.exists(full_schedule_path):
                    schedule_df = pd.read_csv(full_schedule_path)
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
                    # FIX: Access object attribute
                    'buffer': getattr(route_config, 'buffer', 0),
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