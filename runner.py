import uvicorn
import services
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Path
from fastapi.responses import JSONResponse
from stop_access import direction_map 

ROUTE_SLUGS = {
    "airport-rawai": "Airport -> Rawai",
    "rawai-airport": "Rawai -> Airport",
    "terminal-patong": "Bus 2 -> Bus 1 -> Patong",
    "patong-terminal": "Patong -> Bus 1 -> Bus 2",
    "dragon-line": "Dragon Line"
}

# === LIFECYCLE MANAGER ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start the worker from services
    print("[LIFECYCLE] Starting background worker...")
    services.start_worker()
    yield
    # Shutdown: Stop the worker
    print("[LIFECYCLE] Stopping background worker...")
    services.stop_worker()

# === FASTAPI SETUP ===
app = FastAPI(title="Phuket Bus ETA API", lifespan=lifespan)

# === HELPER FUNCTIONS ===
def resolve_route_key(route_identifier: str):
    if route_identifier in ROUTE_SLUGS:
        return ROUTE_SLUGS[route_identifier]
    if route_identifier in direction_map:
        return route_identifier
    return None

def success_response(data):
    return JSONResponse(
        content=data,
        media_type="application/json; charset=utf-8",
        status_code=200
    )

# === ENDPOINTS ===

@app.get("/")
async def get_all_data():
    data = services.load_data()
    help_info = {
        "message": "Data loaded.",
        "endpoints": ["GET /<slug>", "GET /<slug>/<stop_no>"]
    }
    if data is None:
        return success_response({"status": "initializing", "info": help_info})
    return success_response({"data": data, "info": help_info})

@app.get("/{route_identifier}")
async def get_route_data(route_identifier: str = Path(...)):
    real_route_key = resolve_route_key(route_identifier)
    if not real_route_key:
        raise HTTPException(status_code=404, detail="Route not found")

    data = services.load_data()
    if not data or real_route_key not in data:
        raise HTTPException(status_code=404, detail="No data available")
        
    return success_response(data[real_route_key])

@app.get("/{route_identifier}/{stop_no}")
async def get_stop_data(route_identifier: str, stop_no: int):
    real_route_key = resolve_route_key(route_identifier)
    if not real_route_key:
        raise HTTPException(status_code=404, detail="Route not found")

    # FIX: Access Object Attribute
    route_config = direction_map[real_route_key]
    target_stop = next((s for s in route_config.stop_list if s['no'] == stop_no), None)
            
    if not target_stop:
        raise HTTPException(status_code=404, detail=f"Stop {stop_no} not found")
    
    stop_name_eng = target_stop['stop_name_eng']
    data = services.load_data()
    
    if not data or real_route_key not in data:
         raise HTTPException(status_code=503, detail="Data initializing")

    stops_data = data[real_route_key].get("stops", {})
    if stop_name_eng not in stops_data:
        raise HTTPException(status_code=404, detail="Stop data unavailable")

    return success_response({
        "route_slug": route_identifier,
        "stop_no": stop_no,
        "stop_info": target_stop,
        "live_eta": stops_data[stop_name_eng]
    })

if __name__ == "__main__":
    print("Starting API...")
    uvicorn.run("runner:app", host="127.0.0.1", port=8000, reload=True)