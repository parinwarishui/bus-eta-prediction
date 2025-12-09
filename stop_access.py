import json, os
from dataclasses import dataclass
from typing import List, Dict, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "routes_data.json")

@dataclass
class Stop:
    no: int; stop_name_eng: str; stop_name_th: str; lat: float; lon: float; direction: str; route_index: int

@dataclass
class RouteConfig:
    key: str; line: str; buffer: str; direction: str; geojson_path: str; schedule_path: str; speeds_path: Optional[str]
    stop_list: Dict[str, Dict]; overlap: Optional[Dict]; layover: Optional[Dict]

    def stops(self) -> List[Stop]:
        sorted_stops = sorted(self.stop_list.values(), key=lambda s: s.get("index", 0))
        return [Stop(no=s["no"], stop_name_eng=s.get("name_eng", s.get("stop_name_eng")), stop_name_th=s.get("name_th", ""), lat=s["lat"], lon=s["lon"], direction=self.direction, route_index=s["index"]) for s in sorted_stops]

def load_routes_from_json():
    if not os.path.exists(CONFIG_FILE): return {}, []
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
    loaded_map = {}; raw_routes = data.get("routes", {})
    for k, r in raw_routes.items():
        stop_dict = {}
        for sk, sv in r.get("stops", {}).items():
            stop_dict[sk] = {"no": sv["no"], "index": sv["index"], "lat": sv["lat"], "lon": sv["lon"], "stop_name_eng": sv.get("name_eng", sk), "stop_name_th": sv.get("name_th", "")}
        loaded_map[k] = RouteConfig(key=k, line=r["line"], buffer=r.get("buffer",""), direction=r["direction"], geojson_path=r["files"]["geojson"], schedule_path=r["files"]["schedule"], speeds_path=r["files"]["speeds"], stop_list=stop_dict, overlap=r.get("overlap"), layover=r.get("layover"))
    return loaded_map, list(raw_routes.keys())

direction_map, line_options = load_routes_from_json()