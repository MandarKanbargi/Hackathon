from flask import Flask, render_template, request 
from flask import session
import requests
import folium
import math

app = Flask(__name__)
app.secret_key = 'your_unique_secret_key_here'

VEHICLE_CAPACITY = 5000
OR_SERVICE_API_KEY = '5b3ce3597851110001cf62481d7abc2708ad4856ad63639288ec805b'
WEATHER_API_KEY = '5938991ca3585919457c1147d4370f6d'
TRAFFIC_API_KEY = 'u1xqxd7esr0PWotWPAiWCBP9GeH8botj'

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/route_optimizer')
def route_optimizer():
    return render_template('route_optimizer.html')

@app.route('/route_optimizer/get_route', methods=['POST'])
def get_route():
    start_city = request.form['start']
    end_city = request.form['end']
    load_weight = float(request.form['load_weight'])
    fuel_type = request.form.get("fuel_type")
    fuel_efficiency = int(request.form.get("fuel_efficiency"))

    if fuel_type not in {"petrol", "diesel", "electric"}:
        return "Error: Invalid fuel type."

    start_coords = geocode_city_to_coordinates(start_city)
    end_coords = geocode_city_to_coordinates(end_city)

    if not start_coords or not end_coords:
        return render_template('route_optimizer.html', error="Could not geocode one or both city names.")

    routes = get_routes_from_osrm(start_coords, end_coords)

    if not routes:
        return render_template('route_optimizer.html', error="Could not find routes between the cities.")

    map_path = generate_map(routes, start_coords, end_coords)
    
    route_data = []
    for route in routes:
        weather = get_weather_data(route['route'])
        emissions = get_emissions_data(route['distance'], fuel_type, fuel_efficiency)
        traffic_condition, traffic_speed = get_traffic_data(start_coords, end_coords)
        traffic_speed = adjust_speed_based_on_load(traffic_speed, load_weight)
        estimated_time_hours = route['distance'] / traffic_speed
        formatted_time = convert_minutes_to_hr_min(estimated_time_hours * 60)

        route_data.append({
            'distance': route['distance'],
            'weather': weather,
            'emissions': emissions,
            'traffic_condition': traffic_condition,
            'estimated_time': formatted_time
        })

    session['route_data'] = route_data
    session['form_data'] = request.form

    return render_template(
        'route_optimizer.html',
        routes=routes,
        route_data=route_data,
        map_path=map_path
    )

@app.route('/dashboard')
def dashboard():
   
    route_data = session.get('route_data')
    form_data = session.get('form_data')
    print(form_data)
    
    return render_template('dashboard.html', route_data=route_data, form_data=form_data)

def adjust_speed_based_on_load(speed, load_weight):
    if load_weight > VEHICLE_CAPACITY:
        reduction_factor = (load_weight - VEHICLE_CAPACITY) / 1000 * 0.1
        return max(0.5, speed * (1 - reduction_factor))
    increase_factor = (VEHICLE_CAPACITY - load_weight) / 1000 * 0.05
    return speed * (1 + increase_factor)

def convert_minutes_to_hr_min(minutes):
    hours = minutes // 60
    minutes_remaining = minutes % 60
    return f"{int(hours)}h {int(minutes_remaining)}m"

def geocode_city_to_coordinates(city_name):
    url = f'https://api.openrouteservice.org/geocode/search?api_key={OR_SERVICE_API_KEY}&text={city_name}'
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data['features']:
            return data['features'][0]['geometry']['coordinates']
    except requests.RequestException as e:
        print(f"Error in geocoding request: {e}")
    return None

def get_nearby_fuel_stations(route):
    """
    Fetch nearby fuel stations along the route using Overpass API (OpenStreetMap).
    Filters stations within 1 km of the route.
    """
    fuel_stations = []
    # We'll query for fuel stations within a bounding box around the route
    start_lat, start_lon = route[0][1], route[0][0]
    end_lat, end_lon = route[-1][1], route[-1][0]

    # Set a bounding box around the route (This can be adjusted as per your need)
    bbox = f"{min(start_lat, end_lat)},{min(start_lon, end_lon)},{max(start_lat, end_lat)},{max(start_lon, end_lon)}"

    overpass_url = "http://overpass-api.de/api/interpreter"
    overpass_query = f"""
    [out:json];
    (
        node["amenity"="fuel"]({bbox});
    );
    out body;
    """
    
    try:
        response = requests.get(overpass_url, params={'data': overpass_query})
        response.raise_for_status()
        data = response.json()

        for element in data['elements']:
            name = element.get('tags', {}).get('name', 'Unknown Fuel Station')
            lat = element['lat']
            lon = element['lon']
            # Check if the fuel station is within 1 km of the route
            for point in route:
                route_lat, route_lon = point[1], point[0]
                distance = haversine(route_lat, route_lon, lat, lon)
                if distance <= 1:  # If within 1 km
                    fuel_stations.append({'name': name, 'lat': lat, 'lon': lon})
                    break  # Exit the loop once a nearby fuel station is found

        return fuel_stations
    except requests.exceptions.RequestException as e:
        print(f"Error fetching fuel stations: {e}")
        return []

def haversine(lat1, lon1, lat2, lon2):
    # Haversine formula to calculate distance between two points on the earth (in kilometers)
    R = 6371  # Radius of the Earth in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 4 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c  # Distance in kilometers

def get_nearby_tolls(route):
    """
    Fetch nearby tolls along the route using Overpass API (OpenStreetMap).
    Filters tolls within 1 km of the route.
    """
    tolls = []
    start_lat, start_lon = route[0][1], route[0][0]
    end_lat, end_lon = route[-1][1], route[-1][0]

    # Set a bounding box around the route
    bbox = f"{min(start_lat, end_lat)},{min(start_lon, end_lon)},{max(start_lat, end_lat)},{max(start_lon, end_lon)}"

    overpass_url = "http://overpass-api.de/api/interpreter"
    overpass_query = f"""
    [out:json];
    (
        node["barrier"="toll_booth"]({bbox});
    );
    out body;
    """

    try:
        response = requests.get(overpass_url, params={'data': overpass_query})
        response.raise_for_status()
        data = response.json()

        for element in data['elements']:
            name = element.get('tags', {}).get('name', 'Unknown Toll')
            lat = element['lat']
            lon = element['lon']
            # Check if the toll is within 1 km of the route
            for point in route:
                route_lat, route_lon = point[1], point[0]
                distance = haversine(route_lat, route_lon, lat, lon)
                if distance <= 1:  # If within 1 km
                    tolls.append({'name': name, 'lat': lat, 'lon': lon})
                    break  # Exit the loop once a nearby toll is found

        return tolls
    except requests.exceptions.RequestException as e:
        print(f"Error fetching tolls: {e}")
        return []


def get_routes_from_osrm(start_coords, end_coords):
    url = f'http://router.project-osrm.org/route/v1/driving/{start_coords[0]},{start_coords[1]};{end_coords[0]},{end_coords[1]}?alternatives=true&overview=full&geometries=geojson'
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data['routes']:
            routes = []
            for route in data['routes']:
                route_data = {
                    'route': route['geometry']['coordinates'],
                    'distance': round(route['legs'][0]['distance'] / 1000, 2),
                    'estimated_time': convert_minutes_to_hr_min((route['legs'][0]['distance'] / 50000) * 60)  # Assuming 50 km/h
                }
                routes.append(route_data)
            return sorted(routes, key=lambda x: x['distance'])
    except requests.RequestException as e:
        print(f"Error in route request: {e}")
    return None

def generate_map(routes, start_coords, end_coords):
    import folium
    from folium import LayerControl

    start_lat, start_lon = routes[0]['route'][0][1], routes[0]['route'][0][0]
    map_obj = folium.Map(location=[start_lat, start_lon], zoom_start=12, tiles="OpenStreetMap")

    map_obj.get_root().html.add_child(folium.Element("""
        <style>
        @keyframes blink {
            0% { opacity: 0.4; }
            50% { opacity: 1; }
            100% { opacity: 0.4; }
        }
        .blink-circle {
            animation: blink 2s infinite;
            width: 70px;
            height: 70px;
            background-color: rgba(0, 91, 224, 0.26);
            border-radius: 50%;
            position: absolute;
            transform: translate(-50%, -50%);
            margin: 10px;                                         
        }
        </style>
    """))

    truck_icon_html = """
        <div style="font-size: 25px; color: #4287f5;">
            <i class="fa-solid fa-truck" style="color: #4287f5;"></i>
        </div>
    """
    folium.Marker(
        location=[start_lat, start_lon],
        popup="FedEx Truck",
        tooltip="FedEx Truck",
        icon=folium.DivIcon(html=truck_icon_html)
    ).add_to(map_obj)

    folium.Marker(
        location=[start_lat, start_lon],
        icon=folium.DivIcon(html='<div class="blink-circle"></div>')
    ).add_to(map_obj)

    end_lat, end_lon = routes[0]['route'][-1][1], routes[0]['route'][-1][0]
    folium.Marker(
        location=[end_lat, end_lon],
        popup="Ending Point",
        tooltip="End",
        icon=folium.Icon(color="red", icon="stop")
    ).add_to(map_obj)

    colors = ["blue", "green"]
    for idx, route in enumerate(routes):
        folium.PolyLine(
            locations=[(lat, lon) for lon, lat in route['route']],
            color=colors[idx % len(colors)],
            weight=4,
            opacity=1,
            tooltip=f"Route {idx + 1}: {route['distance']} km"
        ).add_to(map_obj)

    toll_layer = folium.FeatureGroup(name="Tolls", show=False)
    fuel_layer = folium.FeatureGroup(name="Fuel Stations", show=False)

    for idx, route in enumerate(routes):
        fuel_stations = get_nearby_fuel_stations(route['route'])
        for station in fuel_stations:
            fuel_icon_html = """
                <div style="font-size: 25px; color: ##00fc43;">
                    <i class="fa-solid fa-gas-pump fa-beat" style="color: #00b344;"></i>
                </div>
            """
            folium.Marker(
                location=[station['lat'], station['lon']],
                popup=f"Fuel Station: {station['name']}",
                tooltip="Fuel Station",
                icon=folium.DivIcon(html=fuel_icon_html)
            ).add_to(fuel_layer)

        tolls = get_nearby_tolls(route['route'])
        for toll in tolls:
            toll_icon_html = """
                <div style="font-size: 25px; color: #ff8800;">
                    <i class="fa-solid fa-road fa-bounce" style="color: #ff8800;"></i>
                </div>
            """
            folium.Marker(
                location=[toll['lat'], toll['lon']],
                popup=f"Toll: {toll['name']}, Fee: {toll.get('fee', 'N/A')}",
                tooltip="Toll",
                icon=folium.DivIcon(html=toll_icon_html)
            ).add_to(toll_layer)

    toll_layer.add_to(map_obj)
    fuel_layer.add_to(map_obj)

    folium.TileLayer(
        "CartoDB positron",
        name="CartoDB Positron",
        attr="&copy; <a href='https://carto.com/attributions'>CartoDB</a>",
        control=True
    ).add_to(map_obj)

    LayerControl(collapsed=False).add_to(map_obj)

    map_path = 'static/route_map.html'
    map_obj.save(map_path)

    return map_path

def get_weather_data(route):
    # Use OpenWeatherMap API to get weather data for the first location on the route
    lat, lon = route[0][1], route[0][0]
    url = f'http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}'

    try:
        response = requests.get(url)
        data = response.json()
        if data and 'weather' in data:
            weather = data['weather'][0]['description']
            temperature = data['main']['temp'] - 273.15  # Convert from Kelvin to Celsius
            humidity = data['main']['humidity']
            # Round temperature to 2 decimal places
            temperature = round(temperature, 2)
            return {"description": weather, "temperature": temperature, "humidity": humidity}
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error in weather request: {e}")
        return None
    
def get_emissions_data(distance, fuel_type, fuel_efficiency):
    """Calculate CO2 emissions based on distance, fuel type, and fuel efficiency."""
    if fuel_type == "electric":
        return 0  # Assuming electric vehicles have no CO2 emissions
    else:
        # Average CO2 emission factors (in grams per km)
        emission_factors = {
            "petrol": 350,  # grams per km
            "diesel": 800,  # grams per km
        }
        emissions = emission_factors.get(fuel_type, 0) * distance  # in grams
        return emissions / 1000  # Convert grams to kilograms


def fetch_traffic(start_coords):
    """Fetch traffic conditions for the starting point."""
    # TomTom Traffic API for traffic data
    tomtom_traffic_url = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
    tomtom_params = {
        "point": f"{start_coords[1]},{start_coords[0]}",  # Latitude, Longitude
        "key": TRAFFIC_API_KEY
    }

    traffic_info = {}

    try:
        # Fetch traffic data
        traffic_response = requests.get(tomtom_traffic_url, params=tomtom_params)
        if traffic_response.status_code == 200:
            traffic_data = traffic_response.json()
            current_speed = traffic_data.get("flowSegmentData", {}).get("currentSpeed", 50)  # Default speed if not found

            # Determine traffic status
            if current_speed >= 50:
                traffic_status = "Clear"
            elif current_speed <= 30:
                traffic_status = "Congested"
            else:
                traffic_status = "Moderate"

            traffic_info = {
                "current_speed": current_speed,
                "traffic_status": traffic_status,
            }
        else:
            traffic_info = {"current_speed": "Unknown", "traffic_status": "Unknown"}
        print(current_speed)

        return {"traffic": traffic_info}

    except Exception as e:
        print(f"Error fetching traffic: {e}")
        return {
            "traffic": {"current_speed": "Unknown", "traffic_status": "Unknown"}
        }

def get_traffic_data(start_coords, end_coords):
        # Fetch traffic and weather data for the starting point
    data = fetch_traffic(start_coords)
    traffic_info = data["traffic"]

    # Map traffic conditions to speeds
    speed_by_traffic = {
        "Clear": 60,  # Speed in km/h for clear traffic
        "Moderate": 40,  # Speed in km/h for moderate traffic
        "Congested": 30,  # Speed in km/h for congested traffic
    }

    traffic_status = traffic_info.get("traffic_status", "Unknown")
    current_speed = speed_by_traffic.get(traffic_status, 50)  # Default speed if status is unknown

    return traffic_status, current_speed

if __name__ == '__main__':
    app.run(debug=True)
