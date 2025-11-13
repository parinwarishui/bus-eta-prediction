# 🚌 Phuket SmartBus ETA API

This project provides a **FastAPI-based REST API** that serves real-time **Bus ETA (Estimated Time of Arrival)** data for multiple routes.  
The API automatically updates every 60 seconds via an integrated background worker and serves up-to-date results through HTTP endpoints.

---

## 📂 Project Structure

```
bus_eta_prediction/
│
├── api.py                # Main FastAPI app (runs both API & background worker)
├── load_files.py         # Functions to fetch and preprocess live bus data
├── tweak_bus_data.py     # Functions to clean, filter, and map bus data to indices
├── eta_calculation.py    # Core ETA calculation logic
├── stop_access.py        # Stores route definitions, direction maps, and stop lists
├── .env                  # Environment variables (contains API_KEY)
├── all_etas.json         # Auto-generated output file containing all ETA data
├── requirements.txt      # Python dependencies
└── README.md             # You are here
```

---

## ⚙️ File Overview

| File | Purpose |
|------|----------|
| **`api.py`** | Main entry point. Runs a FastAPI server and background worker that recalculates all ETAs every 60 seconds using the FastAPI `lifespan` event system. |
| **`load_files.py`** | Connects to the Phuket SmartBus API, fetches live bus data, and structures it into a DataFrame. |
| **`tweak_bus_data.py`** | Cleans and transforms raw data, filters by route, and maps bus positions to index order along the route. |
| **`eta_calculation.py`** | Core ETA logic: computes bus ETAs for all stops on each route. |
| **`stop_access.py`** | Contains `line_options`, `direction_map`, and `bus_stop_list` — defines all known routes and stops. |
| **`all_etas.json`** | Output file that stores the most recent ETA data for all routes. Automatically updated by the worker every 60 seconds. |
| **`.env`** | (Not included) Please create your own .env file for `API_KEY` variable, which stores the API key.|

---

## 🧰 Requirements

- **Python 3.9+**
- Internet connection (for live data)
- Environment variable `API_KEY` from Phuket SmartBus API

---

## 📦 Installation

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

## 🚀 Running the API

### Option 1: Development Mode (with live auto-refresh)
```bash
uvicorn api:app --reload
```

### Option 2: Production Mode
```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

When you start the API, you’ll see:
```
🚀 Background worker started.
--- Worker run START (2025-11-13 10:33:00) ---
worker: Fetching live bus data...
worker: Successfully updated all_etas.json
--- Worker run END (2025-11-13 10:33:03) ---
```

---

## 🌐 API Endpoints

### **GET** `/`

Returns the latest ETA data for all routes.

**Example Request:**
```
GET http://localhost:8000/
```

**Example Response:**
```json
{
  "Airport -> Rawai": {
    "route": "Airport -> Rawai",
    "updated_at": "2025-11-13 10:34:00",
    "stops": {
      "Big C Kamala": {
        "licence": "10-1147",
        "eta_min": 24,
        "eta_time": "2025-11-13T11:00:00"
      }
    }
  }
}
```

---

## 🔄 How It Works

1. When the API starts:
   - The background worker (`update_worker_loop`) begins running every 60 seconds.
   - Each run calls `calculate_all_etas()`.

2. `calculate_all_etas()`:
   - Fetches live data via `load_files.get_bus_data()`.
   - Processes data for each route defined in `stop_access.line_options`.
   - Calculates ETAs for every stop using `eta_calculation.get_upcoming_buses()`.
   - Saves everything to `all_etas.json`.

3. The API endpoint `/api/eta/all` simply reads and serves `all_etas.json`.

---

## 🧪 Testing the API

You can test your API endpoints in any of these ways:
- **Browser:** open `http://localhost:8000/docs` for the built-in Swagger UI  
- **Command line:**  
  ```bash
  curl http://localhost:8000/api
  ```
- **Postman / Insomnia:** use as a normal REST endpoint

---

## 🧠 Evaluating ETA Accuracy

You can measure ETA prediction accuracy by comparing:
- Predicted ETA time (`eta_time`)
- Actual arrival time (logged when bus reaches stop)

---

## 🪶 Example `requirements.txt`

```txt
fastapi
uvicorn
pandas
numpy
requests
python-dotenv
```

---

## 🧩 Future Improvements
- Add `/api/eta/{route}` to return a single route’s ETA
- Implement `/api/eval/accuracy` to visualize ETA performance
- Log `arrival_events` for continuous model evaluation
- Cache API responses for efficiency

---

## 📄 License
MIT License © 2025 [Your Name]
