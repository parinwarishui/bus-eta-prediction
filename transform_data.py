import json
import os
# IMPORT YOUR OLD DATA HERE
# If your old stop_access.py is named something else, change this import
from stop_access import direction_map 

OUTPUT_FILE = "routes_data.json"

def convert_to_json():
    routes_json = {}
    
    # 1. Iterate over your existing python dictionary
    for route_name, route_obj in direction_map.items():
        print(f"Processing {route_name}...")
        
        # 2. Build the new JSON structure
        routes_json[route_name] = {
            "line": route_obj.line,
            "buffer": route_obj.buffer,
            "direction": route_obj.direction,
            "files": {
                "geojson": route_obj.geojson_path,
                "schedule": route_obj.schedule_path,
                "speeds": route_obj.speeds_path
            },
            # 3. Handle Special Overlap/Layover Logic dynamically
            "overlap": route_obj.overlap,
            # We will migrate hardcoded layovers to this config later, 
            # for now, we init it as None or manual entry
            "layover": None, 
            "stops": {}
        }
        
        # 4. Transform Stops
        # Your old stops might be keyed by ID or Name, we standardize to Name Key
        # but keep ID for lookups.
        for s_key, s_val in route_obj.stop_list.items():
            # If s_val is a dict (standard), copy it.
            # If it's an object, convert to dict.
            stop_data = s_val if isinstance(s_val, dict) else s_val.__dict__
            
            # Ensure keys match new format
            clean_stop = {
                "no": stop_data.get('no'),
                "index": stop_data.get('index'),
                "lat": stop_data.get('lat'),
                "lon": stop_data.get('lon'),
                "name_eng": stop_data.get('stop_name_eng'),
                "name_th": stop_data.get('stop_name_th')
            }
            # Use English Name as the key for the JSON dict
            routes_json[route_name]["stops"][clean_stop["name_eng"]] = clean_stop

    # 5. Add Layover Config Manually (Migration Step)
    # This replaces the hardcoded dictionary in services.py
    if "Patong -> Bus 1 -> Bus 2" in routes_json:
        routes_json["Patong -> Bus 1 -> Bus 2"]["layover"] = {"stop_index": 3774, "duration": 30}
        
    if "Bus 2 -> Bus 1 -> Patong" in routes_json:
        routes_json["Bus 2 -> Bus 1 -> Patong"]["layover"] = {"stop_index": 1581, "duration": 30}

    # 6. Save to File
    final_structure = {"routes": routes_json}
    with open(OUTPUT_FILE, "w", encoding='utf-8') as f:
        json.dump(final_structure, f, indent=4, ensure_ascii=False)
    
    print(f"✅ Successfully created {OUTPUT_FILE}")

if __name__ == "__main__":
    convert_to_json()