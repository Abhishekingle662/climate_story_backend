# backend.py (Flask Backend)
from flask import Flask, jsonify, request
from flask_cors import CORS
import datetime as dt
import meteomatics.api as api
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from timezonefinder import TimezoneFinder
import pytz
import logging
from dotenv import load_dotenv
import os

# Configure logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

username = os.getenv.getenv('METEOMATICS_USERNAME')
password = os.getenv.getenv('METEOMATICS_PASSWORD')


cities = {
    'Bloomington': (39.165325, -86.52638569999999),
    'Chicago': (41.8781, -87.6298),
    'New York': (40.7128, -74.0060),
    'Los Angeles': (34.0522, -118.2437)
}

# Removed 'pressure_surface:hPa'
parameters = [
    't_2m:C',
    'precip_1h:mm',
    'wind_speed_10m:ms',
    'relative_humidity_2m:p',
    'uv:idx',
]

geolocator = Nominatim(user_agent="weather_app")
tf = TimezoneFinder()

@app.route('/cities', methods=['GET'])
def get_cities():
    logging.debug("Fetching list of predefined cities.")
    return jsonify(list(cities.keys()))

@app.route('/search', methods=['GET'])
def search_city():
    query = request.args.get('q', '')
    logging.debug(f"Searching for city: {query}")
    try:
        location = geolocator.geocode(query)
        if location:
            logging.debug(f"City found: {location.address}")
            return jsonify({
                'name': location.address,
                'lat': location.latitude,
                'lon': location.longitude
            })
        else:
            logging.warning(f"City not found: {query}")
            return jsonify({'error': 'City not found'}), 404
    except (GeocoderTimedOut, GeocoderUnavailable) as e:
        logging.error(f"Geocoding service unavailable: {str(e)}")
        return jsonify({'error': 'Geocoding service unavailable'}), 503

@app.route('/weather', methods=['GET'])
def get_weather():
    city = request.args.get('city')
    lat = request.args.get('lat')
    lon = request.args.get('lon')

    logging.debug(f"Received weather request - city: {city}, lat: {lat}, lon: {lon}")

    if city:
        coordinates = [cities.get(city, cities['Bloomington'])]
        logging.debug(f"Using predefined city coordinates: {coordinates[0]}")
    elif lat and lon:
        try:
            lat = float(lat)
            lon = float(lon)
            coordinates = [(lat, lon)]
            logging.debug(f"Using provided coordinates: {coordinates[0]}")
        except ValueError:
            logging.error("Invalid latitude or longitude provided.")
            return jsonify({'error': 'Invalid latitude or longitude'}), 400
    else:
        logging.error("City or coordinates not provided.")
        return jsonify({'error': 'City or coordinates required'}), 400

    startdate = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    enddate = startdate + dt.timedelta(days=1)
    interval = dt.timedelta(hours=1)

    logging.debug(f"Querying Meteomatics API from {startdate} to {enddate} with interval {interval}.")

    try:
        df = api.query_time_series(
            coordinates,
            startdate,
            enddate,
            interval,
            parameters,
            username,
            password,
            model='mix'
        )
        logging.debug("Successfully queried Meteomatics API.")
    except Exception as e:
        logging.error(f"Meteomatics API query failed: {str(e)}")
        return jsonify({'error': str(e)}), 500

    # Reset the index to include 'validdate' as a column
    df.reset_index(inplace=True)

    weather_data = df.to_dict(orient='records')

    # Determine the time zone based on coordinates
    if city:
        coord = cities.get(city, cities['Bloomington'])
    else:
        coord = coordinates[0]

    logging.debug(f"Determining time zone for coordinates: {coord}")
    timezone_str = tf.timezone_at(lng=coord[1], lat=coord[0])
    if not timezone_str:
        timezone_str = 'UTC'  # Fallback to UTC if timezone not found
        logging.warning(f"Time zone not found for coordinates {coord}. Falling back to UTC.")

    try:
        local_tz = pytz.timezone(timezone_str)
    except pytz.UnknownTimeZoneError:
        local_tz = pytz.UTC
        logging.error(f"Unknown time zone '{timezone_str}'. Falling back to UTC.")

    # Convert 'validdate' from UTC to local time
    for entry in weather_data:
        if 'validdate' in entry and entry['validdate']:
            try:
                utc_time = dt.datetime.fromisoformat(entry['validdate'])
                utc_time = utc_time.replace(tzinfo=dt.timezone.utc)
                local_time = utc_time.astimezone(local_tz)
                entry['validdate'] = local_time.isoformat()
            except Exception as e:
                logging.error(f"Error converting time for entry {entry}: {str(e)}")
                entry['validdate'] = None  # Or handle as per your requirement
        else:
            logging.warning(f"Missing 'validdate' in entry: {entry}")
            entry['validdate'] = None  # Or handle as per your requirement

    logging.debug(f"Returning weather data with time zone '{timezone_str}'.")
    return jsonify({
        'weather_data': weather_data,
        'timezone': timezone_str
    })



# Run the Flask app
if __name__ == "__main__":
    app.run()