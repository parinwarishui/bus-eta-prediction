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
├── runner.py             # Main FastAPI entry point (routes & lifecycle manager)
├── services.py           # Core logic: fetches API data, runs worker thread, calculates ETA
├── stop_access.py        # Helper classes to manage route configurations and objects
├── stop_lists.py         # Static dictionaries defining stop coordinates and sequences
├── templates/            # HTML templates for the frontend
│   ├── dashboard.html
│   └── admin.html
├── .env                  # Environment variables (API Key)
├── all_etas.json         # Auto-generated cache file containing live ETA data
├── bus_flags.json        # Auto-generated file storing manual admin flags
├── requirements.txt      # Python dependencies
└── README.md             # Project documentation
```

---

## File Overview

| File | Purpose |
|------|----------|
| **`runner.py`** | The main application file. It sets up the FastAPI server, defines URL endpoints, and manages the startup/shutdown lifecycle of the background worker.|
| **`services.py`** | The engine room. It connects to the official Phuket SmartBus API, cleans the data (Pandas), calculates travel times, and updates the JSON cache. |
| **`stop_access.py`** | A utility module that maps route "slugs" (URLs) to internal configuration objects. |
| **`all_etas.json`** | A local JSON cache updated every 60 seconds. The API reads from this file to ensure fast response times without hammering the external API. |
| **`stop_lists.py`** | Contains large dictionaries defining the exact latitude, longitude, and sequence of every bus stop. |
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

### `/admin`

Internal panel to manually flag routes (e.g., "Traffic Jam", "Broken Bus").

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
   "data":{
      "Airport -> Rawai":{
         "route":"Airport -> Rawai",
         "updated_at":"2025-11-26T14:08:10.237950",
         "manual_status":null,
         "stops":{
            "Phuket Airport":{
               "no":42,
               "index":3,
               "stop_name_eng":"Phuket Airport",
               "stop_name_th":"สนามบิน ภูเก็ต",
               "lat":8.10846,
               "lon":98.30655,
               "licence":"Scheduled",
               "eta_min":22,
               "eta_time":"2025-11-26T14:30:10.012254",
               "status":"Scheduled"
            },
         }
      },
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
   "route":"Airport -> Rawai",
   "updated_at":"2025-11-26T14:12:15.645828",
   "manual_status":null,
   "stops":{
      "Phuket Airport":{
         "no":42,
         "index":3,
         "stop_name_eng":"Phuket Airport",
         "stop_name_th":"สนามบิน ภูเก็ต",
         "lat":8.10846,
         "lon":98.30655,
         "licence":"Scheduled",
         "eta_min":18,
         "eta_time":"2025-11-26T14:30:15.456232",
         "status":"Scheduled"
      },
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
   "route_slug":"airport-rawai",
   "stop_no":42,
   "stop_info":{
      "no":42,
      "direction":"Bus to Rawai",
      "index":3,
      "lat":8.10846,
      "lon":98.30655,
      "stop_name_eng":"Phuket Airport",
      "stop_name_th":"สนามบิน ภูเก็ต"
   },
   "live_eta":{
      "no":42,
      "index":3,
      "stop_name_eng":"Phuket Airport",
      "stop_name_th":"สนามบิน ภูเก็ต",
      "lat":8.10846,
      "lon":98.30655,
      "licence":"Scheduled",
      "eta_min":17,
      "eta_time":"2025-11-26T14:30:16.731511",
      "status":"Scheduled"
   }
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

You can measure ETA prediction accuracy by comparing:
- Predicted ETA time (`eta_time`)
- Actual arrival time (logged when bus reaches stop)
