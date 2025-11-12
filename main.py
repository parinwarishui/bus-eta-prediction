'''
FILES:
1) load_files.py : helper functions to load route coordinates, fetch bus data, and store in history
2) tweak_bus_data.py : filter buses to selected route, map each bus to index of the chosen route
3) eta_calculation.py : calculate ETA from known bus index, stop index, and select route + compile list of upcoming buses

'''

import os
from dotenv import load_dotenv
from load_files import get_bus_data, collect_bus_history
from tweak_bus_data import filter_bus, map_index_df
from eta_calculation import get_upcoming_buses
from pprint import pprint
from stop_access import bus_stop_list

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

    #combined_df = combined_df.replace({pd.NA: None, np.nan: None})

    result = {
        "route": route,
        "stop": stop_name,
        "buses": combined_df.to_dict(orient="records")
    }

    # Convert DataFrame to JSON string
    combined_json_str = combined_df.to_json(orient="records")  # list of dicts

    #return combined_df
    return combined_json_str

pprint(main(API_URL, API_KEY, "Dragon Line", "Dibuk Road"))