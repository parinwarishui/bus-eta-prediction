# Phuket Smart Bus ETA API

This project provides a **FastAPI-based system** that serves real-time **Bus ETA (Estimated Time of Arrival)** data for Phuket SmartBus routes.

It includes:
1. A **REST API** serving JSON data for mobile apps or third-party integrations.
2. A **Web Dashboard** for visualizing bus locations and ETAs.
3. An **Admin Panel** for manually flagging delays or issues on specific routes, and adding new bus routes / stops.

The system features an integrated background worker that automatically fetches vehicle positions and recalculates ETAs every 60 seconds.

---

## Project Structure

```text
bus_eta_prediction/
│
├── runner.py                     # Main FastAPI entry point (App lifecycle, API routes & frontend mounting)
├── services.py                   # Core Engine: Data fetching, threading, ETA calculation logic
├── admin_logic.py                # Admin Backend: Handles file uploads, GeoJSON processing, and route configuration
├── stop_access.py                # Helper: Loads and parses route configurations from JSON
├── accuracy_check.py             # Background process: Validates ETA predictions against actual arrival times
│
├── routes_data.json              # Central Database: Stores all route configurations and stop data
├── all_etas.json                 # Live Cache: Auto-generated file containing current ETA predictions
├── bus_flags.json                # Live Cache: Stores manual status flags set by admins
├── bus_history.csv               # Log: Retains recent bus positions to handle short API outages
│
├── templates/                    # HTML/Jinja2 Frontend
│   ├── dashboard.html            # Public Display: Real-time ETA board for passengers
│   └── admin.html                # Admin Panel: System management interface
│
├── data_routes/                  # Storage: GeoJSON files for route paths
├── data_schedules/               # Storage: CSV files for bus departure schedules
├── data_speeds/                  # Storage: CSV/JSON files for historical speed data
│
├── .env                          # Environment variables (API Key)
├── requirements.txt              # Python dependencies
└── README.md                     # Documentation
```

---

## File Overview

| File | Purpose |
|------|----------|
| **`runner.py`** | The main application file. It sets up the FastAPI server, defines URL endpoints, and manages the startup/shutdown lifecycle of the background worker.|
| **`services.py`** | The engine room. It connects to the official Phuket SmartBus API, cleans the data (Pandas), calculates travel times, and updates the JSON cache. |
| **`accuracy_check.py`** | The file to check ETA accuracy over time, getting data of bus ETAs accuracy compared to time before bus arrives. |
| **`stop_access.py`** | A utility module that maps route "slugs" (URLs) to internal configuration objects. |
| **`all_etas.json`** | A local JSON cache updated every 60 seconds. The API reads from this file to ensure fast response times without hammering the external API. |
| **`.env`** | (Not included) Please create your own .env file for `API_KEY` variable, which stores the API key for the Phuket Smart Bus API.|

---

## Requirements

- **Python 3.9+**
- Internet connection (for live data)
- Environment variable `API_KEY` from Phuket SmartBus API in .env file

---

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/parinwarishui/bus_eta_prediction.git
   cd bus_eta_prediction
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate   # On macOS/Linux
   venv\Scripts\activate      # On Windows
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables:**
   Create a `.env` file in the project root:
   ```bash
   API_KEY=your_phuket_smartbus_api_key_here
   ```

---

## Running the API

### Development Mode (with live auto-refresh)
```bash
uvicorn api:app --reload
```
The API will be live at http://127.0.0.1:8000.

---

## Web Interface

### `/dashboard`

Public-facing dashboard. Select a route and stop to see live ETAs.
Dashboard can be keyed for specific routes / bus stops dynamically. e.g. /dashboard/airport-rawai/42

### `/admin`

Internal admin page for various functions.
- View Routes
- Add New Route
- Flag Bus / Stop / Route (for delays / inactive / closing)
- Analytics (ETA accuracy)

### `/docs`

Access Swagger UI to test API endpoints manually.

## JSON API Endpoints

### **GET** `/`

Returns the latest ETA data for all routes.

**Example Request:**
```
GET http://localhost:8000/
```

**Example Response:**
```json
{
  "data": {
    "Airport -> Rawai": {
      "route": "Airport -> Rawai",
      "updated_at": "2025-12-02T14:46:52.764704",
      "route_status": "active",   // Options: "active", "suspended"
      "route_message": null,      // Custom message if suspended
      "stops": {
        "Phuket Airport": {
          "no": 42,
          "index": 3,
          "stop_name_eng": "Phuket Airport",
          "stop_name_th": "สนามบิน ภูเก็ต",
          "lat": 8.10846,
          "lon": 98.30655,
          "stop_status": "open",  // Options: "open", "closed"
          "stop_message": null,
          "upcoming": [
            {
              "licence": "10-1204",
              "eta_min": 0,
              "eta_time": "2025-12-02T14:46:52.423626",
              "status": "Active",
              "message": "Normal Operation",
              "type": "active"
            },
            {
              "licence": "Scheduled",
              "eta_min": 13,
              "eta_time": "2025-12-02T14:59:52.423626",
              "status": "Scheduled",
              "message": "Normal Operation",
              "type": "scheduled"
            },
            {
              "licence": "Scheduled",
              "eta_min": 43,
              "eta_time": "2025-12-02T15:29:52.423626",
              "status": "Scheduled",
              "message": "Normal Operation",
              "type": "scheduled"
            }
          ]
        }
        // ... more stops ...
      }
    },
    "Rawai -> Airport": {
      // ... next route object ...
    }
  }
}
```

### **GET** `/{route_name}`

Returns the latest ETA data for a specific route.

**Example Request:**
```
GET http://localhost:8000/airport-rawai
```

**Example Response:**
```json
{
  "route": "Airport -> Rawai",
  "updated_at": "2025-12-02T14:46:52.764704",
  "route_status": "active",
  "route_message": null,
  "stops": {
    "Phuket Airport": {
      "no": 42,
      "index": 3,
      "stop_name_eng": "Phuket Airport",
      "stop_name_th": "สนามบิน ภูเก็ต",
      "lat": 8.10846,
      "lon": 98.30655,
      "stop_status": "open",
      "stop_message": null,
      "upcoming": [
        {
          "licence": "10-1204",
          "eta_min": 0,
          "eta_time": "2025-12-02T14:46:52.423626",
          "status": "Active",
          "message": "Normal Operation",
          "type": "active"
        },
        {
          "licence": "Scheduled",
          "eta_min": 13,
          "eta_time": "2025-12-02T14:59:52.423626",
          "status": "Scheduled",
          "message": "Normal Operation",
          "type": "scheduled"
        },
        {
          "licence": "Scheduled",
          "eta_min": 43,
          "eta_time": "2025-12-02T15:29:52.423626",
          "status": "Scheduled",
          "message": "Normal Operation",
          "type": "scheduled"
        }
      ]
    }
    // ... other stops on this route ...
  }
}
```

### **GET** `/{route_name}/{stop_no}`

Returns the latest ETA data for a specific stop in a specific route.

**Example Request:**
```
GET http://localhost:8000/airport-rawai/40
```

**Example Response:**
```json
{
  "no": 43,
  "index": 2368,
  "stop_name_eng": "Thalang Public Health Office",
  "stop_name_th": "สำนักงานสาธารณสุข ถลาง",
  "lat": 8.034014,
  "lon": 98.333571,
  "stop_status": "open",
  "stop_message": null,
  "upcoming": [
    {
      "licence": "10-1148",
      "eta_min": 4,
      "eta_time": "2025-12-02T14:51:54.209948",
      "status": "Active",
      "message": "Normal Operation",
      "type": "active"
    },
    {
      "licence": "Scheduled",
      "eta_min": 29,
      "eta_time": "2025-12-02T15:16:54.209948",
      "status": "Scheduled",
      "message": "Normal Operation",
      "type": "scheduled"
    },
    {
      "licence": "Scheduled",
      "eta_min": 59,
      "eta_time": "2025-12-02T15:46:54.209948",
      "status": "Scheduled",
      "message": "Normal Operation",
      "type": "scheduled"
    }
  ]
}
```


## Dashboard Page Guide

### Viewing ETA

- Please select a route first then select stop.
- View the 3 upcoming buses ETA

### Dynamic Links

- You can key in route and stop no. to directly get ETA of that specific route & stop.
- e.g. http://127.0.0.1:8000/dashboard/bus-2-bus-1-patong/76 
  - returns ETA of **"Bus 2 -> Bus 1 -> Patong"** route at **stop no. 76 "Andamanda Phuket Waterpark"**
- keying in a route that does not exist will return error message
- keying in a stop no. that is not part of the route will return error message.


## Admin Page Guide

Access at:
➡️ http://127.0.0.1:8000/admin

### 1. View Routes
- Select a route
- Preview of the route and its stops on the map.
- List of Stops and its data (No. / Eng / Thai / Coordinates / Index (on the 5m points))
- Allow admin to add new stops (with the data mentioned above, Index is auto-mapped) or remove stops.

### 2. Editor
- Add new bus route
- Fill in **Route Name, Line, Buffer, Direction** (according to the message in Phuket Smart Bus API).
- Attach **GeoJSON File** of the route (make sure ALL coordinates are in order from top to bottom) format as follows.

```json
{
"type": "FeatureCollection",
"name": "airport_rawai",
"crs": { "type": "name", "properties": { "name": "urn:ogc:def:crs:OGC:1.3:CRS84" } },
"features": [
{ "type": "Feature", "properties": { "Id": 0, "lat": 867713.494 }, "geometry": { "type": "Point", "coordinates": [ 98.293235119708498, 7.849391077160541 ] } },
{ "type": "Feature", "properties": { "Id": 0, "lat": 867712.459 }, "geometry": { "type": "Point", "coordinates": [ 98.293279455503139, 7.8493817939272 ] } },
// more points ...
]
}

```

- Add **Schedule CSV File** (time bus departs from start) in the structure below.

| [Starting Point]    |
| -------- |
| 08:00  |
| 09:00 |
| 10:00    |
and so on...

- Add **Speeds CSV File** (Optional) in structure below.

| index | km_interval | avg_speed | count | km_label |
| -------- | -------- | -------- | -------- | -------- |
| 0 | 0 | 23 | 3546 | KM 0-1 |
| 1 | 1 | 25 | 2726 | KM 1-2 |
and so on...

### 3. Status

- **Route Status:** choose a route and set Active / Suspend.
- **Stop Status:** choose a route → choose a stop → set Open / Close.
- **Bus Status:** enter plate/license → set Active / Delayed / Inactive + message + optional auto-expire duration (mins).

### 4. Analytics
- View historical stats of **ETA accuracy**.
- Graph is between time before actual arrival (min), and ETA error (min) with error bar of +- SD
- Graph explains how accurate ETA is, the further the bus is away from the stop.

---

## Evaluating ETA Accuracy

Along side the main API, you can run a separate process in accuracy_check.py

```bash
   python accuracy_check.py
```

This will start testing the accuracy of bus / stops ETA in real-time and add data to the archive which will be used in the accuracy graph.
The graph in the "Accuracy" tab of the admin page displays a plot of minutes of difference between ETAs and actual travel time of buses to different bus stops.

---

## Future Improvements

### Admin Login System

Add authentication for admin logins to access the admin page.

### Bulk Stop Upload

Upload a CSV file of stops in bulk when adding a new route.

### Manual Input of Speed / CSV

Allow manual input of speeds and scheduled departures.