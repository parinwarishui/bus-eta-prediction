import os
import json
from dotenv import load_dotenv
from pprint import pprint
from services import get_bus_data, collect_bus_history, filter_bus, map_index_df, get_upcoming_buses

'''==== CONSTANTS ===='''
load_dotenv()
API_KEY = os.getenv('API_KEY')
API_URL = "https://smartbus-pk-api.phuket.cloud/api/bus-news-2/"

'''=== RUN ==='''
def main(api_url, api_key, route, stop_name):
    bus_df = get_bus_data(api_url, api_key)
    bus_df = collect_bus_history(bus_df)

    filtered_df = filter_bus(bus_df, route)
    mapped_df = map_index_df(filtered_df, route)
    print(filtered_df)
    print(mapped_df)
    combined_df = get_upcoming_buses(mapped_df, stop_name, route)

    # Convert DataFrame to JSON string
    combined_json_str = combined_df.to_json(orient="records")  # list of dicts

    return combined_json_str

if __name__ == "__main__":
    pprint(main(API_URL, API_KEY, "Dragon Line", "Dibuk Road"))