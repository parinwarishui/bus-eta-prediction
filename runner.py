import uvicorn
import services
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Path, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from stop_access import direction_map
from pydantic import BaseModel
from typing import Optional

ROUTE_SLUGS = {
    "airport-rawai": "Airport -> Rawai",
    "rawai-airport": "Rawai -> Airport",
    "terminal-patong": "Bus 2 -> Bus 1 -> Patong",
    "patong-terminal": "Patong -> Bus 1 -> Bus 2",
    "dragon-line": "Dragon Line"
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[LIFECYCLE] Starting background worker...")
    services.start_worker()
    yield
    print("[LIFECYCLE] Stopping background worker...")
    services.stop_worker()

app = FastAPI(title="Phuket Bus ETA API", lifespan=lifespan)
templates = Jinja2Templates(directory="templates") 

def resolve_route_key(route_identifier: str):
    if route_identifier in ROUTE_SLUGS: return ROUTE_SLUGS[route_identifier]
    if route_identifier in direction_map: return direction_map
    return None

def success_response(data):
    return JSONResponse(content=data, media_type="application/json; charset=utf-8")

class StatusRequest(BaseModel):
    scope: str
    identifier: str
    status: str
    message: Optional[str] = None
    duration: Optional[int] = None

# ==========================
# 1. ADMIN API (Must come BEFORE generic admin routes)
# ==========================

@app.get("/admin/fleet")
async def get_fleet():
    fleet_data = services.get_fleet_data_for_admin()
    return success_response({"fleet": fleet_data})

@app.get("/admin/system-status")
async def get_system_status():
    status_data = services.get_all_system_statuses()
    return success_response({"status": status_data})

@app.get("/admin/api/accuracy-stats")
async def get_accuracy_stats():
    stats = services.get_live_accuracy_stats()
    return success_response({"data": stats})

@app.get("/admin/stops/{route_slug}")
async def get_stops_for_route(route_slug: str):
    real_name = resolve_route_key(route_slug)
    if not real_name: return {"stops": []}
    route_config = direction_map.get(real_name)
    if not route_config: return {"stops": []}
    stops = []
    for s in route_config.stop_list.values():
        stops.append({"id": s['no'], "name": s['stop_name_eng']})
    stops.sort(key=lambda x: x['id'])
    return success_response({"stops": stops})

@app.post("/admin/set-status")
async def set_status(payload: StatusRequest):
    services.set_status_flag(
        payload.scope, payload.identifier, payload.status, 
        payload.message, payload.duration
    )
    return {"status": "success", "scope": payload.scope, "id": payload.identifier}

# ==========================
# 2. FRONTEND PAGES
# ==========================

# Admin Dashboard (Handles /admin, /admin/bus, /admin/route, etc.)
@app.get("/admin", response_class=HTMLResponse)
@app.get("/admin/{view_type}", response_class=HTMLResponse)
async def admin_panel(request: Request, view_type: str = "bus"):
    # Safety check: if view_type isn't a valid tab, default to bus
    if view_type not in ["bus", "route", "stop", "accuracy"]:
        view_type = "bus"
        
    return templates.TemplateResponse("admin.html", {
        "request": request, 
        "routes": ROUTE_SLUGS,
        "initial_view": view_type 
    })

# Public Dashboard
@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/dashboard/{route_slug}", response_class=HTMLResponse)
@app.get("/dashboard/{route_slug}/{stop_no}", response_class=HTMLResponse)
async def dashboard(request: Request, route_slug: Optional[str] = None, stop_no: Optional[int] = None):
    data = services.load_data()
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "data": data, 
        "routes": ROUTE_SLUGS,
        "initial_route_slug": route_slug, 
        "initial_stop_no": stop_no
    })

# ==========================
# 3. PUBLIC DATA API
# ==========================

@app.get("/")
async def get_all_data():
    data = services.load_data()
    return success_response({"data": data})

@app.get("/{route_identifier}/{stop_no}") 
async def get_stop_data(route_identifier: str, stop_no: int):
    real_route_key = resolve_route_key(route_identifier)
    if not real_route_key: raise HTTPException(status_code=404, detail="Route not found")
    data = services.load_data()
    if not data or real_route_key not in data: return success_response({"status": "Initializing", "upcoming": []})
    
    route_data = data[real_route_key]
    stops_data = route_data.get("stops", {})
    target_stop_name = next((name for name, info in stops_data.items() if str(info.get('no')) == str(stop_no)), None)
            
    if not target_stop_name: raise HTTPException(status_code=404, detail=f"Stop {stop_no} not found")
    return success_response(stops_data[target_stop_name])

@app.get("/{route_identifier}")
async def get_route_data(route_identifier: str):
    real_route_key = resolve_route_key(route_identifier)
    data = services.load_data()
    if not data or real_route_key not in data: raise HTTPException(status_code=404, detail="No data")
    return success_response(data[real_route_key])

if __name__ == "__main__":
    uvicorn.run("runner:app", host="127.0.0.1", port=8000, reload=True)