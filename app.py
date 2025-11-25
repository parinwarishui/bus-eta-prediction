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

if selected_line in direction_map:
    # UPDATED: Access attributes via dot notation
    route_config = direction_map[selected_line]
    
    stop_list = route_config.stop_list
    stop_options = [stop['stop_name_eng'] for stop in stop_list]
    
    if st.session_state.selected_stop not in stop_options:
        st.session_state.selected_stop = stop_options[0]
    
    selected_stop_name = st.selectbox(
        "Select Bus Stop",
        stop_options,
        index=stop_options.index(st.session_state.selected_stop),
        key="selected_stop_dropdown"
    )
    st.session_state.selected_stop = selected_stop_name

    if st.session_state.selected_stop:
        with st.spinner("Fetching bus data..."):
            try:
                result_json = main(
                    API_URL, 
                    API_KEY,
                    selected_line,
                    st.session_state.selected_stop
                )
                
                result_data = json.loads(result_json)
                st.session_state.result_df = pd.DataFrame(result_data)
                
                if not st.session_state.result_df.empty:
                    display_df = st.session_state.result_df.copy()
                    display_columns = ['licence','lon', 'lat', 'eta_min', 'dist_km', 'spd']
                    display_columns = [col for col in display_columns if col in display_df.columns]
                    display_df = display_df[display_columns]
                    
                    st.dataframe(display_df, width='content')
                    
                    if 'eta_min' in display_df.columns:
                        st.info(f"Next bus arrives in **{display_df['eta_min'].iloc[0]}** minutes")
                else:
                    st.warning("No buses found for this route at the moment.")
                    
            except Exception as e:
                st.error(f"Error fetching bus data: {e}")