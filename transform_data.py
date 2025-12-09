import json
import os
# Rename your OLD stop_access.py to legacy_data.py before running this
from legacy_data import direction_map 

OUTPUT_FILE = "routes_data.json"

def convert_to_json():
    routes_json = {}
    
    for route_name, route_obj in direction_map.items():
        print(f"Processing {route_name}...")
        
        # Force forward slashes for web compatibility
        geo_path = route_obj.geojson_path.replace("\\", "/")
        sched_path = route_obj.schedule_path.replace("\\", "/") if route_obj.schedule_path else None
        speed_path = route_obj.speeds_path.replace("\\", "/") if route_obj.speeds_path else None

        routes_json[route_name] = {
            "line": route_obj.line,
            "buffer": route_obj.buffer,
            "direction": route_obj.direction,
            "files": {
                "geojson": geo_path,
                "schedule": sched_path,
                "speeds": speed_path
            },
            "overlap": route_obj.overlap,
            "layover": None, 
            "stops": {}
        }
        
        for s_key, s_val in route_obj.stop_list.items():
            stop_data = s_val if isinstance(s_val, dict) else s_val.__dict__
            clean_stop = {
                "no": stop_data.get('no'),
                "index": stop_data.get('index'),
                "lat": stop_data.get('lat'),
                "lon": stop_data.get('lon'),
                "name_eng": stop_data.get('stop_name_eng'),
                "name_th": stop_data.get('stop_name_th')
            }
            routes_json[route_name]["stops"][clean_stop["name_eng"]] = clean_stop

    # Inject Layover Config
    if "Patong -> Bus 1 -> Bus 2" in routes_json:
        routes_json["Patong -> Bus 1 -> Bus 2"]["layover"] = {"stop_index": 3774, "duration": 30}
    if "Bus 2 -> Bus 1 -> Patong" in routes_json:
        routes_json["Bus 2 -> Bus 1 -> Patong"]["layover"] = {"stop_index": 1581, "duration": 30}

    with open(OUTPUT_FILE, "w", encoding='utf-8') as f:
        json.dump({"routes": routes_json}, f, indent=4, ensure_ascii=False)
    
    print(f"✅ Created {OUTPUT_FILE}")

if __name__ == "__main__":
    convert_to_json()