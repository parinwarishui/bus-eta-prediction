from stop_lists import (
    stop_list_airport_rawai,
    stop_list_rawai_airport,
    stop_list_bus2_bus1_patong,
    stop_list_patong_bus1_bus2,
    stop_list_dragon_line
)

from dataclasses import dataclass, asdict
from typing import List, Dict, Optional

# ===================== DATA CLASSES =====================

@dataclass
class Stop:
    no: int
    stop_name_eng: str
    stop_name_th: str
    lat: float
    lon: float
    direction: str
    route_index: int  # This corresponds to 'index' in the dict

@dataclass
class RouteConfig:
    key: str
    line: str
    buffer: str
    direction: str
    geojson_path: str
    schedule_path: str
    speeds_path: Optional[str]
    stop_list: Dict[str, Dict]  # Now keyed by stop "no"

    def stops(self) -> List[Stop]:
        """Return stop list sorted by route index (sequence along the route)."""
        sorted_stops = sorted(self.stop_list.values(), key=lambda s: s.get("index", 0))
        return [
            Stop(
                no=s["no"],
                stop_name_eng=s["stop_name_eng"],
                stop_name_th=s["stop_name_th"],
                lat=s["lat"],
                lon=s["lon"],
                direction=s["direction"],
                route_index=s["index"]
            )
            for s in sorted_stops
        ]

    def to_json(self) -> Dict:
        return {
            "route_name": self.key,
            "stops": [asdict(s) for s in self.stops()]
        }

# ===================== ROUTES CONFIG =====================

line_options = [
    "Airport -> Rawai",
    "Rawai -> Airport",
    "Bus 2 -> Bus 1 -> Patong",
    "Patong -> Bus 1 -> Bus 2",
    "Dragon Line"
]

direction_map: Dict[str, RouteConfig] = {
    "Airport -> Rawai": RouteConfig(
        key="Airport -> Rawai",
        line="Phuket Airport to Rawai",
        buffer="Rawai",
        direction="Bus to Rawai",
        geojson_path="data_routes/airport_rawai_ordered.geojson",
        schedule_path="data_schedules/airport_rawai_bus_schedule.csv",
        speeds_path="data_speeds/airport_rawai_speeds.csv",
        stop_list=stop_list_airport_rawai
    ),
    "Rawai -> Airport": RouteConfig(
        key="Rawai -> Airport",
        line="Rawai to Phuket Airport",
        buffer="Phuket Airport",
        direction="Bus to Airport",
        geojson_path="data_routes/rawai_airport_ordered.geojson",
        schedule_path="data_schedules/rawai_airport_bus_schedule.csv",
        speeds_path="data_speeds/rawai_airport_speeds.csv",
        stop_list=stop_list_rawai_airport
    ),
    "Bus 2 -> Bus 1 -> Patong": RouteConfig(
        key="Bus 2 -> Bus 1 -> Patong",
        line="Phuket Bus Terminal 1 to Patong",
        buffer="Patong",
        direction="Bus to Terminal 1",
        geojson_path="data_routes/bus2_bus1_patong_ordered.geojson",
        schedule_path="data_schedules/bus2_bus1_patong_schedule.csv",
        speeds_path="data_speeds/bus2_bus1_patong_speeds.csv",
        stop_list=stop_list_bus2_bus1_patong
    ),
    "Patong -> Bus 1 -> Bus 2": RouteConfig(
        key="Patong -> Bus 1 -> Bus 2",
        line="Patong to Phuket Bus Terminal 1",
        buffer="Patong",
        direction="Bus to Patong",
        geojson_path="data_routes/patong_bus1_bus2_ordered.geojson",
        schedule_path="data_schedules/patong_bus1_bus2_schedule.csv",
        speeds_path="data_speeds/patong_bus1_bus2_speeds.csv",
        stop_list=stop_list_patong_bus1_bus2
    ),
    "Dragon Line": RouteConfig(
        key="Dragon Line",
        line="Dragon Line",
        buffer="Dragon Line",
        direction="Old Town Bus",
        geojson_path="data_routes/dragonline_ordered.geojson",
        schedule_path="data_schedules/dragonline_schedule.csv",
        speeds_path=None,
        stop_list=stop_list_dragon_line
    )
}

# ===================== ACCESS FUNCTIONS =====================

def list_routes() -> List[str]:
    """Return list of available route keys."""
    return list(direction_map.keys())

def get_route(direction_name: str) -> Optional[RouteConfig]:
    """Return RouteConfig object for a direction."""
    return direction_map.get(direction_name)

def get_stops(direction_name: str) -> Optional[List[Stop]]:
    """Return Stop objects for a given route."""
    route = get_route(direction_name)
    return route.stops() if route else None

def get_stop_by_name(direction_name: str, stop_name: str) -> Optional[Stop]:
    """Find a stop by English or Thai name."""
    stops = get_stops(direction_name)
    if not stops:
        return None
    stop_name_lower = stop_name.lower()
    for s in stops:
        if stop_name_lower in s.stop_name_eng.lower() or stop_name_lower in s.stop_name_th.lower():
            return s
    return None
