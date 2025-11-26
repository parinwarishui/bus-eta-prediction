import uvicorn
import services
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Path, Request, Form
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from stop_access import direction_map, line_options 

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
    print("[LIFECYCLE] Starting background worker...")
    services.start_worker()
    yield
    print("[LIFECYCLE] Stopping background worker...")
    services.stop_worker()

# === FASTAPI SETUP ===
app = FastAPI(title="Phuket Bus ETA API", lifespan=lifespan)
templates = Jinja2Templates(directory="templates") # Looks for HTML files in 'templates' folder

# === API HELPERS ===
def resolve_route_key(route_identifier: str):
    if route_identifier in ROUTE_SLUGS: return ROUTE_SLUGS[route_identifier]
    if route_identifier in direction_map: return direction_map
    return None

def success_response(data):
    return JSONResponse(content=data, media_type="application/json; charset=utf-8")

# === FRONTEND ROUTES ===

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Public Dashboard View"""
    data = services.load_data()
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "data": data, 
        "routes": ROUTE_SLUGS
    })

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    """Admin Control Panel"""
    data = services.load_data()
    return templates.TemplateResponse("admin.html", {
        "request": request, 
        "routes": line_options,
        "current_data": data
    })

@app.post("/admin/flag")
async def set_flag(
    route: str = Form(...),
    status: str = Form(...),
    is_delayed: bool = Form(False)
):
    """API to Set/Clear Flags"""
    if route not in line_options:
        raise HTTPException(status_code=400, detail="Invalid Route")
    
    message = "CLEAR" if status == "" else status
    services.set_route_status(route, message, is_delayed)
    
    return {"status": "success", "route": route, "message": message}

# === API ENDPOINTS (EXISTING) ===

@app.get("/")
async def get_all_data():
    data = services.load_data()
    return success_response({"data": data})

@app.get("/{route_identifier}")
async def get_route_data(route_identifier: str = Path(...)):
    real_route_key = resolve_route_key(route_identifier)
    data = services.load_data()
    if not data or real_route_key not in data:
        raise HTTPException(status_code=404, detail="No data")
    return success_response(data[real_route_key])


@app.get("/{route_identifier}/{stop_no}")
async def get_stop_data(route_identifier: str, stop_no: int):
    real_route_key = resolve_route_key(route_identifier)
    if not real_route_key:
        raise HTTPException(status_code=404, detail="Route not found")

    if real_route_key not in direction_map:
        raise HTTPException(status_code=500, detail=f"Server Error: Route configuration missing.")

    route_config = direction_map[real_route_key]
 
    target_stop = next((s for s in route_config.stop_list.values() if s['no'] == stop_no), None)
            
    if not target_stop:
        raise HTTPException(status_code=404, detail=f"Stop {stop_no} not found")
    
    stop_name_eng = target_stop['stop_name_eng']
    data = services.load_data()
    
    if not data or real_route_key not in data:
         raise HTTPException(status_code=503, detail="Data initializing")

    stops_data = data[real_route_key].get("stops", {})
    
    # Return the full merged data from services.py
    if stop_name_eng not in stops_data:
        # Fallback if service hasn't updated yet
        return success_response({
            "route_slug": route_identifier,
            "stop_no": stop_no,
            "stop_info": target_stop,
            "live_eta": {"status": "Loading..."}
        })

    return success_response({
        "route_slug": route_identifier,
        "stop_no": stop_no,
        "stop_info": target_stop,
        "live_eta": stops_data[stop_name_eng]
    })


if __name__ == "__main__":
    uvicorn.run("runner:app", host="127.0.0.1", port=8000, reload=True)