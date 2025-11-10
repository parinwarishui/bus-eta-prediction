import streamlit as st
import os
import pandas as pd
from stop_access import line_options, direction_map
from main import main
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
import json

# ==== CONSTANTS ====
load_dotenv()
API_KEY = os.getenv('API_KEY')
API_URL = "https://smartbus-pk-api.phuket.cloud/api/bus-news-2/"
count = st_autorefresh(interval = 30*1000, key = "refresh")

# ==== CONSTANTS ====

st.title("Phuket SmartBus Tracker")

st.write(f"Date refreshed: {datetime.now().strftime('%H:%M:%S')} (refresh #{count})")

# ==== INIT SESSION STATE VARIABLES ====

if "selected_line" not in st.session_state:
    st.session_state.selected_line = None
if "selected_stop" not in st.session_state:
    st.session_state.selected_stop = None
if "result_df" not in st.session_state:
    st.session_state.result_df = None
if "bus_history" not in st.session_state:
    st.session_state.bus_history = pd.DataFrame(columns=['licence', 'lon', 'lat', 'spd', 'route_direction', 'timestamp'])

# ==== DROPDOWN BOX CHOOSING BUS ROUTES ====

selected_line = st.selectbox("Select Bus Line", line_options)

if selected_line != st.session_state.selected_line and st.session_state.selected_line is not None:
    st.session_state.selected_line = selected_line
    st.session_state.selected_stop = None
    st.session_state.result_df = None
    st.rerun()
elif st.session_state.selected_line is None:
    st.session_state.selected_line = selected_line

# if selected_line is valid and selected
if selected_line in direction_map:
    selected_direction = direction_map[selected_line]["line"]
    selected_geojson = direction_map[selected_line]["geojson_path"]
    selected_schedule = direction_map[selected_line]["schedule_path"]
    selected_speeds = direction_map[selected_line]["speeds_path"]

    # ==== DROPDOWN BOX CHOOSING BUS STOP ====
    stop_list = direction_map[selected_line]["stop_list"]
    stop_options = [stop['stop_name_eng'] for stop in stop_list]
    
    # initialize session state for selected_stop if not set
    if st.session_state.selected_stop not in stop_options:
        st.session_state.selected_stop = stop_options[0]
    
    # Dropdown for stops
    selected_stop_name = st.selectbox(
        "Select Bus Stop",
        stop_options,
        index=stop_options.index(st.session_state.selected_stop),
        key="selected_stop_dropdown"
    )
    st.session_state.selected_stop = selected_stop_name


    if st.session_state.selected_stop:
        selected_stop = st.session_state.selected_stop

        with st.spinner("Fetching bus data..."):
            try:
                # get_stop_data returns JSON string, need to parse it
                result_json = main(
                    API_URL, 
                    API_KEY,
                    st.session_state.selected_stop,  # Pass stop NAME not index
                    selected_line
                )
                
                # Parse JSON to DataFrame
                result_data = json.loads(result_json)
                st.session_state.result_df = pd.DataFrame(result_data)
                
                # Display the dataframe
                if not st.session_state.result_df.empty:
                    # Format for better display
                    display_df = st.session_state.result_df.copy()
                    
                    # Select relevant columns for display
                    display_columns = ['licence','lon', 'lat', 'eta_min', 'dist_km', 'spd']
                    display_df = display_df[display_columns]
                    
                    st.dataframe(display_df, width='stretch')
                    
                    # Show additional info
                    st.info(f"Next bus arrives in **{display_df['eta_min'].iloc[0]}** minutes")
                else:
                    st.warning("No buses found for this route at the moment.")
                    
            except Exception as e:
                st.error(f"Error fetching bus data: {e}")
                st.exception(e)  # Shows full traceback for debugging
