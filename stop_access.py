import json
import os
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional

# Constants
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "routes_data.json")

# ===================== DATA CLASSES =====================

@dataclass
class Stop:
    no: int
    stop_name_eng: str
    stop_name_th: str
    lat: float
    lon: float
    direction: str
    route_index: int

@dataclass
class RouteConfig:
    key: str
    line: str
    buffer: str
    direction: str
    geojson_path: str
    schedule_path: str
    speeds_path: Optional[str]
    stop_list: Dict[str, Dict]
    overlap: Optional[Dict]
    layover: Optional[Dict] # [NEW] Added Layover field

    def stops(self) -> List[Stop]:
        """Return stop list sorted by route index (sequence along the route)."""
        sorted_stops = sorted(self.stop_list.values(), key=lambda s: s.get("index", 0))
        return [
            Stop(
                no=s["no"],
                stop_name_eng=s.get("name_eng", s.get("stop_name_eng")),
                stop_name_th=s.get("name_th", s.get("stop_name_th")),
                lat=s["lat"],
                lon=s["lon"],
                direction=self.direction,
                route_index=s["index"]
            )
            for s in sorted_stops
        ]

# ===================== LOADER LOGIC =====================

def load_routes_from_json():
    """Reads routes_data.json and returns the direction_map and line_options."""
    if not os.path.exists(CONFIG_FILE):
        print(f"[WARN] Configuration file not found: {CONFIG_FILE}")
        return {}, []

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[CRITICAL] Failed to parse routes_data.json: {e}")
        return {}, []

    loaded_map = {}
    raw_routes = data.get("routes", {})
    loaded_options = list(raw_routes.keys())

    for route_key, r_data in raw_routes.items():
        stop_dict_cleaned = {}
        for s_key, s_val in r_data.get("stops", {}).items():
            stop_dict_cleaned[s_key] = {
                "no": s_val["no"],
                "index": s_val["index"],
                "lat": s_val["lat"],
                "lon": s_val["lon"],
                "stop_name_eng": s_val.get("name_eng", s_key),
                "stop_name_th": s_val.get("name_th", ""),
                "direction": r_data["direction"] 
            }

        loaded_map[route_key] = RouteConfig(
            key=route_key,
            line=r_data["line"],
            buffer=r_data.get("buffer", ""),
            direction=r_data["direction"],
            geojson_path=r_data["files"]["geojson"],
            schedule_path=r_data["files"]["schedule"],
            speeds_path=r_data["files"]["speeds"],
            stop_list=stop_dict_cleaned,
            overlap=r_data.get("overlap"),
            layover=r_data.get("layover")
        )
    
    return loaded_map, loaded_options

# === INITIALIZATION ===
direction_map, line_options = load_routes_from_json()

# ===================== ACCESS FUNCTIONS =====================

def list_routes() -> List[str]:
    return line_options

def get_route(direction_name: str) -> Optional[RouteConfig]:
    return direction_map.get(direction_name)

def get_stops(direction_name: str) -> Optional[List[Stop]]:
    route = get_route(direction_name)
    return route.stops() if route else None