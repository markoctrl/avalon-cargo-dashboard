import os
import csv
import requests

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


# ---------------------------------------
# CONFIGURATION
# ---------------------------------------

AIRPORTS = {
    "YMAV": "Avalon",
    "YMML": "Melbourne"
}

TOKEN_URL = (
    "https://auth.opensky-network.org/"
    "auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)

OPENSKY_BASE_URL = "https://opensky-network.org/api"

OUTPUT_FILE = "data/movements.csv"


# ---------------------------------------
# GET OPENSKY ACCESS TOKEN
# ---------------------------------------

def get_access_token():

    client_id = os.environ["OPENSKY_CLIENT_ID"]
    client_secret = os.environ["OPENSKY_CLIENT_SECRET"]

    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret
        },
        timeout=30
    )

    response.raise_for_status()

    return response.json()["access_token"]


# ---------------------------------------
# DETERMINE YESTERDAY IN MELBOURNE
# ---------------------------------------

def get_yesterday_timestamps():

    melbourne = ZoneInfo("Australia/Melbourne")

    now = datetime.now(melbourne)

    yesterday = now.date() - timedelta(days=1)

    start_local = datetime(
        yesterday.year,
        yesterday.month,
        yesterday.day,
        0,
        0,
        0,
        tzinfo=melbourne
    )

    end_local = start_local + timedelta(days=1)

    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    begin = int(start_utc.timestamp())
    end = int(end_utc.timestamp()) - 1

    return yesterday, begin, end


# ---------------------------------------
# GET FLIGHTS
# ---------------------------------------

def get_flights(token, airport, direction, begin, end):

    if direction == "Arrival":
        endpoint = "flights/arrival"
    else:
        endpoint = "flights/departure"

    url = f"{OPENSKY_BASE_URL}/{endpoint}"

    response = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}"
        },
        params={
            "airport": airport,
            "begin": begin,
            "end": end
        },
        timeout=60
    )

    # OpenSky returns 404 if there are no flights
    if response.status_code == 404:
        return []

    response.raise_for_status()

    return response.json()


# ---------------------------------------
# MAIN
# ---------------------------------------

def main():

    print("Starting Avalon Cargo flight collection")

    token = get_access_token()

    yesterday, begin, end = get_yesterday_timestamps()

    print(f"Collecting flights for: {yesterday}")
    print(f"Unix start: {begin}")
    print(f"Unix end:   {end}")

    rows = []

    for airport_code, airport_name in AIRPORTS.items():

        for direction in ["Arrival", "Departure"]:

            print(
                f"Collecting {direction}s for "
                f"{airport_code} - {airport_name}"
            )

            flights = get_flights(
                token,
                airport_code,
                direction,
                begin,
                end
            )

            print(f"Found {len(flights)} flights")

            for flight in flights:

                rows.append({
                    "CaptureDate": datetime.now(
                        ZoneInfo("Australia/Melbourne")
                    ).strftime("%Y-%m-%d"),

                    "FlightDate": str(yesterday),

                    "Airport": airport_code,
                    "AirportName": airport_name,
                    "Direction": direction,

                    "ICAO24": flight.get("icao24"),
                    "Callsign": (
                        flight.get("callsign") or ""
                    ).strip(),

                    "OriginAirport":
                        flight.get("estDepartureAirport"),

                    "DestinationAirport":
                        flight.get("estArrivalAirport"),

                    "FirstSeen":
                        flight.get("firstSeen"),

                    "LastSeen":
                        flight.get("lastSeen"),

                    "DepartureAirportDistance":
                        flight.get(
                            "estDepartureAirportHorizDistance"
                        ),

                    "ArrivalAirportDistance":
                        flight.get(
                            "estArrivalAirportHorizDistance"
                        ),

                    "Source": "OpenSky"
                })

    print(f"Total movements collected: {len(rows)}")

    os.makedirs("data", exist_ok=True)

    fieldnames = [
        "CaptureDate",
        "FlightDate",
        "Airport",
        "AirportName",
        "Direction",
        "ICAO24",
        "Callsign",
        "OriginAirport",
        "DestinationAirport",
        "FirstSeen",
        "LastSeen",
        "DepartureAirportDistance",
        "ArrivalAirportDistance",
        "Source"
    ]

    with open(
        OUTPUT_FILE,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )

        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
