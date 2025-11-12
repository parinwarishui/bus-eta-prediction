from fastapi import FastAPI
import json

app = FastAPI()

@app.get("/api/eta/all")
async def get_all_etas():
    # open the json file if exists
    try:
        with open("all_etas.json", "r") as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        return {"error": "ETA data not yet generated. Please wait."}
    except Exception as e:
        return {"error": f"An error occurred: {e}"}
