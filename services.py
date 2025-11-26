import time
import json
import os
import sys
import pandas as pd
import numpy as np
import threading
import traceback
from math import cos, radians
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

# Keep stop_access separate as it contains heavy config data
from stop_access import line_options, direction_map 

# === CONSOLE ENCODING FIX ===
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass 

# === CONSTANTS & CONFIGURATION ===
load_dotenv()
API_KEY = os.getenv('API_KEY')
API_URL = "https://smartbus-pk-api.phuket.cloud/api/bus-news-2/"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_SOURCE_FILE = os.path.join(BASE_DIR, "all_etas.json")
HISTORY_LOG = os.path.join(BASE_DIR, "bus_history.csv")
BUS_FLAGS_FILE = os.path.join(BASE_DIR, "bus_flags.json")

# Global flag to control the worker thread
running_event = threading.Event()

RUN_INTERVAL_SECONDS = 60
STEP_ORDER = 5
DEFAULT_SPEED = 15
ORDERS_PER_KM = 1000 // STEP_ORDER 
START_BUFFER_STEPS = 10
IDLE_SPEED_THRESHOLD = 1

# Configuration for specific road sections
INLET_CONFIG = {
    "Patong -> Bus 1 -> Bus 2": {
        "Surin Road": {
            "index_ranges": {"south": (3397, 3577), "north": (3883, 4063)},
            "azm_range": (75, 225)
        },
        "Phangnga Road": {
            "index_ranges": {"east": (3795, 3883), "west": (3577, 3666)},
            "azm_range": (5, 185)
        }
    },
    "Bus 2 -> Bus 1 -> Patong": {
        "Surin Road": {
            "index_ranges": {"south": (1223, 1412), "north": (1717, 1895)},
            "azm_range": (75, 225)
        },
        "Phangnga Road": {
            "index_ranges": {"west": (1412, 1500), "east": (1630, 1717)},
            "azm_range": (5, 185)
        }
    },
    "Dragon Line": {
        "dibuk_road": {
            "index_ranges": {"west": (917, 1011), "east": (1, 95)},
            "azm_range": (0, 180)
        },
        "phangnga_road": {
            "index_ranges": {"east": (264, 293), "west": (1412, 1500)},
            "azm_range": (5, 185)
        }
    }
}

# =========================================================
# SECTION 1: DATA LOADING & FLAG MANAGEMENT
# =========================================================

def load_data():
    """Helper to safely load the JSON data file."""
    if not os.path.exists(DATA_SOURCE_FILE):
        return None
    try:
        with open(DATA_SOURCE_FILE, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to load data file: {e}")
        return None

def load_flags():
    if not os.path.exists(BUS_FLAGS_FILE):
        return {}
    try:
        with open(BUS_FLAGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def set_route_status(route_name, status_message, is_delayed=False):
    """Updates the manual status for a specific route."""
    flags = load_flags()
    
    if status_message == "CLEAR":
        if route_name in flags:
            del flags[route_name]
    else:
        flags[route_name] = {
            "message": status_message,
            "is_delayed": is_delayed,
            "updated_at": datetime.now().isoformat()
        }
    
    with open(BUS_FLAGS_FILE, "w", encoding="utf-8") as f:
        json.dump(flags, f, indent=2)
    
    # Trigger immediate recalculation
    calculate_all_etas() 

# =========================================================
# SECTION 2: CORE LOGIC
# =========================================================

def load_route_coords(route_geojson):
    with open(route_geojson, "r") as f:
        route_geojson_loaded = json.load(f)
    return [
        (feat["properties"]["order"],
         feat["geometry"]["coordinates"][0],
         feat["geometry"]["coordinates"][1])
        for feat in route_geojson_loaded["features"]
    ]

def get_bus_data(api_url, api_key):
    import requests 
    headers = { "Authorization": f"Bearer {api_key}", "Accept": "application/json" }
    try:
        response = requests.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"\nError fetching bus data: {e}")
        return pd.DataFrame()
    
    bus_list = []
    for bus in data:
        bus_data = bus.get("data", {})
        pos = bus_data.get("pos")
        if pos is None or len(pos) < 2: continue
        
        bus_list.append({
            'licence': str(bus.get("licence")),
            'lon': float(pos[0]),
            'lat': float(pos[1]),
            'spd': float(bus_data.get("spd", 0)), # Force float here
            'buffer': bus.get("buffer"),
            'azm': bus_data.get("azm"),
            'route': bus_data.get("determineBusDirection", [None])[0],
            'timestamp': datetime.now(),
        })
    return pd.DataFrame(bus_list)

def collect_bus_history(bus_df):
    now = datetime.now()
    if os.path.exists(HISTORY_LOG):
        try:
            bus_history_df = pd.read_csv(HISTORY_LOG, parse_dates=['timestamp'])
        except:
            bus_history_df = pd.DataFrame(columns=['licence', 'lon', 'lat', 'spd', 'buffer', 'azm', 'route', 'timestamp'])
    else:
        bus_history_df = pd.DataFrame(columns=['licence', 'lon', 'lat', 'spd', 'buffer', 'azm', 'route', 'timestamp'])

    if not bus_history_df.empty:
        bus_history_df['timestamp'] = pd.to_datetime(bus_history_df['timestamp'])

    for idx, row in bus_df.iterrows():
        licence = row['licence']
        buffer = row.get('buffer')
        hist_row = bus_history_df[bus_history_df['licence'] == licence]

        if buffer == None or buffer == '-':
            if not hist_row.empty:
                hist_time = hist_row.iloc[0]['timestamp']
                if (now - hist_time).total_seconds() / 60.0 <= 5:
                    bus_df.loc[idx, 'buffer'] = hist_row.iloc[0]['buffer']
                    bus_df.loc[idx, 'route'] = hist_row.iloc[0]['route']
        else:
            new_hist = row.to_dict()
            if not hist_row.empty:
                hist_i = hist_row.index[0]
                for k, v in new_hist.items():
                    bus_history_df.at[hist_i, k] = v
            else:
                bus_history_df = pd.concat([bus_history_df, pd.DataFrame([new_hist])], ignore_index=True)
      
    bus_history_df.to_csv(HISTORY_LOG, index=False)
    return bus_df

def filter_bus(bus_df: pd.DataFrame, route: str) -> pd.DataFrame:
    if bus_df.empty: return pd.DataFrame()
    route_config = direction_map.get(route)
    if not route_config: return pd.DataFrame()
    # Filter by route string
    return bus_df[bus_df['route'].str.contains(route_config.line, na=False)].copy()

def map_index(bus_lon, bus_lat, route_coords):
    if not route_coords or bus_lon is None: return -1
    min_dist = float("inf")
    nearest_index = -1
    cos_lat = cos(radians(bus_lat))
    for order, lon, lat in route_coords:
        dx = (lon - bus_lon) * 111320 * cos_lat
        dy = (lat - bus_lat) * 110540
        d2 = dx*dx + dy*dy
        if d2 < min_dist:
            min_dist = d2
            nearest_index = order
    return nearest_index

def map_index_df(filtered_df: pd.DataFrame, route: str) -> pd.DataFrame:
    route_config = direction_map.get(route)
    if not route_config: return filtered_df
    geojson_full_path = os.path.join(BASE_DIR, route_config.geojson_path)
    route_coords = load_route_coords(geojson_full_path)
    
    if 'bus_index' not in filtered_df.columns: 
        filtered_df['bus_index'] = np.nan
    
    for i, row in filtered_df.iterrows():
        first_index = map_index(row['lon'], row['lat'], route_coords)
        filtered_df.loc[i, 'bus_index'] = first_index
        
    return filtered_df

def calc_eta(bus_order, stop_order, route, current_speed=None):
    """Full ETA calculation logic."""
    constant_speed = DEFAULT_SPEED
    first_km_orders = 1000 // STEP_ORDER

    # Ensure inputs are standard python types (not Series)
    if isinstance(current_speed, pd.Series):
        current_speed = float(current_speed.iloc[0])
    
    if isinstance(stop_order, dict):
        stop_order = stop_order.get('index', stop_order.get('no', 0))

    start_km = int(bus_order / ORDERS_PER_KM)
    end_km = int(stop_order / ORDERS_PER_KM)
    if start_km > end_km:
        return 0

    route_config = direction_map.get(route)
    if not route_config: return 0
        
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
            avg_speeds_df = None  

    if avg_speeds_df is None or avg_speeds_df.empty:
        avg_speeds_df = pd.DataFrame({'km_interval':[0], 'avg_speed':[constant_speed]})

    segment_range = list(range(start_km, end_km + 1))
    segments = pd.DataFrame({'km_interval': segment_range})

    if 'km_interval' in avg_speeds_df.columns:
        avg_speeds_df['km_interval'] = avg_speeds_df['km_interval'].astype(str)
        segments['km_interval'] = segments['km_interval'].astype(str)

    # Handle speed column naming
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
    
    segments['segment_start_order'] = segments['km_interval'].astype(int) * ORDERS_PER_KM
    segments['segment_end_order'] = segments['segment_start_order'] + ORDERS_PER_KM

    segments['segment_start_order_clipped'] = np.clip(segments['segment_start_order'], bus_order, stop_order)
    segments['segment_end_order_clipped'] = np.clip(segments['segment_end_order'], bus_order, stop_order)
    segments['segment_distance_orders'] = (segments['segment_end_order_clipped'] - segments['segment_start_order_clipped'])
    
    segments = segments[segments['segment_distance_orders'] > 0]

    segments['segment_distance_km'] = (segments['segment_distance_orders'] * STEP_ORDER / 1000.0)
    segments['effective_speed'] = segments['avg_speed']

    if current_speed is not None and not segments.empty:
        current_speed_clamped = np.clip(current_speed, 15, 50)
        first_km_mask = (segments['segment_start_order_clipped'] < (bus_order + first_km_orders))
        segments.loc[first_km_mask, 'effective_speed'] = (0.7 * segments.loc[first_km_mask, 'avg_speed'] + 0.3 * current_speed_clamped)
    
    segments['travel_time_hr'] = (segments['segment_distance_km'] / segments['effective_speed'])
    
    # Final scalar result
    total_travel_time_min = int((segments['travel_time_hr'] * 60).sum())
    
    return total_travel_time_min


def get_upcoming_buses(mapped_df, stop_name, route):
    now = datetime.now()
    today = date.today()
    all_cols = ['licence', 'eta_min', 'eta_time', 'status']

    route_config = direction_map.get(route)
    if not route_config: return pd.DataFrame(columns=all_cols)

    stop_index = None
    # Lookup stop index safely
    for s in route_config.stop_list.values():
        if s['stop_name_eng'] == stop_name:
            stop_index = s.get('index', s.get('no')) 
            break

    if stop_index is None: return pd.DataFrame(columns=all_cols)

    # === 1. ACTIVE BUSES ===
    active_buses_df = mapped_df[mapped_df["bus_index"] < stop_index].copy() if not mapped_df.empty else pd.DataFrame(columns=all_cols)

    # --- CRITICAL FIX: Remove Duplicate Columns to prevent 'Cannot set DataFrame' error ---
    active_buses_df = active_buses_df.loc[:, ~active_buses_df.columns.duplicated()]

    if not active_buses_df.empty:
        # Filter idle buses
        active_buses_df = active_buses_df[active_buses_df['spd'] > IDLE_SPEED_THRESHOLD]
        
        # Apply calculation row by row
        if not active_buses_df.empty:
            active_buses_df['eta_min'] = active_buses_df.apply(
                lambda row: calc_eta(
                    row['bus_index'], 
                    stop_index, 
                    route, 
                    float(row['spd']) # Force float
                ), axis=1
            )
            active_buses_df['eta_time'] = active_buses_df['eta_min'].apply(lambda x: (now + timedelta(minutes=x)).isoformat())
            active_buses_df['status'] = "Active"

    # === 2. SCHEDULED BUSES ===
    scheduled_df = pd.DataFrame(columns=all_cols)
    if active_buses_df.empty or active_buses_df is None:
        schedule_path_rel = route_config.schedule_path
        if schedule_path_rel:
            full_schedule_path = os.path.join(BASE_DIR, schedule_path_rel)
            try:
                if os.path.exists(full_schedule_path):
                    df_sched = pd.read_csv(full_schedule_path)
                    if not df_sched.empty:
                        departure_col = df_sched.columns[0]
                        departure_times = pd.to_datetime(df_sched[departure_col], format='%H:%M', errors='coerce').dropna()
                        departure_times = departure_times.apply(lambda dt: datetime.combine(today, dt.time()))
                        upcoming_departures = departure_times[departure_times > now]
                        scheduled_buses = []
                        base_travel_time_min = calc_eta(0, stop_index, route)
                        for depart_dt in upcoming_departures:
                            minutes_until_departure = (depart_dt - now).total_seconds() / 60.0
                            total_eta = int(round(minutes_until_departure + base_travel_time_min))
                            scheduled_buses.append({
                                'licence': 'Scheduled',
                                'eta_min': total_eta,
                                'eta_time': (now + timedelta(minutes=total_eta)).isoformat(),
                                'status': 'Scheduled'
                            })
                            break
                        if scheduled_buses:
                            scheduled_df = pd.DataFrame(scheduled_buses)
            except Exception as e:
                print(f"[ERROR] Loading schedule for {route}: {e}")

    # === 3. COMBINE ===
    concatenate_df = [df for df in [active_buses_df, scheduled_df] if not df.empty]
    if concatenate_df:
        combined_df = pd.concat(concatenate_df, ignore_index=True)
        combined_df = combined_df.sort_values(by='eta_min').reset_index(drop=True)
        return combined_df[all_cols]

    return pd.DataFrame(columns=all_cols)

# =========================================================
# SECTION 3: WORKER CONTROL LOGIC
# =========================================================

def calculate_all_etas():
    timestamp_str = datetime.now().strftime('%H:%M:%S')
    
    try:
        bus_df = get_bus_data(API_URL, API_KEY)
        try: bus_df = collect_bus_history(bus_df) 
        except: pass

        flags = load_flags()
        all_routes_data = {}

        for route_name in line_options:
            route_config = direction_map[route_name]
            manual_status = flags.get(route_name, None)
            
            # --- FILTER & CLEAN ---
            filtered_df = filter_bus(bus_df, route_name)
            # Ensure no dupes before mapping
            filtered_df = filtered_df.loc[:, ~filtered_df.columns.duplicated()]
            mapped_df = map_index_df(filtered_df, route_name)
            
            all_stop_etas = {}
            
            # Use ITEMS() to get ID/Index correctly
            for stop_id, stop_info in route_config.stop_list.items():
                stop_name = stop_info['stop_name_eng']
                
                # Base data structure (Static info)
                stop_result = {
                    "no": stop_info['no'],
                    "index": stop_info['index'],
                    "stop_name_eng": stop_info['stop_name_eng'],
                    "stop_name_th": stop_info['stop_name_th'],
                    "lat": stop_info['lat'],
                    "lon": stop_info['lon']
                }

                try:
                    upcoming_buses_df = get_upcoming_buses(mapped_df, stop_name, route_name)
                    
                    if not upcoming_buses_df.empty:
                        next_bus = upcoming_buses_df.iloc[0].to_dict()
                        if manual_status and manual_status.get("is_delayed"):
                            next_bus["status"] = f"DELAYED: {manual_status['message']}"
                        stop_result.update(next_bus)
                    else:
                        stop_result.update({
                            "eta_min": -1,
                            "message": "No more buses for today",
                            "licence": "-",
                            "status": "Ended"
                        })
                except Exception as e:
                    # Capture the calculation error for the frontend
                    stop_result.update({
                        "eta_min": -1, 
                        "status": "Error", 
                        "message": str(e)
                    })

                all_stop_etas[stop_name] = stop_result
            
            all_routes_data[route_name] = {
                "route": route_name,
                "updated_at": datetime.now().isoformat(),
                "manual_status": manual_status,
                "stops": all_stop_etas 
            }

        with open(DATA_SOURCE_FILE, "w", encoding="utf-8-sig") as f:
            json.dump(all_routes_data, f, indent=2, ensure_ascii=False)
        
    except Exception as e:
        print(f"WORKER ERROR: {e}")
        traceback.print_exc()

def worker_thread_func():
    calculate_all_etas()
    while running_event.is_set():
        for _ in range(RUN_INTERVAL_SECONDS):
            if not running_event.is_set(): break
            time.sleep(1)
        if running_event.is_set():
            calculate_all_etas()

def start_worker():
    if not running_event.is_set():
        running_event.set()
        t = threading.Thread(target=worker_thread_func, daemon=True)
        t.start()

def stop_worker():
    running_event.clear()