import os
import json
import shutil
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from stop_access import CONFIG_FILE
from services import map_index, load_route_coords
from math import radians, cos, sin, asin, sqrt

admin_router = APIRouter(prefix="/admin/api")

# Directories
DATA_ROUTES_DIR = "data_routes"
DATA_SCHED_DIR = "data_schedules"
DATA_SPEED_DIR = "data_speeds"

for d in [DATA_ROUTES_DIR, DATA_SCHED_DIR, DATA_SPEED_DIR]:
    os.makedirs(d, exist_ok=True)

# --- HELPERS ---

def read_json_db():
    if not os.path.exists(CONFIG_FILE): return {"routes": {}}
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f: return json.load(f)

def save_json_db(data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_unique_base_filename(original_base):
    counter = 0
    candidate = original_base
    while True:
        p1 = os.path.join(DATA_ROUTES_DIR, f"{candidate}_ordered.geojson")
        if not os.path.exists(p1): return candidate
        counter += 1
        candidate = f"{original_base}_{counter}"

def haversine(lon1, lat1, lon2, lat2):
    """Calculate distance in meters between two coordinates"""
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a)) 
    r = 6371000 # Radius of earth in meters
    return c * r

# --- SMART GEOJSON PROCESSOR ---

def process_and_save_geojson(file: UploadFile, filename_base: str):
    content = json.load(file.file)
    raw_features = []
    
    # 1. EXTRACT ALL POINTS (Explode Lines if needed)
    if "features" in content:
        for f in content["features"]:
            geom = f.get("geometry", {})
            ctype = geom.get("type")
            coords = geom.get("coordinates", [])

            if ctype == "Point":
                raw_features.append(f)
            elif ctype == "LineString":
                for point_coords in coords:
                    raw_features.append({
                        "type": "Feature", "properties": {},
                        "geometry": {"type": "Point", "coordinates": point_coords}
                    })

    elif content.get("type") == "LineString":
         for point_coords in content.get("coordinates", []):
            raw_features.append({
                "type": "Feature", "properties": {}, 
                "geometry": {"type": "Point", "coordinates": point_coords}
            })

    if not raw_features:
        raise HTTPException(status_code=400, detail="No valid coordinates found")

    # 2. SMART SORTING LOGIC (Nearest Neighbor with Threshold)
    sorted_features = []
    
    # Start with the first point in the file (Assumed Start)
    current_idx = 0
    unmapped_indices = set(range(1, len(raw_features))) # All indices except 0
    
    # Add first point
    sorted_features.append(raw_features[0])
    last_idx = 0
    
    while unmapped_indices:
        last_feature = raw_features[last_idx]
        last_lon = last_feature["geometry"]["coordinates"][0]
        last_lat = last_feature["geometry"]["coordinates"][1]
        
        # Candidate 1: The sequential next point in the file
        next_seq_idx = last_idx + 1
        found_next = False
        
        if next_seq_idx in unmapped_indices:
            seq_feature = raw_features[next_seq_idx]
            seq_lon = seq_feature["geometry"]["coordinates"][0]
            seq_lat = seq_feature["geometry"]["coordinates"][1]
            
            dist = haversine(last_lon, last_lat, seq_lon, seq_lat)
            
            # Logic: If next point is < 10m away, trust the file order
            if dist < 10:
                best_idx = next_seq_idx
                found_next = True
        
        # Candidate 2: Search ALL unmapped points (if sequential check failed)
        if not found_next:
            best_idx = -1
            min_dist = float('inf')
            
            for idx in unmapped_indices:
                cand_feat = raw_features[idx]
                c_lon = cand_feat["geometry"]["coordinates"][0]
                c_lat = cand_feat["geometry"]["coordinates"][1]
                
                dist = haversine(last_lon, last_lat, c_lon, c_lat)
                
                if dist < min_dist:
                    min_dist = dist
                    best_idx = idx
            
            # If we still found nothing (shouldn't happen unless empty), break
            if best_idx == -1: break
            
        # 3. Add the winner to the sorted list
        sorted_features.append(raw_features[best_idx])
        unmapped_indices.remove(best_idx)
        last_idx = best_idx # Continue chain from here

    # 4. RE-INDEX ORDER (0 to N)
    for i, feature in enumerate(sorted_features):
        if "properties" not in feature: feature["properties"] = {}
        feature["properties"]["order"] = i
        feature["properties"]["Id"] = i
    
    # 5. SAVE
    new_content = { "type": "FeatureCollection", "features": sorted_features }
    
    save_name = f"{filename_base}_ordered.geojson"
    save_path = os.path.join(DATA_ROUTES_DIR, save_name)
    
    with open(save_path, 'w', encoding='utf-8') as f:
        json.dump(new_content, f, indent=4)
        
    return f"{DATA_ROUTES_DIR}/{save_name}"

# --- ENDPOINTS ---

@admin_router.post("/add-route")
async def add_route(
    route_name: str = Form(...), line: str = Form(...), buffer: str = Form(...), direction: str = Form(...),
    geojson_file: UploadFile = File(...), schedule_file: UploadFile = File(...), speeds_file: UploadFile = File(None)
):
    db = read_json_db()
    if route_name in db["routes"]: raise HTTPException(400, "Route exists")

    raw_base = route_name.lower().replace(" -> ", "_").replace(" ", "_").replace("->", "_")
    base = get_unique_base_filename(raw_base)

    geojson_path = process_and_save_geojson(geojson_file, base)

    sched_name = f"{base}_schedule.csv"
    sched_path = os.path.join(DATA_SCHED_DIR, sched_name)
    with open(sched_path, "wb") as f: shutil.copyfileobj(schedule_file.file, f)
    sched_web_path = f"{DATA_SCHED_DIR}/{sched_name}"

    speeds_web_path = None
    if speeds_file:
        speed_name = f"{base}_speeds.csv"
        speed_path = os.path.join(DATA_SPEED_DIR, speed_name)
        with open(speed_path, "wb") as f: shutil.copyfileobj(speeds_file.file, f)
        speeds_web_path = f"{DATA_SPEED_DIR}/{speed_name}"

    db["routes"][route_name] = {
        "line": line, "buffer": buffer, "direction": direction,
        "files": { "geojson": geojson_path, "schedule": sched_web_path, "speeds": speeds_web_path },
        "overlap": None, "layover": None, "stops": {}
    }
    save_json_db(db)
    return {"status": "success", "message": f"Route {route_name} created"}

@admin_router.post("/add-stop")
async def add_stop(
    route_name: str = Form(...), stop_name_eng: str = Form(...), stop_name_th: str = Form(...),
    lat: float = Form(...), lon: float = Form(...)
):
    db = read_json_db()
    route = db["routes"].get(route_name)
    if not route: raise HTTPException(404, "Route not found")

    max_id = 0
    for r in db["routes"].values():
        for s in r["stops"].values():
            if s["no"] > max_id: max_id = s["no"]
    new_id = max_id + 1

    try:
        # Load local path
        local_geo_path = route["files"]["geojson"].replace("/", os.sep)
        route_coords = load_route_coords(local_geo_path)
        mapped_index = map_index(lon, lat, route_coords)
    except Exception as e:
        print(f"Map Error: {e}"); mapped_index = 0 

    if mapped_index == -1: raise HTTPException(400, "Stop too far from line")

    new_stop = {
        "no": new_id, "index": mapped_index, "lat": lat, "lon": lon,
        "name_eng": stop_name_eng, "name_th": stop_name_th
    }
    db["routes"][route_name]["stops"][stop_name_eng] = new_stop
    save_json_db(db)
    return {"status": "success", "stop": new_stop}

@admin_router.post("/remove-stop")
async def remove_stop(route_name: str = Form(...), stop_name_key: str = Form(...)):
    db = read_json_db()
    if route_name in db["routes"] and stop_name_key in db["routes"][route_name]["stops"]:
        del db["routes"][route_name]["stops"][stop_name_key]
        save_json_db(db)
        return {"status": "success"}
    raise HTTPException(404, "Stop not found")