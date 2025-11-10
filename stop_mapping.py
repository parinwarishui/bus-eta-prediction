import os
import pandas as pd
import numpy as np
import json
import requests
from math import cos, radians
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
from pprint import pprint

direction_map = {
    "Airport -> Rawai": {
                            "line":"Phuket Airport to Rawai",
                            "buffer":"Rawai",
                            "direction": "Bus to Rawai",
                            "geojson_path":"airport_rawai_ordered.geojson", 
                            "schedule_path":"airport_rawai_bus_schedule.csv",
                            "speeds_path":"airport_rawai_speeds.csv"
                        },
    "Rawai -> Airport": {
                            "line":"Rawai to Phuket Airport", 
                            "buffer":"Phuket Airport",
                            "direction": "Bus to Airport",
                            "geojson_path":"rawai_airport_ordered.geojson", 
                            "schedule_path":"rawai_airport_bus_schedule.csv", # Placeholder
                            "speeds_path":"rawai_airport_speeds.csv" # Placeholder
                        },
    "Bus 2 -> Bus 1": {
                                    "line":"Bus 2 -> Bus 1 -> Patong", 
                                    "buffer":"Patong",
                                    "direction": "Bus to Airport",
                                    "geojson_path":"bus2_bus1_patong_ordered.geojson", 
                                    "schedule_path":"bus2_bus1_patong_bus_schedule.csv", # Placeholder
                                    "speeds_path":"bus2_bus1_patong_speeds.csv" # Placeholder
                                },
    "Bus 2 -> Bus 1 -> Patong": {
                                    "line":"Bus 2 -> Bus 1 -> Patong", 
                                    "buffer":"Patong",
                                    "direction": "Bus to Airport",
                                    "geojson_path":"bus2_bus1_patong_ordered.geojson", 
                                    "schedule_path":"bus2_bus1_patong_bus_schedule.csv", # Placeholder
                                    "speeds_path":"bus2_bus1_patong_speeds.csv" # Placeholder
                                },
    "Patong -> Bus 1 -> Bus 2": {
                                    "line":"Patong -> Bus 1 -> Bus 2", 
                                    "buffer":"Bus 2",
                                    "direction": "Bus to Airport",
                                    "geojson_path": "patong_bus1_bus2_ordered.geojson", 
                                    "schedule_path":"patong_bus1_bus2_bus_schedule.csv", # Placeholder
                                    "speeds_path":"patong_bus1_bus2_speeds.csv" # Placeholder
                                },
    "Dragon Line": {
                        "line":"Dragon Line", 
                        "buffer":"ฺDragon Line",
                        "geojson_path":"dragonline_ordered.geojson", 
                        "schedule_path":"dragonline_bus_schedule.csv", # Placeholder
                        "speeds_path":"dragonline_speeds.csv" # Placeholder
                    } # Placeholder
}

def load_route_coords(route_geojson_path):

    if not os.path.exists(route_geojson_path):
        raise FileNotFoundError(f"GeoJSON not found: {route_geojson_path}")

    with open(route_geojson_path, "r") as f:
        geojson = json.load(f)
    
    coords = [
        (feat["properties"]["order"],
         feat["geometry"]["coordinates"][0],
         feat["geometry"]["coordinates"][1])
        for feat in geojson["features"]
    ]
    
    print(f"Loaded {len(coords)} route coordinates")  # Debug print
    if coords:
        print(f"Sample coords: {coords[:3]}")  # Debug print
    
    return coords

def map_stop(route_coords, stop_lon, stop_lat):
    """
    Map bus stop to nearest route coordinate.
    Returns the order index of the nearest point.
    """
    if not route_coords or stop_lon is None or stop_lat is None:
        print(f"Warning: Invalid input - route_coords: {len(route_coords) if route_coords else 0}, bus_lon: {stop_lon}, bus_lat: {stop_lat}")
        return -1
    
    min_dist = float("inf")
    nearest_index = None
    cos_lat = cos(radians(stop_lat))

    for order, lon, lat in route_coords:
        dx = (lon - stop_lon) * 111320 * cos_lat
        dy = (lat - stop_lat) * 110540
        d2 = dx*dx + dy*dy
        if d2 < min_dist:
            min_dist = d2
            nearest_index = order

    # Distance threshold (50m squared = 2500)
    actual_distance = np.sqrt(min_dist)
    
    return nearest_index

def get_stop_dict(bus_stops_geojson):

    with open(bus_stops_geojson, "r") as f:
        geojson = json.load(f)

    stops = []

    for stop in geojson["features"]:
        stop_dict = {}
        stop_dict["no"] = stop["properties"]["no"]
        stop_dict["stop_name_th"] = stop["properties"]["stop_name_th"]
        stop_dict["stop_name_eng"] = stop["properties"]["stop_name_eng"]
        stop_dict["lat"] = stop["properties"]["lat"]
        stop_dict["lon"] = stop["properties"]["lon"]
        stop_dict["direction"] = stop["properties"]["direction"]
        stops.append(stop_dict)

    return stops




stop_list = get_stop_dict("bus_stop_all.geojson")

route_coords = load_route_coords("data_routes/dragonline_ordered.geojson")

stop_dict_filtered = list(filter(lambda x: "Old Town Bus" in x["direction"], stop_list))

for stop in stop_dict_filtered:
    stop["index"] = map_stop(route_coords, stop["lon"], stop["lat"])

stop_dict_filtered = sorted(stop_dict_filtered, key=lambda stop: stop["index"])

pprint(stop_dict_filtered)





stop_list_bus2_bus1 = []

stop_list_bus1_patong = [{'direction': 'Bus to Patong',
  'index': 1587,
  'lat': 7.884101493,
  'lon': 98.39575082,
  'no': 68,
  'stop_name_eng': 'Phuket Bus Terminal 1',
  'stop_name_th': 'สถานีขนส่งภูเก็ต 1'},
 {'direction': 'Bus to Patong',
  'index': 1886,
  'lat': 7.889961988,
  'lon': 98.39767359,
  'no': 69,
  'stop_name_eng': 'Sanamchai',
  'stop_name_th': 'สนามชัย'},
 {'direction': 'Bus to Patong',
  'index': 2019,
  'lat': 7.890961837,
  'lon': 98.39209012,
  'no': 70,
  'stop_name_eng': 'Satree Phuket School',
  'stop_name_th': 'โรงเรียนสตรีภูเก็ต'},
 {'direction': 'Bus to Patong',
  'index': 2111,
  'lat': 7.892383991,
  'lon': 98.38963431,
  'no': 71,
  'stop_name_eng': 'Phuket Wittayalai School',
  'stop_name_th': 'โรงเรียนภูเก็ตวิทยาลัย'},
 {'direction': 'Bus to Patong',
  'index': 2334,
  'lat': 7.897257446,
  'lon': 98.38400696,
  'no': 72,
  'stop_name_eng': 'Vachira Phuket Hospital',
  'stop_name_th': 'โรงพยาบาลวชิระภูเก็ต'},
 {'direction': 'Bus to Patong',
  'index': 2559,
  'lat': 7.904270508,
  'lon': 98.3776116,
  'no': 73,
  'stop_name_eng': 'Bangkok Hospital Phuket',
  'stop_name_th': 'โรงพยาบาลกรุงเทพภูเก็ต'},
 {'direction': 'Bus to Patong',
  'index': 2715,
  'lat': 7.906829856,
  'lon': 98.37335804,
  'no': 74,
  'stop_name_eng': 'Chillva Market',
  'stop_name_th': 'ตลาดชิลวา'},
 {'direction': 'Bus to Patong',
  'index': 2809,
  'lat': 7.905991202,
  'lon': 98.36921261,
  'no': 75,
  'stop_name_eng': 'Lotus Samkong',
  'stop_name_th': 'โลตัส สามกอง'},
 {'direction': 'Bus to Patong',
  'index': 2935,
  'lat': 7.904688653,
  'lon': 98.36366775,
  'no': 76,
  'stop_name_eng': 'Andamanda Phuket Waterpark',
  'stop_name_th': 'สวนน้ำอันดามันดา'},
 {'direction': 'Bus to Patong',
  'index': 3266,
  'lat': 7.908207595,
  'lon': 98.34954164,
  'no': 77,
  'stop_name_eng': 'Kathu Fresh Market',
  'stop_name_th': 'ตลาดสดกะทู้'},
 {'direction': 'Bus to Patong',
  'index': 3459,
  'lat': 7.911864114,
  'lon': 98.34250205,
  'no': 78,
  'stop_name_eng': 'PTT Station Kathu',
  'stop_name_th': 'ปตท. กะทู้'},
 {'direction': 'Bus to Patong',
  'index': 3649,
  'lat': 7.911319948,
  'lon': 98.3362023,
  'no': 79,
  'stop_name_eng': 'Siko',
  'stop_name_th': 'สี่กอ'},
 {'direction': 'Bus to Patong',
  'index': 3736,
  'lat': 7.90995831,
  'lon': 98.3327828,
  'no': 80,
  'stop_name_eng': 'Kathu Police Station',
  'stop_name_th': 'สถานีตำรวจภูธรกะทู้'},
 {'direction': 'Bus to Patong',
  'index': 4922,
  'lat': 7.883948691,
  'lon': 98.30179899,
  'no': 81,
  'stop_name_eng': 'Coffee Mania',
  'stop_name_th': 'คอฟฟี่ มาเนีย'},
 {'direction': 'Bus to Patong',
  'index': 5178,
  'lat': 7.882674707,
  'lon': 98.2933205,
  'no': 82,
  'stop_name_eng': 'Malin Plaza',
  'stop_name_th': 'มาลินพลาซ่า'}]

stop_list_patong_bus1 = [{'direction': 'Bus to Terminal 1',
  'index': 0,
  'lat': 7.88742,
  'lon': 98.291173,
  'no': 83,
  'stop_name_eng': 'Patong',
  'stop_name_th': 'ป่าตอง'},
 {'direction': 'Bus to Terminal 1',
  'index': 115,
  'lat': 7.882809803,
  'lon': 98.29345369,
  'no': 84,
  'stop_name_eng': 'Malin Plaza',
  'stop_name_th': 'มาลินพลาซ่า'},
 {'direction': 'Bus to Terminal 1',
  'index': 371,
  'lat': 7.884033046,
  'lon': 98.3017782,
  'no': 85,
  'stop_name_eng': 'Makro Nanai',
  'stop_name_th': 'แม็คโคร นาใน'},
 {'direction': 'Bus to Terminal 1',
  'index': 1550,
  'lat': 7.909912418,
  'lon': 98.3323804,
  'no': 86,
  'stop_name_eng': 'Kathu Police Station',
  'stop_name_th': 'สถานีตำรวจภูธรกะทู้'},
 {'direction': 'Bus to Terminal 1',
  'index': 1652,
  'lat': 7.911686805,
  'lon': 98.33621525,
  'no': 87,
  'stop_name_eng': 'Siko',
  'stop_name_th': 'สี่กอ'},
 {'direction': 'Bus to Terminal 1',
  'index': 1843,
  'lat': 7.911828211,
  'lon': 98.34279008,
  'no': 88,
  'stop_name_eng': 'PTT Station Kathu',
  'stop_name_th': 'ปตท. กะทู้'},
 {'direction': 'Bus to Terminal 1',
  'index': 2031,
  'lat': 7.908360146,
  'lon': 98.34964231,
  'no': 89,
  'stop_name_eng': 'Kathu Fresh Market',
  'stop_name_th': 'ตลาดสดกะทู้'},
 {'direction': 'Bus to Terminal 1',
  'index': 2377,
  'lat': 7.905041515,
  'lon': 98.36436545,
  'no': 90,
  'stop_name_eng': 'Andamanda Phuket Waterpark',
  'stop_name_th': 'สวนน้ำอันดามันดา'},
 {'direction': 'Bus to Terminal 1',
  'index': 2484,
  'lat': 7.906262429,
  'lon': 98.36908411,
  'no': 91,
  'stop_name_eng': 'Lotus Samkong',
  'stop_name_th': 'โลตัส สามกอง'},
 {'direction': 'Bus to Terminal 1',
  'index': 2580,
  'lat': 7.907018353,
  'lon': 98.37334465,
  'no': 92,
  'stop_name_eng': 'Chillva Market',
  'stop_name_th': 'ตลาดชิลวา'},
 {'direction': 'Bus to Terminal 1',
  'index': 2727,
  'lat': 7.904781267,
  'lon': 98.37777846,
  'no': 93,
  'stop_name_eng': 'Bangkok Hospital Phuket',
  'stop_name_th': 'โรงพยาบาลกรุงเทพภูเก็ต'},
 {'direction': 'Bus to Terminal 1',
  'index': 2966,
  'lat': 7.897191545,
  'lon': 98.38418576,
  'no': 94,
  'stop_name_eng': 'Vachira Phuket Hospital',
  'stop_name_th': 'โรงพยาบาลวชิระภูเก็ต'},
 {'direction': 'Bus to Terminal 1',
  'index': 3184,
  'lat': 7.892510646,
  'lon': 98.38976981,
  'no': 95,
  'stop_name_eng': 'Phuket Wittayalai School',
  'stop_name_th': 'โรงเรียนภูเก็ตวิทยาลัย'},
 {'direction': 'Bus to Terminal 1',
  'index': 3270,
  'lat': 7.891111846,
  'lon': 98.39197764,
  'no': 96,
  'stop_name_eng': 'Satree Phuket School',
  'stop_name_th': 'โรงเรียนสตรีภูเก็ต'},
 {'direction': 'Bus to Terminal 1',
  'index': 3411,
  'lat': 7.889820314,
  'lon': 98.39786569,
  'no': 115,
  'stop_name_eng': 'Sanamchai',
  'stop_name_th': 'สนามชัย'}]

stop_list_airport_rawai = [{'direction': 'Bus to Airport',
  'index': 10885,
  'lat': 7.77208774295,
  'lon': 98.3217882953,
  'no': 16,
  'stop_name_eng': 'Rawai Beach',
  'stop_name_th': 'หาดราไวย์'},
 {'direction': 'Bus to Airport',
  'index': 10247,
  'lat': 7.79441794757,
  'lon': 98.3155604072,
  'no': 17,
  'stop_name_eng': 'Sai Yuan',
  'stop_name_th': 'ไสยวน'},
 {'direction': 'Bus to Airport',
  'index': 9324,
  'lat': 7.81247074512,
  'lon': 98.3010678512,
  'no': 18,
  'stop_name_eng': 'Andaman Cannacia Resort',
  'stop_name_th': 'อันดามัน คาเนเซีย'},
 {'direction': 'Bus to Airport',
  'index': 9161,
  'lat': 7.81648548634,
  'lon': 98.3006487149,
  'no': 19,
  'stop_name_eng': 'Beyond hotel Kata',
  'stop_name_th': 'บียอนด์ กะตะ'},
 {'direction': 'Bus to Airport',
  'index': 9109,
  'lat': 7.81874394528,
  'lon': 98.3000995192,
  'no': 20,
  'stop_name_eng': 'Kata Palm',
  'stop_name_th': 'กะตะ ปาล์ม'},
 {'direction': 'Bus to Airport',
  'index': 8952,
  'lat': 7.82509655568,
  'lon': 98.2970288793,
  'no': 21,
  'stop_name_eng': 'OZO Kata',
  'stop_name_th': 'โอโซ่ ภูเก็ต'},
 {'direction': 'Bus to Airport',
  'index': 8926,
  'lat': 7.82622531978,
  'lon': 98.2966885186,
  'no': 22,
  'stop_name_eng': 'Peach Blossom',
  'stop_name_th': 'พีช บลอสซั่ม'},
 {'direction': 'Bus to Airport',
  'index': 8825,
  'lat': 7.83035424986,
  'lon': 98.2950633387,
  'no': 23,
  'stop_name_eng': 'Karon Stadium',
  'stop_name_th': 'สนามกีฬากะรน'},
 {'direction': 'Bus to Airport',
  'index': 8520,
  'lat': 7.84400759933,
  'lon': 98.2941565461,
  'no': 24,
  'stop_name_eng': 'Woraburi Karon',
  'stop_name_th': 'วรบุรี ภูเก็ต รีสอร์ท'},
 {'direction': 'Bus to Airport',
  'index': 8435,
  'lat': 7.84775915937,
  'lon': 98.2933055042,
  'no': 25,
  'stop_name_eng': 'Karon Circle',
  'stop_name_th': 'วงเวียนกะรน'},
 {'direction': 'Bus to Airport',
  'index': 7892,
  'lat': 7.8609001407,
  'lon': 98.2845652549,
  'no': 26,
  'stop_name_eng': 'Secret cliff resort ',
  'stop_name_th': 'ซีเคร็ท คลิฟ'},
 {'direction': 'Bus to Airport',
  'index': 7215,
  'lat': 7.88752462813,
  'lon': 98.2913288644,
  'no': 27,
  'stop_name_eng': 'Patong Bus Stop',
  'stop_name_th': 'จุดจอดรถป่าตอง'},
 {'direction': 'Bus to Airport',
  'index': 7031,
  'lat': 7.89407,
  'lon': 98.29513,
  'no': 28,
  'stop_name_eng': 'Bangla Patong ',
  'stop_name_th': 'ป่าตอง บางลา'},
 {'direction': 'Bus to Airport',
  'index': 6685,
  'lat': 7.90467913947,
  'lon': 98.2972091153,
  'no': 29,
  'stop_name_eng': 'Four Point Patong',
  'stop_name_th': 'โฟร์ พอยต์ ป่าตอง'},
 {'direction': 'Bus to Airport',
  'index': 6569,
  'lat': 7.91067572034,
  'lon': 98.2957506346,
  'no': 30,
  'stop_name_eng': 'Kalim School',
  'stop_name_th': 'โรงเรียนกะหลิม'},
 {'direction': 'Bus to Airport',
  'index': 6452,
  'lat': 7.9149017669,
  'lon': 98.2927425399,
  'no': 31,
  'stop_name_eng': 'Kalim Bus Stop',
  'stop_name_th': 'หาดกะหลิม'},
 {'direction': 'Bus to Airport',
  'index': 5370,
  'lat': 7.94747711246,
  'lon': 98.2805120802,
  'no': 32,
  'stop_name_eng': 'Big C Kamala',
  'stop_name_th': 'บิ๊กซี กมลา'},
 {'direction': 'Bus to Airport',
  'index': 5138,
  'lat': 7.95413235293,
  'lon': 98.2865626774,
  'no': 33,
  'stop_name_eng': 'Phuket Fantasea',
  'stop_name_th': 'ภูเก็ต แฟนตาซี'},
 {'direction': 'Bus to Airport',
  'index': 5026,
  'lat': 7.95732021988,
  'lon': 98.2842693667,
  'no': 34,
  'stop_name_eng': 'Kamala Muslim Cemetery',
  'stop_name_th': 'กุโบร์ กมลา'},
 {'direction': 'Bus to Airport',
  'index': 4944,
  'lat': 7.9609119227,
  'lon': 98.2846268463,
  'no': 35,
  'stop_name_eng': 'Cafe De Mar',
  'stop_name_th': 'คาเฟ่ เดล มาร์'},
 {'direction': 'Bus to Airport',
  'index': 4447,
  'lat': 7.97543085798,
  'lon': 98.2806006571,
  'no': 36,
  'stop_name_eng': 'Surin Beach',
  'stop_name_th': 'หาดสุรินทร์'},
 {'direction': 'Bus to Airport',
  'index': 3865,
  'lat': 7.98564677947,
  'lon': 98.3019957451,
  'no': 37,
  'stop_name_eng': 'Lotus Cherngtalay',
  'stop_name_th': 'โลตัสเชิงทะเล'},
 {'direction': 'Bus to Airport',
  'index': 3576,
  'lat': 8.00036,
  'lon': 98.29662,
  'no': 38,
  'stop_name_eng': 'Laguna',
  'stop_name_th': 'ลากูน่า'},
 {'direction': 'Bus to Airport',
  'index': 3543,
  'lat': 7.99461605031,
  'lon': 98.3072837597,
  'no': 39,
  'stop_name_eng': 'Cherngtalay School',
  'stop_name_th': 'เชิงทะเลวิทยคม'},
 {'direction': 'Bus to Airport',
  'index': 2589,
  'lat': 8.02671784214,
  'lon': 98.3299507153,
  'no': 40,
  'stop_name_eng': 'Baan Khian',
  'stop_name_th': 'บ้านเคียน'},
 {'direction': 'Bus to Airport',
  'index': 2357,
  'lat': 8.03455487516,
  'lon': 98.3332974713,
  'no': 41,
  'stop_name_eng': 'Thalang Public Health Office',
  'stop_name_th': 'สำนักงานสาธารณสุข ถลาง'}]