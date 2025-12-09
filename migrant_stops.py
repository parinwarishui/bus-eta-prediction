import json
import os
import sys

# Add current directory to path so we can import stop_access
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from stop_access import direction_map
except ImportError:
    print("Error: Could not find 'stop_access.py'. Make sure this script is in the same folder.")
    sys.exit(1)

def migrate():
    print("Read 'stop_access.py' successfully.")
    print(f"Found {len(direction_map)} routes to migrate...")

    output_data = {"routes": {}}

    for route_key, config in direction_map.items():
        print(f"Processing: {route_key}")

        # 1. Transform Stops
        # We need to map 'stop_name_eng' -> 'name_eng' to match your new spec
        stops_transformed = {}
        
        # Sort stops by index just to be tidy in the JSON
        sorted_stops = sorted(config.stop_list.items(), key=lambda item: item[1]['index'])

        for stop_key, stop_val in sorted_stops:
            stops_transformed[str(stop_key)] = {
                "no": stop_val['no'],
                "index": stop_val['index'],
                "lat": stop_val['lat'],
                "lon": stop_val['lon'],
                "name_eng": stop_val['stop_name_eng'],
                "name_th": stop_val['stop_name_th']
            }

        # 2. Build Route Object
        route_object = {
            "line": config.line,
            "buffer": config.buffer,
            "direction": config.direction,
            "files": {
                "geojson": config.geojson_path,
                "schedule": config.schedule_path,
                "speeds": config.speeds_path
            },
            "stops": stops_transformed
        }

        output_data["routes"][route_key] = route_object

    # 3. Write to JSON
    output_filename = "routes_data.json"
    try:
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"\nSUCCESS! Data exported to '{output_filename}'")
        print("You can now verify the file and then replace 'stop_access.py' with the new loader code.")
    except Exception as e:
        print(f"Error writing file: {e}")

if __name__ == "__main__":
    migrate()