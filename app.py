from flask import Flask, render_template, request
import requests
import folium
import math

app = Flask(__name__)

VEHICLE_CAPACITY = 5000

# OpenRouteService API Key
OR_SERVICE_API_KEY = '5b3ce3597851110001cf62481d7abc2708ad4856ad63639288ec805b'

# OpenWeatherMap API Key
WEATHER_API_KEY = '5938991ca3585919457c1147d4370f6d'

# TomTom Traffic API Key
TRAFFIC_API_KEY = 'u1xqxd7esr0PWotWPAiWCBP9GeH8botj'


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/route_optimizer')
def route_optimizer():
    return render_template('route_optimizer.html')  # Ensure this file is in the templates folder


@app.route('/route_optimizer/get_route', methods=['POST'])
def get_route():
    start_city = request.form['start']
    end_city = request.form['end']

    # Get Coordinates from City Names
    start_coords = geocode_city_to_coordinates(start_city)
    end_coords = geocode_city_to_coordinates(end_city)
    load_weight = float(request.form['load_weight'])  # Load weight in kg
    fuel_type = request.form.get("fuel_type")
    fuel_efficiency = request.form.get("fuel_efficiency")

    fuel_efficiency = int(fuel_efficiency)
    start_coords = geocode_city_to_coordinates(start_city)
    end_coords = geocode_city_to_coordinates(end_city)

    if fuel_type not in {"petrol", "diesel", "electric"}:
        return "Error: Invalid fuel type."

    if start_coords and end_coords:
        # Get the route and distance from OpenRouteService API
        route, distance, estimated_time = get_route_from_osrm(start_coords, end_coords)

        if route:
            # Generate Map with Folium
            map_path = generate_map(route, start_coords, end_coords)

            # Get Weather Data
            weather = get_weather_data(route)

            # Get Emissions Data
            emissions = get_emissions_data(distance, fuel_type, fuel_efficiency)

            # Get traffic data and condition
            traffic_condition, traffic_speed = get_traffic_data(start_coords, end_coords)

            # Adjust speed based on load weight
            # Example logic: Reduce speed by 10% for every 1000 kg over 5000 kg or increase for lighter loads
            if load_weight > VEHICLE_CAPACITY:
                reduction_factor = (load_weight - VEHICLE_CAPACITY) / 1000 * 0.1  # 10% reduction for every 1000 kg
                traffic_speed *= max(0.5, (1 - reduction_factor))  # Ensure minimum speed factor of 0.5
            elif load_weight < VEHICLE_CAPACITY:
                increase_factor = (VEHICLE_CAPACITY - load_weight) / 1000 * 0.05  # 5% increase for every 1000 kg
                traffic_speed *= (1 + increase_factor)

            # Calculate the estimated time using the adjusted speed and distance
            estimated_time_hours = distance / traffic_speed  # Time in hours
            estimated_time_minutes = estimated_time_hours * 60  # Convert to minutes
            formatted_time = convert_minutes_to_hr_min(estimated_time_minutes)  # Convert to hr:min format

            return render_template(
                'route_optimizer.html',
                route=route,
                distance=distance,
                weather=weather,
                emissions=emissions,
                map_path=map_path,
                traffic_condition=traffic_condition,
                estimated_time=formatted_time
            )
        else:
            return render_template('route_optimizer.html', error="Could not find a route between the cities.")
    else:
        return render_template('route_optimizer.html', error="Could not geocode one or both city names.")


def convert_minutes_to_hr_min(minutes):
    hours = minutes // 60
    minutes_remaining = minutes % 60
    return f"{int(hours)}h {int(minutes_remaining)}m"


def geocode_city_to_coordinates(city_name):
    # Geocoding API to get coordinates from city name
    geocode_url = f'https://api.openrouteservice.org/geocode/search?api_key={OR_SERVICE_API_KEY}&text={city_name}'

    try:
        response = requests.get(geocode_url)
        response.raise_for_status()  # Ensure request is successful
        data = response.json()

        if 'features' in data and len(data['features']) > 0:
            coordinates = data['features'][0]['geometry']['coordinates']
            return coordinates  # Returns [longitude, latitude]
        else:
            print(f"No coordinates found for {city_name}.")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error in geocoding request: {e}")
        return None


def get_route_from_osrm(start_coords, end_coords):
    # OSRM Route API
    url = f'http://router.project-osrm.org/route/v1/driving/{start_coords[0]},{start_coords[1]};{end_coords[0]},{end_coords[1]}?overview=full&geometries=geojson'

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        if 'routes' in data and len(data['routes']) > 0:
            route = data['routes'][0]['geometry']['coordinates']
            distance = data['routes'][0]['legs'][0]['distance'] / 1000  # Convert to km
            distance = round(distance, 2)

            # Calculate estimated time based on distance and default speed (50 km/h for simplicity)
            estimated_time = distance / 50  # Time in hours
            estimated_time_minutes = estimated_time * 60  # Convert to minutes
            formatted_time = convert_minutes_to_hr_min(estimated_time_minutes)

            return route, distance, formatted_time
        else:
            print(f"No route found.")
            return None, None, None
    except requests.exceptions.RequestException as e:
        print(f"Error in route request: {e}")
        return None, None, None


def generate_map(route, start_coords, end_coords):
    """
    Generate a map with a highlighted route and markers only for the start, end points, and fuel stations.
    """
    # Create a map centered on the starting location
    start_lat, start_lon = route[0][1], route[0][0]  # Coordinates are in [lon, lat] format
    map_obj = folium.Map(location=[start_lat, start_lon], zoom_start=12)

    # Add a marker for the starting point
    folium.Marker(
        location=[start_lat, start_lon],
        popup="Starting Point",
        tooltip="Start",
        icon=folium.Icon(color="green", icon="play")
    ).add_to(map_obj)

    # Add a marker for the ending point
    end_lat, end_lon = route[-1][1], route[-1][0]
    folium.Marker(
        location=[end_lat, end_lon],
        popup="Ending Point",
        tooltip="End",
        icon=folium.Icon(color="red", icon="stop")
    ).add_to(map_obj)

    # Add the route to the map as a polyline
    folium.PolyLine(
        locations=[(lat, lon) for lon, lat in route],
        color="blue",
        weight=4,
        opacity=1
    ).add_to(map_obj)

    # Add fuel stations near the route
    fuel_stations = get_nearby_fuel_stations(route)
    for station in fuel_stations:
        # Create a custom DivIcon for Font Awesome
        fuel_icon_html = """
            <div style="font-size: 25px; color: #1a1a1a;">
                <i class="fa-solid fa-gas-pump fa-beat" style="color: #393e41;"></i>
            </div>
        """
        folium.Marker(
            location=[station['lat'], station['lon']],
            popup=station['name'],
            icon=folium.DivIcon(html=fuel_icon_html)
        ).add_to(map_obj)

    # Save the map to an HTML file
    map_path = 'static/route_map.html'
    map_obj.save(map_path)

    return map_path



def haversine(lat1, lon1, lat2, lon2):
    # Haversine formula to calculate distance between two points on the earth (in kilometers)
    R = 6371  # Radius of the Earth in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c  # Distance in kilometers

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


def get_emissions_data(distance_km, fuel_type, fuel_efficiency):
    """Calculate CO2 emissions based on distance, fuel type, and fuel efficiency."""
    if fuel_type == "electric":
        return 0  # Assuming electric vehicles have no CO2 emissions
    else:
        # Average CO2 emission factors (in grams per km)
        emission_factors = {
            "petrol": 350,  # grams per km
            "diesel": 800,  # grams per km
        }
        emissions = emission_factors.get(fuel_type, 0) * distance_km  # in grams
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
            if current_speed > 50:
                traffic_status = "Clear"
            elif current_speed < 30:
                traffic_status = "Congested"
            else:
                traffic_status = "Moderate"

            traffic_info = {
                "current_speed": current_speed,
                "traffic_status": traffic_status,
            }
        else:
            traffic_info = {"current_speed": "Unknown", "traffic_status": "Unknown"}

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
