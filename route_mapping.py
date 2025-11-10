import folium
import json

geojson_path = "data_routes/dragonline_reordered.geojson"

# Load geojson
with open(geojson_path, "r") as f:
    data = json.load(f)

# Extract coordinates + order index
coords = []
for feat in data["features"]:
    lon, lat = feat["geometry"]["coordinates"]
    idx = feat["properties"]["order"]
    coords.append((idx, lat, lon))

# Sort by route order
coords.sort(key=lambda x: x[0])

# Center of map = avg coords
center_lat = sum(c[1] for c in coords) / len(coords)
center_lon = sum(c[2] for c in coords) / len(coords)

m = folium.Map(location=[center_lat, center_lon], zoom_start=12, max_zoom=25)

# Draw polyline (full route)
route_latlon = [(c[1], c[2]) for c in coords]
folium.PolyLine(route_latlon, weight=4, opacity=0.7).add_to(m)

# Add clickable markers
for idx, lat, lon in coords:
    popup_html = f"""
    <b>Route Index:</b> {idx}<br>
    <b>Lat:</b> {lat}<br>
    <b>Lon:</b> {lon}
    """
    folium.CircleMarker(
        location=[lat, lon],
        radius=3,
        popup=popup_html,
        tooltip=f"Index {idx}",
        fill=True
    ).add_to(m)

m.save("route_index_map.html")
print("route_index_map.html saved")