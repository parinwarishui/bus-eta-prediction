# Phuket SmartBus ETA API

This project provides a **FastAPI-based system** that serves real-time **Bus ETA (Estimated Time of Arrival)** data for Phuket SmartBus routes.

It includes:
1. A **REST API** serving JSON data for mobile apps or third-party integrations.
2. A **Web Dashboard** for visualizing bus locations and ETAs.
3. An **Admin Panel** for manually flagging delays or issues on specific routes.

The system features an integrated background worker that automatically fetches vehicle positions and recalculates ETAs every 60 seconds.

---

## Project Structure

```text
bus_eta_prediction/
│
├── runner.py                     # Main FastAPI entry point (routes & lifecycle manager)
├── services.py                   # Core logic: fetches API data, runs worker thread, calculates ETA
├── stop_access.py                # Helper classes to manage route configurations and objects
├── templates/                    # HTML templates for the frontend
│   ├── dashboard.html            # page for public view to get ETAs of each bus stop
│   └── admin.html                # admin page for bus / stop / route flagging
├── .env                          # Environment variables (API Key)
├── all_etas.json                 # Auto-generated cache file containing live ETA data
├── bus_flags.json                # Auto-generated file storing manual admin flags
├── accuracy_check.py             # File to check ETA accuracy over time for accuracy graph
├── eta_accuracy_archive.csv      # File which stores completed bus / stop pairs for ETA grpah plotting
├── eta_accuracy_by_stop.csv      # File which stores intermediate bus / stop pairs currently in ETA checking
├── requirements.txt              # Python dependencies
└── README.md                     # Project documentation
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

### Option 1: Development Mode (with live auto-refresh)
```bash
uvicorn api:app --reload
```
or
```bash
python runner.py
```

### Option 2: Production Mode
```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

---

## Web Interface

### `/dashboard`

Public-facing dashboard. Select a route and stop to see live ETAs.
Dashboard can be keyed for specific routes / bus stops dynamically. e.g. /dashboard/airport-rawai/42

### `/admin`

Internal panel to manually flag routes (e.g., "Traffic Jam", "Broken Bus") and analytics of ETA prediction accuracy.
Admin page can be keyed for specific page dynamically, e.g. /admin/bus

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

---

## Testing the API

You can test your API endpoints in any of these ways:
- **Browser:** open `http://localhost:8000/docs` for the built-in Swagger UI  
- **Command line:**  
  ```bash
  curl http://localhost:8000/api
  ```
- **Postman / Insomnia:** use as a normal REST endpoint

---

## Evaluating ETA Accuracy

The graph in the "Accuracy" tab of the admin page displays a plot of minutes of difference between ETAs and actual travel time of buses to different bus stops.