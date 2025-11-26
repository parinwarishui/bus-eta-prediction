# Phuket SmartBus ETA API

This project provides a **FastAPI-based REST API** that serves real-time **Bus ETA (Estimated Time of Arrival)** data for multiple routes.  
The API automatically updates every 60 seconds via an integrated background worker and serves up-to-date results through HTTP endpoints.

---

## Project Structure

```
bus_eta_prediction/
│
├── api.py                # Main FastAPI app (runs both API & background worker)
├── services.py           # Functions to fetch data and calculate ETA
├── stop_access.py        # Stores route definitions, direction maps, and stop lists
├── .env                  # Environment variables (contains API_KEY)
├── all_etas.json         # Auto-generated output file containing all ETA data
├── requirements.txt      # Python dependencies
└── README.md             # You are here
```

---

## File Overview

| File | Purpose |
|------|----------|
| **`api.py`** | Main entry point. Runs a FastAPI server and background worker that recalculates all ETAs every 60 seconds using the FastAPI `lifespan` event system. |
| **`services.py`** | Connects to the Phuket SmartBus API, fetches live bus data, and structures it into a DataFrame. Then calculates the ETA of buses for each stop in all the lines. |
| **`stop_access.py`** | Contains `line_options`, `direction_map`, and `bus_stop_list` — defines all known routes and stops. |
| **`all_etas.json`** | Output file that stores the most recent ETA data for all routes. Automatically updated by the worker every 60 seconds. |
| **`.env`** | (Not included) Please create your own .env file for `API_KEY` variable, which stores the API key.|

---

## Requirements

- **Python 3.9+**
- Internet connection (for live data)
- Environment variable `API_KEY` from Phuket SmartBus API

---

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/bus_eta_prediction.git
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

### Option 2: Production Mode
```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

---

## API Endpoints

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
