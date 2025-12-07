import time
import json
import os
import sys
import pandas as pd
import numpy as np
import threading
import traceback
import requests 
from math import cos, radians
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

# Local Import
from stop_access import line_options, direction_map 

# === CONSOLE ENCODING FIX ===
try:
    sys.stdout.reconfigure(encoding='utf-8') # type: ignore
except AttributeError:
    pass 

'''=== CONSTANTS ==='''
load_dotenv()
API_KEY = os.getenv('API_KEY')
API_URL = "https://smartbus-pk-api.phuket.cloud/api/bus-news-2/"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_SOURCE_FILE = os.path.join(BASE_DIR, "all_etas.json")
HISTORY_LOG = os.path.join(BASE_DIR, "bus_history.csv")
BUS_FLAGS_FILE = os.path.join(BASE_DIR, "bus_flags.json")
ACCURACY_CSV = os.path.join(BASE_DIR, "eta_accuracy_archive.csv")

# Global flag to control the worker thread
running_event = threading.Event()

# Parameters
RUN_INTERVAL_SECONDS = 60
STEP_ORDER = 5
DEFAULT_SPEED = 15
ORDERS_PER_KM = 1000 // STEP_ORDER 
START_BUFFER_STEPS = 10
IDLE_SPEED_THRESHOLD = 1
OFFLINE_GRACE_PERIOD_MIN = 5 
AUTO_INACTIVE_THRESHOLD = 10 

# === ROUTE BIAS CONFIGURATION ===
# Multipliers to adjust ETA calculations based on route characteristics
ROUTE_BIAS = {
    "Airport -> Rawai": 0.8,       
    "Rawai -> Airport": 0.8,       
    "Dragon Line": 0.7,            
    "Patong -> Bus 1 -> Bus 2": 0.7, 
    "Bus 2 -> Bus 1 -> Patong": 0.7
}

# =========================================================
# DATA LOADING & FLAG MANAGEMENT
# =========================================================

'''LOAD ETA DATA'''
def load_data():
    if not os.path.exists(DATA_SOURCE_FILE): return {}
    try:
        with open(DATA_SOURCE_FILE, "r", encoding="utf-8-sig") as f: return json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to load data file: {e}")
        return {}

'''LOAD FLAGS FROM BUS_FLAGS'''
def load_flags():
    if not os.path.exists(BUS_FLAGS_FILE): return {}
    try:
        with open(BUS_FLAGS_FILE, "r", encoding="utf-8") as f: return json.load(f)
    except: return {}

'''ADD NEW FLAGS INTO BUS_FLAGS'''
def save_flags(flags):
    with open(BUS_FLAGS_FILE, "w", encoding="utf-8") as f: json.dump(flags, f, indent=2)

'''FULL MECHANISM TO SET FLAG OF BUS / STOP / ROUTE'''
def set_status_flag(scope, identifier, status, message=None, duration=None):
    flags = load_flags()
    identifier = str(identifier).strip() 
    key = f"{scope}:{identifier}"
    print(f"[ADMIN] Setting {key} to {status}")

    if status.lower() in ["active", "open", "clear"]:
        if key in flags: del flags[key]
    else:
        expires_at = None
        if duration and duration > 0:
            expires_at = (datetime.now() + timedelta(minutes=duration)).isoformat()
        flags[key] = {
            "scope": scope, "status": status, "message": message,
            "expires_at": expires_at, "updated_at": datetime.now().isoformat()
        }
    save_flags(flags)
    calculate_all_etas() 

'''CHECK EXPIRED FLAG AND REMOVE'''
def clean_expired_flags():
    flags = load_flags()
    now_iso = datetime.now().isoformat()
    keys_to_delete = [k for k, v in flags.items() if v.get("expires_at") and v["expires_at"] < now_iso]
    if keys_to_delete:
        for k in keys_to_delete: del flags[k]
        save_flags(flags)

# =========================================================
# SECTION 2: CORE LOGIC & MAPPING
# =========================================================

'''LOAD ROUTE COORDINATES FROM GEOJSON_ORDERED FILES'''
def load_route_coords(route_geojson):
    with open(route_geojson, "r") as f:
        route_geojson_loaded = json.load(f)
    return [
        (feat["properties"]["order"],
         feat["geometry"]["coordinates"][0],
         feat["geometry"]["coordinates"][1])
        for feat in route_geojson_loaded["features"]
    ]

'''GET BUS DATA FROM API'''
def get_bus_data(api_url, api_key):

    # get data from API as pandas DataFrame
    headers = { "Authorization": f"Bearer {api_key}", "Accept": "application/json" }
    try:
        response = requests.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"\nError fetching bus data: {e}")
        return pd.DataFrame()
    
    # create list of buses
    bus_list = []
    for bus in data:
        bus_data = bus.get("data", {})
        pos = bus_data.get("pos")
        if pos is None or len(pos) < 2: continue
        
        bus_list.append({
            'licence': str(bus.get("licence")),
            'lon': float(pos[0]),
            'lat': float(pos[1]),
            'spd': float(bus_data.get("spd", 0)), 
            'buffer': bus.get("buffer"),
            'azm': bus_data.get("azm"),
            'route': bus_data.get("determineBusDirection", [None])[0],
            'timestamp': datetime.now(),
        })
    return pd.DataFrame(bus_list)

'''CHECK HISTORY FOR MISSING BUSES (except > 5 mins)'''
def collect_bus_history(live_df):
    now = datetime.now()
    cutoff_time = now - timedelta(minutes=5)
    
    # open bus_history.csv
    if os.path.exists(HISTORY_LOG):
        try:
            hist_df = pd.read_csv(HISTORY_LOG)
            
            # clean any duplicate buses
            if not hist_df.empty and 'licence' in hist_df.columns:
                hist_df = hist_df.drop_duplicates(subset=['licence'], keep='last')

            # format date to datetime type
            if 'timestamp' in hist_df.columns:
                hist_df['timestamp'] = pd.to_datetime(hist_df['timestamp'])
            if 'last_move_time' in hist_df.columns:
                hist_df['last_move_time'] = pd.to_datetime(hist_df['last_move_time'])
            
            # take out any buses with time > cutoff limit
            if not hist_df.empty and 'timestamp' in hist_df.columns:
                hist_df = hist_df[hist_df['timestamp'] > cutoff_time]
                
        except Exception as e:
            print(f"History Load Error: {e}")
            hist_df = pd.DataFrame()
    else:
        hist_df = pd.DataFrame()

    cols = ['licence', 'lon', 'lat', 'spd', 'buffer', 'azm', 'route', 'timestamp', 'last_move_time']
    for c in cols:
        if c not in hist_df.columns: hist_df[c] = pd.NA

    # create map from cleaned bus history
    history_map = hist_df.set_index('licence').to_dict('index') if not hist_df.empty else {}
    
    if live_df.empty:
        # save new bus history
        hist_df.to_csv(HISTORY_LOG, index=False)
        return hist_df

    updated_records = []
    processed_licences = set()

    # process live data and add to updated records
    for _, row in live_df.iterrows():
        licence = str(row['licence'])
        processed_licences.add(licence)
        spd = float(row['spd'])
        
        last_move = now
        if licence in history_map:
            prev_last_move = history_map[licence].get('last_move_time')
            if pd.notna(prev_last_move):
                if spd > IDLE_SPEED_THRESHOLD:
                    last_move = now
                else:
                    last_move = prev_last_move 
        
        record = row.to_dict()
        record['timestamp'] = now 
        record['last_move_time'] = last_move
        updated_records.append(record)

    # process history data later
    for lic, data in history_map.items():
        if lic not in processed_licences:
            data['licence'] = lic 
            updated_records.append(data)

    full_df = pd.DataFrame(updated_records)
    
    # save completed full_df 
    full_df.to_csv(HISTORY_LOG, index=False)
    
    return full_df

'''FILTER BUS BY SELECTED ROUTE'''
def filter_bus(bus_df: pd.DataFrame, route: str) -> pd.DataFrame:
    if bus_df.empty: return pd.DataFrame()
    route_config = direction_map.get(route)
    if not route_config: return pd.DataFrame()
    if 'route' not in bus_df.columns: return pd.DataFrame()
    # Handle NaN in route column
    return bus_df[bus_df['route'].fillna('').str.contains(route_config.line, na=False)].copy()

'''MAP BUS TO INDEX ON THE 5M ROUTE COORDINATES'''
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

'''SPECIAL MAPPING FOR BUSES IN OVERLAP ROUTES'''
def map_index_constrained(bus_lon, bus_lat, route_coords, min_idx, max_idx):
    best_dist = float("inf")
    best_idx = -1
    cos_lat = cos(radians(bus_lat))
    for order, r_lon, r_lat in route_coords:
        if min_idx <= order <= max_idx:
            dx = (r_lon - bus_lon) * 111320 * cos_lat
            dy = (r_lat - bus_lat) * 110540
            d2 = dx*dx + dy*dy
            if d2 < best_dist:
                best_dist = d2
                best_idx = order
    return best_idx

'''CHECK BUS AZM RANGE'''
def is_in_azm_range(azm, rng):
    min_a, max_a = rng
    if min_a <= max_a:
        return min_a <= azm <= max_a
    else: # Wrap around
        return azm >= min_a or azm <= max_a

'''MAP WHOLE DATAFRAME OF BUSES TO INDEX'''
def map_index_df(filtered_df: pd.DataFrame, route: str) -> pd.DataFrame:
    route_config = direction_map.get(route)
    if not route_config: return filtered_df
    
    geojson_full_path = os.path.join(BASE_DIR, route_config.geojson_path)
    route_coords = load_route_coords(geojson_full_path)
    
    config = route_config.overlap

    if 'bus_index' not in filtered_df.columns: 
        filtered_df['bus_index'] = np.nan
        
    for i, row in filtered_df.iterrows():
        idx = map_index(row['lon'], row['lat'], route_coords)
        if config and idx != -1:
            for road_name, constraints in config.items():
                in_danger_zone = False
                
                # check if current bus index is in danger range (overlapping line)
                for start, end in constraints['index_ranges'].values():
                    if start <= idx <= end:
                        in_danger_zone = True
                        break
                
                if in_danger_zone:
                    bus_azm = row.get('azm')
                    if bus_azm is not None:
                        # ranges will be a list of [start, end] pairs
                        ranges = list(constraints['index_ranges'].values())
                        
                        # Determine which segment corresponds to current heading
                        if is_in_azm_range(float(bus_azm), constraints['azm_range']):
                            target_range = ranges[0]
                        else:
                            target_range = ranges[1] if len(ranges) > 1 else ranges[0]
                        
                        t_min, t_max = target_range
                        
                        # If mapped index is WRONG (not in the target range), force remap
                        if not (t_min <= idx <= t_max):
                            new_idx = map_index_constrained(row['lon'], row['lat'], route_coords, t_min, t_max)
                            if new_idx != -1:
                                idx = new_idx
                    break
        filtered_df.at[i, 'bus_index'] = idx #type: ignore
    return filtered_df

# =========================================================
# ETA CALCULATION
# =========================================================

'''MAIN FUNCTION FOR CALCULATE ETA'''
def calc_eta(bus_order, stop_order, route, current_speed=None):
    # set up data
    constant_speed = DEFAULT_SPEED
    if isinstance(current_speed, pd.Series): current_speed = float(current_speed.iloc[0])
    if isinstance(stop_order, dict): stop_order = stop_order.get('index', stop_order.get('no', 0))
    
    start_km = int(bus_order / ORDERS_PER_KM)
    end_km = int(stop_order / ORDERS_PER_KM)

    # if start km > end km -> invalid
    if start_km > end_km: return 0
    route_config = direction_map.get(route)
    if not route_config: return 0
    
    # load history speed data
    avg_speeds_file = route_config.speeds_path
    avg_speeds_df = None
    if avg_speeds_file:
        full_path = os.path.join(BASE_DIR, avg_speeds_file)
        try:
            if full_path.endswith(".csv"): avg_speeds_df = pd.read_csv(full_path)
            else:
                with open(full_path, "r") as f: avg_speeds_loaded = json.load(f)
                avg_speeds_df = pd.DataFrame(avg_speeds_loaded)
        except Exception: avg_speeds_df = None  
    if avg_speeds_df is None or avg_speeds_df.empty: 
        avg_speeds_df = pd.DataFrame({'km_interval':[0], 'avg_speed':[constant_speed]})
    
    # make route into segments
    segment_range = list(range(start_km, end_km + 1))
    segments = pd.DataFrame({'km_interval': segment_range})
    
    
    if 'km_interval' in avg_speeds_df.columns:
        avg_speeds_df['km_interval'] = avg_speeds_df['km_interval'].astype(str)
        segments['km_interval'] = segments['km_interval'].astype(str)
    
    speed_col = 'avg_speed' if 'avg_speed' in avg_speeds_df.columns else 'spd'
    if speed_col not in avg_speeds_df.columns: speed_col = None
    
    if speed_col:
        segments = segments.merge(avg_speeds_df[['km_interval', speed_col]], on='km_interval', how='left')
        segments['avg_speed'] = pd.to_numeric(segments[speed_col], errors='coerce')
    else:
        segments['avg_speed'] = constant_speed
        
    segments['avg_speed'] = segments['avg_speed'].fillna(constant_speed).astype(float)

    segments['effective_speed'] = segments['avg_speed']
    segments['dist_from_bus'] = (segments['km_interval'].astype(int) - start_km).abs()

    # apply current speed to weight in first km
    if current_speed is not None and not segments.empty:
        # Filter for the first segment only (First KM)
        first_km_mask = segments['dist_from_bus'] == 0
        
        if first_km_mask.any():
            historical = segments.loc[first_km_mask, 'avg_speed']

            # 0.2 * current speed + 0.8 * historical
            blended = (0.2 * current_speed) + (0.8 * historical)

            # clip speed to not be too low or high (prevent extremes!!)
            blended = blended.clip(lower=15.0, upper=50.0)
            
            # only the first km use blended speed
            segments.loc[first_km_mask, 'effective_speed'] = blended

    # apply route_bias weight
    global_bias = ROUTE_BIAS.get(route, 1.0)
    segments['effective_speed'] = segments['effective_speed'] * global_bias

    # calculate time (combine each segments)
    segments['segment_start_order'] = segments['km_interval'].astype(int) * ORDERS_PER_KM
    segments['segment_end_order'] = segments['segment_start_order'] + ORDERS_PER_KM
    segments['segment_start_order_clipped'] = np.clip(segments['segment_start_order'], bus_order, stop_order)
    segments['segment_end_order_clipped'] = np.clip(segments['segment_end_order'], bus_order, stop_order)
    segments['segment_distance_orders'] = (segments['segment_end_order_clipped'] - segments['segment_start_order_clipped'])
    
    segments = segments[segments['segment_distance_orders'] > 0]
    segments['segment_distance_km'] = (segments['segment_distance_orders'] * STEP_ORDER / 1000.0)
    
    # replace speed = 0 with speed = 15 to prevent division error
    segments['effective_speed'] = segments['effective_speed'].replace(0, 15) 
    
    # get travel time for each segment and combine
    segments['travel_time_hr'] = (segments['segment_distance_km'] / segments['effective_speed'])
    total_travel_time_min = int((segments['travel_time_hr'] * 60).sum())
    
    return total_travel_time_min

'''GET UPCOMING BUSES FOR ROUTE (FROM FILTERED BY ROUTE / STOP -> SORT BY ETA, CHOOSE 3)'''
def get_upcoming_buses(mapped_df, stop_name, route, route_status_flags, stop_status_flags, global_flags=None):
    # if entire route suspended / bus stop closed -> return
    if route_status_flags and route_status_flags.get("status") == "suspended":
        return pd.DataFrame(columns=['licence', 'eta_min', 'eta_time', 'status', 'message', 'type'])
    if stop_status_flags and stop_status_flags.get("status") == "closed":
        return pd.DataFrame(columns=['licence', 'eta_min', 'eta_time', 'status', 'message', 'type'])

    if global_flags is None: global_flags = load_flags()
    now = datetime.now()
    today = date.today()
    all_cols = ['licence', 'eta_min', 'eta_time', 'status', 'message', 'type'] 
    
    route_config = direction_map.get(route)
    if not route_config: return pd.DataFrame(columns=all_cols)
    
    stop_index = None
    for s in route_config.stop_list.values():
        if s['stop_name_eng'] == stop_name:
            stop_index = s.get('index', s.get('no')) 
            break
    if stop_index is None: return pd.DataFrame(columns=all_cols)
    
    # set up active buses df
    active_buses_df = pd.DataFrame(columns=all_cols)
    if not mapped_df.empty:
        filtered_active = mapped_df[mapped_df["bus_index"] < stop_index].copy()
        
        if not filtered_active.empty:
            def should_keep(row):
                key = f"bus:{row['licence']}"
                if key in global_flags and global_flags[key].get('status') == 'inactive':
                    return False
                return True

            filtered_active = filtered_active[filtered_active.apply(should_keep, axis=1)]
            
            if not filtered_active.empty:
                # Active buses still use their LIVE speed
                filtered_active['eta_min'] = filtered_active.apply(
                    lambda row: calc_eta(row['bus_index'], stop_index, route, float(row['spd'])), axis=1
                )
                filtered_active['eta_time'] = filtered_active['eta_min'].apply(
                    lambda x: (now + timedelta(minutes=x)).isoformat()
                )
                filtered_active['type'] = 'active'
                
                def get_status(licence):
                    key = f"bus:{licence}"
                    if key in global_flags and global_flags[key].get('status') == "delayed": return "DELAYED"
                    return "Active"
                def get_msg(licence):
                    key = f"bus:{licence}"
                    if key in global_flags: return global_flags[key].get('message', "Normal Operation")
                    return "Normal Operation"
                
                filtered_active['status'] = filtered_active['licence'].apply(get_status)
                filtered_active['message'] = filtered_active['licence'].apply(get_msg)
                
                active_buses_df = filtered_active[all_cols].sort_values(by='eta_min')

    # count buses (top 3 lowest ETA sorted)
    bus_list_to_return = active_buses_df.to_dict('records')
    slots_needed = 3 - len(bus_list_to_return)

    # if active buses are not enough -> use upcoming scheduled buses
    if slots_needed > 0:
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
                        upcoming_departures = departure_times[departure_times > now].sort_values()
                        
                        # Use base travel time (Historical only)
                        base_travel_time_min = calc_eta(0, stop_index, route) 
                        
                        count = 0
                        for depart_dt in upcoming_departures:
                            if count >= slots_needed: break
                            minutes_until_departure = (depart_dt - now).total_seconds() / 60.0
                            total_eta = int(round(minutes_until_departure + base_travel_time_min))
                            bus_list_to_return.append({
                                'licence': 'Scheduled',
                                'eta_min': total_eta,
                                'eta_time': (now + timedelta(minutes=total_eta)).isoformat(),
                                'status': 'Scheduled',
                                'message': "Normal Operation",
                                'type': 'scheduled'
                            })
                            count += 1
            except Exception: pass

    if not bus_list_to_return:
        return pd.DataFrame(columns=all_cols)
    final_df = pd.DataFrame(bus_list_to_return)
    final_df = final_df.sort_values(by='eta_min').reset_index(drop=True)
    return final_df.head(3)[all_cols]

# =========================================================
# STATS COLLECTION
# =========================================================

'''GET BUS DATA FOR ADMIN PAGE'''
def get_fleet_data_for_admin():
    try:
        bus_df = get_bus_data(API_URL, API_KEY)
        # SANITIZE DATA FROM COLLECT HISTORY
        # Fill NaN values with safe defaults to avoid JSON 500 error
        bus_df = collect_bus_history(bus_df).fillna({
            'licence': 'Unknown',
            'route': '-',
            'spd': 0
        }) 
        flags = load_flags()
        clean_expired_flags()
        
        fleet_list = []
        now = datetime.now()

        for route_name in line_options:
            route_buses = filter_bus(bus_df, route_name)
            if route_buses.empty: continue
            
            # Sort by timestamp to get latest, then drop duplicates
            route_buses = route_buses.sort_values('timestamp', ascending=False).drop_duplicates('licence')
            
            mapped_buses = map_index_df(route_buses, route_name)

            if mapped_buses.empty: continue

            for _, row in mapped_buses.iterrows():
                licence = str(row['licence']) # Ensure string
                key = f"bus:{licence}"
                
                # Safe timestamp handling
                try:
                    last_seen = pd.to_datetime(row['timestamp'])
                    if pd.isna(last_seen): raise ValueError
                    minutes_offline = (now - last_seen).total_seconds() / 60.0
                    seen_str = last_seen.strftime("%H:%M:%S")
                except:
                    minutes_offline = 0
                    seen_str = "-"
                
                status = "active"
                message = "-"
                
                if key in flags:
                    status = flags[key].get('status', 'active')
                    message = flags[key].get('message', '-')
                elif minutes_offline > OFFLINE_GRACE_PERIOD_MIN:
                    status = "Offline"
                    message = f"Last signal {int(minutes_offline)}m ago"

                fleet_list.append({
                    "license": licence,
                    "route": route_name,
                    "status": status,
                    "message": message,
                    "last_seen": seen_str
                })
        return fleet_list
    except Exception as e:
        print(f"ADMIN DATA ERROR: {e}")
        return []

'''GET BUS / ROUTE / STOP STATUS FOR DISPLAY'''
def get_all_system_statuses():
    try:
        flags = load_flags()
        clean_expired_flags()
        system_status = []
        
        # 1. Routes
        for route_name in line_options:
            key = f"route:{route_name}"
            data = flags.get(key, {})
            system_status.append({
                "type": "route",
                "id": route_name,
                "status": data.get("status", "active"),
                "message": data.get("message", "-")
            })
            
            # 2. Stops
            route_config = direction_map.get(route_name)
            if route_config:
                for stop in route_config.stop_list.values():
                    stop_key = f"stop:{route_name}:{stop['no']}"
                    s_data = flags.get(stop_key, {})
                    system_status.append({
                        "type": "stop",
                        "route_name": route_name, 
                        "stop_id": str(stop['no']),    
                        "stop_name": stop['stop_name_eng'],
                        "id": f"{route_name}: {stop['no']}", 
                        "raw_id": f"{route_name}:{stop['no']}",
                        "status": s_data.get("status", "open"),
                        "message": s_data.get("message", "-")
                    })

        # 3. Buses
        bus_df = get_bus_data(API_URL, API_KEY)
        bus_df = collect_bus_history(bus_df).fillna({
            'licence': 'Unknown', 'route': '-'
        })
        
        if not bus_df.empty:
            bus_df = bus_df.sort_values('timestamp', ascending=False).drop_duplicates('licence')
            now = datetime.now()
            
            for _, row in bus_df.iterrows():
                lic = str(row['licence'])
                key = f"bus:{lic}"
                
                status = "active"
                msg = "-"
                
                try:
                    last_seen = pd.to_datetime(row['timestamp'])
                    if pd.isna(last_seen): raise ValueError
                    off_min = (now - last_seen).total_seconds() / 60.0
                except:
                    off_min = 0
                
                if key in flags:
                    status = flags[key].get('status', 'active')
                    msg = flags[key].get('message', '-')
                elif off_min > OFFLINE_GRACE_PERIOD_MIN:
                    status = "Offline"
                    msg = f"Last seen {int(off_min)}m ago"
                
                system_status.append({
                    "type": "bus",
                    "id": lic,
                    "route": row['route'],
                    "status": status,
                    "message": msg
                })
            
        return system_status

    except Exception as e:
        print(f"STATUS FETCH ERROR: {e}")
        return []

'''GET ACCURACY ETA STATS FOR DISPLAY GRAPH'''
def get_live_accuracy_stats():
    # ACCURACY_CSV defined at top of file
    output = {}
    routes = ["All"] + line_options
    
    for r in routes:
        output[r] = {
            "chart": {i: [] for i in range(0, 125, 5)}, 
            "text": { "0-15": [], "15-30": [], "30-45": [], "45-60": [], "60+": [] }
        }

    if not os.path.exists(ACCURACY_CSV): return format_accuracy_output(output)

    try:
        df = pd.read_csv(ACCURACY_CSV)
        df['arrival_time'] = pd.to_datetime(df['arrival_time'])
        df['registration_time'] = pd.to_datetime(df['registration_time'])
        df['total_travel_time'] = (df['arrival_time'] - df['registration_time']).dt.total_seconds() / 60.0
        
        for _, row in df.iterrows():
            if pd.isna(row['total_travel_time']): continue
            route_name = row['route']
            total_time = row['total_travel_time']
            
            for t in [0, 15, 30, 45, 60, 75, 90, 105, 120]:
                eta_col = f"eta_min_T{t}"
                if eta_col in df.columns and pd.notna(row[eta_col]):
                    predicted_eta = float(row[eta_col])
                    remaining = total_time - t
                    
                    if remaining < 0 or remaining > 150: continue
                    
                    delay = remaining - predicted_eta 
                    
                    add_to_bins(output["All"], remaining, delay)
                    if route_name in output:
                        add_to_bins(output[route_name], remaining, delay)
                        
        return format_accuracy_output(output)

    except Exception as e:
        print(f"[ACCURACY CALC ERROR] {e}")
        return format_accuracy_output(output)

'''SORT ETA DATA INTO DIFFERENT BINS BASED ON ACTUAL TIME (mins) BEFORE ARRIVAL'''
def add_to_bins(route_dict, remaining, val):
    chart_bin = int(remaining // 5) * 5
    if chart_bin in route_dict["chart"]:
        route_dict["chart"][chart_bin].append(val)
        
    if 0 <= remaining < 15: route_dict["text"]["0-15"].append(val)
    elif 15 <= remaining < 30: route_dict["text"]["15-30"].append(val)
    elif 30 <= remaining < 45: route_dict["text"]["30-45"].append(val)
    elif 45 <= remaining < 60: route_dict["text"]["45-60"].append(val)
    elif remaining >= 60: route_dict["text"]["60+"].append(val)

'''FORMAT OUTPUT'''
def format_accuracy_output(raw_data):
    final_response = {}
    
    for route, data in raw_data.items():
        # 1. Prepare Scatter Data
        scatter_points = []
        x_values = []
        y_values = []
        
        # Iterate through sorted keys (0, 5, 10...)
        for bin_key in sorted(data["chart"].keys()):
            delays = data["chart"][bin_key]
            
            if delays: 
                avg_delay = sum(delays) / len(delays)
                
                point = {"x": bin_key, "y": round(avg_delay, 1)}
                scatter_points.append(point)
                
                x_values.append(bin_key)
                y_values.append(avg_delay)

        # 2. Calculate Linear Trend Line
        trend_line_points = []
        if len(x_values) > 1:
            try:
                z = np.polyfit(x_values, y_values, 1) 
                p = np.poly1d(z)
                for x in x_values:
                    trend_line_points.append({
                        "x": x,
                        "y": round(p(x), 1)
                    })
            except Exception:
                pass 

        # 3. Calculate Text Summaries
        text_summary = {}
        for bin_key, delays in data["text"].items():
            avg_delay = sum(delays) / len(delays) if delays else 0
            text_summary[bin_key] = round(avg_delay, 1)
            
        final_response[route] = {
            "scatter": scatter_points, 
            "trendline": trend_line_points,
            "summary": text_summary
        }
        
    return final_response

# =========================================================
# SECTION 5: WORKER PROCESS
# =========================================================

'''MAIN FUNCTION TO GET ALL ETAs'''
def calculate_all_etas():
    try:
        clean_expired_flags()
        bus_df = get_bus_data(API_URL, API_KEY)
        bus_df = collect_bus_history(bus_df) 
        all_routes_data = {}
        flags = load_flags()
        now = datetime.now()

        for route_name in line_options:
            route_config = direction_map[route_name]
            route_key = f"route:{route_name}"
            route_status_flags = flags.get(route_key)
            filtered_df = filter_bus(bus_df, route_name)
            filtered_df = filtered_df.loc[:, ~filtered_df.columns.duplicated()]
            
            # Filter stale buses (Grace Period)
            def is_fresh(row):
                if pd.isna(row['timestamp']): return False
                diff = (now - row['timestamp']).total_seconds() / 60.0
                return diff < OFFLINE_GRACE_PERIOD_MIN
            
            if not filtered_df.empty:
                filtered_df = filtered_df[filtered_df.apply(is_fresh, axis=1)]

            mapped_df = map_index_df(filtered_df, route_name)

            # --- NEW FILTER ---
            # Remove buses near start (index < 50) that are idle (spd < 1)
            # This logic also ensures buses that failed to map (index -1 or NaN) are handled
            if not mapped_df.empty:
                mapped_df['bus_index'] = pd.to_numeric(mapped_df['bus_index'], errors='coerce')
                mapped_df['spd'] = pd.to_numeric(mapped_df['spd'], errors='coerce')
                
                # Keep if: Index >= 50 OR Speed >= 1
                # Drop if: Index < 50 AND Speed < 1
                mapped_df = mapped_df[~((mapped_df['bus_index'] < 50) & (mapped_df['spd'] < 1))]
            # ------------------

            all_stop_etas = {}
            for stop_id, stop_info in route_config.stop_list.items():
                stop_name = stop_info['stop_name_eng']
                stop_key = f"stop:{route_name}:{stop_info['no']}"
                stop_status_flags = flags.get(stop_key)
                
                stop_result = {
                    "no": stop_info['no'],
                    "index": stop_info['index'],
                    "stop_name_eng": stop_info['stop_name_eng'],
                    "stop_name_th": stop_info['stop_name_th'],
                    "lat": stop_info['lat'],
                    "lon": stop_info['lon'],
                    "stop_status": stop_status_flags.get("status", "open") if stop_status_flags else "open",
                    "stop_message": stop_status_flags.get("message") if stop_status_flags else None
                }
                
                if stop_result["stop_status"] == "closed":
                    stop_result["detail"] = f"Stop Closed: {stop_result['stop_message']}"

                try:
                    upcoming_buses_df = get_upcoming_buses(
                        mapped_df, stop_name, route_name, route_status_flags, stop_status_flags, flags
                    )
                    
                    if not upcoming_buses_df.empty:
                        upcoming_list = upcoming_buses_df.to_dict('records')
                        stop_result["upcoming"] = upcoming_list
                    else:
                        is_suspended = route_status_flags and route_status_flags.get("status") == "suspended"
                        is_stop_closed = stop_status_flags and stop_status_flags.get("status") == "closed"
                        
                        if is_suspended:
                            msg = f"Route Suspended: {route_status_flags.get('message', 'Service Temporarily Unavailable')}"
                            status = "Suspended"
                            stop_result["detail"] = msg
                        elif is_stop_closed:
                            msg = f"Stop Closed: {stop_status_flags.get('message', 'Out of Service')}"
                            status = "Closed"
                            stop_result["detail"] = msg
                        else:
                            msg = "No more buses for today"
                            status = "Ended"

                        stop_result.update({
                            "eta_min": -1,
                            "message": msg,
                            "licence": "-",
                            "status": status,
                            "upcoming": []
                        })
                except Exception as e:
                    stop_result.update({"eta_min": -1, "status": "Error", "message": str(e), "upcoming": []})

                all_stop_etas[stop_name] = stop_result
            
            r_status = route_status_flags.get("status", "active") if route_status_flags else "active"
            r_msg = route_status_flags.get("message") if route_status_flags else None
            
            all_routes_data[route_name] = {
                "route": route_name,
                "updated_at": datetime.now().isoformat(),
                "route_status": r_status,
                "route_message": r_msg,
                "stops": all_stop_etas 
            }
            
            if r_status == "suspended":
                all_routes_data[route_name]["detail"] = f"Route Suspended: {r_msg}"

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