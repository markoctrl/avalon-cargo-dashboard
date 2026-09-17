import os
import csv
import re
import requests

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


# =========================================
# CONFIGURATION
# =========================================

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
ADSBDB_BASE_URL = "https://api.adsbdb.com/v0/aircraft"

OUTPUT_FILE = "data/movements.csv"

MELBOURNE_TZ = ZoneInfo("Australia/Melbourne")


# =========================================
# OPENSKY AUTHENTICATION
# =========================================

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


# =========================================
# GET YESTERDAY IN MELBOURNE TIME
# =========================================

def get_yesterday_timestamps():

    now = datetime.now(MELBOURNE_TZ)

    yesterday = now.date() - timedelta(days=1)

    start_local = datetime(
        yesterday.year,
        yesterday.month,
        yesterday.day,
        0,
        0,
        0,
        tzinfo=MELBOURNE_TZ
    )

    end_local = start_local + timedelta(days=1)

    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    begin = int(start_utc.timestamp())
    end = int(end_utc.timestamp()) - 1

    return yesterday, begin, end


# =========================================
# CONVERT UNIX TIMESTAMP TO MELBOURNE TIME
# =========================================

def unix_to_melbourne(timestamp):

    if not timestamp:
        return ""

    return datetime.fromtimestamp(
        timestamp,
        tz=timezone.utc
    ).astimezone(
        MELBOURNE_TZ
    ).strftime("%Y-%m-%d %H:%M:%S")


# =========================================
# GET OPENSKY FLIGHTS
# =========================================

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

    if response.status_code == 404:
        return []

    response.raise_for_status()

    return response.json()


# =========================================
# GET AIRCRAFT DETAILS FROM ADSBDB
# =========================================

def get_aircraft_details(icao24, callsign=None):

    if not icao24:
        return {}

    url = f"{ADSBDB_BASE_URL}/{icao24}"

    params = {}

    if callsign:
        params["callsign"] = callsign

    try:

        response = requests.get(
            url,
            params=params,
            timeout=30
        )

        if response.status_code == 404:
            print(
                f"ADSBDB: aircraft not found: {icao24}"
            )
            return {}

        response.raise_for_status()

        data = response.json()

        return (
            data
            .get("response", {})
            .get("aircraft", {})
        )

    except requests.RequestException as error:

        print(
            f"ADSBDB lookup failed for "
            f"{icao24}: {error}"
        )

        return {}


# =========================================
# CARGO CLASSIFICATION
# =========================================

def classify_cargo(
    operator,
    aircraft_type,
    icao_type,
    callsign
):

    operator_text = (operator or "").upper().strip()
    aircraft_text = (aircraft_type or "").upper().strip()
    icao_text = (icao_type or "").upper().strip()
    callsign_text = (callsign or "").upper().strip()


    # =====================================
    # 1. KNOWN CARGO OPERATORS
    # =====================================

    known_cargo_operators = [
        "QANTAS FREIGHT",
        "FEDERAL EXPRESS",
        "FEDEX",
        "DHL",
        "UPS",
        "UNITED PARCEL SERVICE",
        "TOLL",
        "TEAM GLOBAL EXPRESS",
        "STARTRACK"
    ]

    for cargo_operator in known_cargo_operators:

        if cargo_operator in operator_text:

            return {
                "classification":
                    "Dedicated Freighter",

                "confidence":
                    "High",

                "reason":
                    f"Known cargo operator: {operator}"
            }


    # =====================================
    # 2. SPECIAL MISSION
    # =====================================

    special_mission_keywords = [
        "AMBULANCE",
        "POLICE",
        "DEFENCE",
        "DEFENSE",
        "AIR FORCE",
        "NAVY",
        "ARMY",
        "RESCUE",
        "EMERGENCY"
    ]

    for keyword in special_mission_keywords:

        if keyword in operator_text:

            return {
                "classification":
                    "Special Mission",

                "confidence":
                    "High",

                "reason":
                    f"Special mission operator: {operator}"
            }


    # =====================================
    # 3. AIRCRAFT DESCRIPTION EXPLICITLY
    #    IDENTIFIES A FREIGHTER
    # =====================================

    freighter_keywords = [
        "FREIGHTER",
        "CARGO"
    ]

    for keyword in freighter_keywords:

        if keyword in aircraft_text:

            return {
                "classification":
                    "Dedicated Freighter",

                "confidence":
                    "High",

                "reason":
                    (
                        "Aircraft description "
                        f"indicates freighter: "
                        f"{aircraft_type}"
                    )
            }


    # =====================================
    # 4. FREIGHTER AIRCRAFT VARIANT
    #
    # Examples:
    # 747-412F
    # 767-300F
    # A330-200F
    # 747-400ERF
    # =====================================

    if aircraft_text:

        if re.search(
            r"(F|ERF)$",
            aircraft_text
        ):

            return {
                "classification":
                    "Dedicated Freighter",

                "confidence":
                    "High",

                "reason":
                    (
                        "Aircraft variant indicates "
                        f"freighter: {aircraft_type}"
                    )
            }


    # =====================================
    # 5. CARGO CALLSIGN PREFIX
    # =====================================

    cargo_callsign_prefixes = [
        "FDX",
        "UPS"
    ]

    for prefix in cargo_callsign_prefixes:

        if callsign_text.startswith(prefix):

            return {
                "classification":
                    "Dedicated Freighter",

                "confidence":
                    "High",

                "reason":
                    f"Cargo callsign prefix: {prefix}"
            }


    # =====================================
    # 6. AIRCRAFT TYPES COMMONLY USED
    #    FOR FREIGHT
    #
    # These do NOT prove cargo configuration.
    # =====================================

    possible_freighter_types = [
        "B77L",
        "B748",
        "B744",
        "B763",
        "B752",
        "A306",
        "A332"
    ]

    if icao_text in possible_freighter_types:

        return {
            "classification":
                "Possible Cargo",

            "confidence":
                "Medium",

            "reason":
                (
                    f"Aircraft type {icao_type} "
                    "is commonly used for cargo "
                    "operations, but configuration "
                    "is not confirmed"
                )
        }


    # =====================================
    # 7. KNOWN PASSENGER OPERATORS
    # =====================================

    known_passenger_operators = [
        "JETSTAR",
        "VIRGIN AUSTRALIA",
        "QANTAS AIRWAYS"
    ]

    for passenger_operator in known_passenger_operators:

        if passenger_operator in operator_text:

            return {
                "classification":
                    "Passenger / Non-Cargo",

                "confidence":
                    "Medium",

                "reason":
                    (
                        "Registered operator appears "
                        f"to be passenger airline: "
                        f"{operator}"
                    )
            }


    # =====================================
    # 8. UNKNOWN
    # =====================================

    return {
        "classification":
            "Unknown",

        "confidence":
            "Low",

        "reason":
            (
                "No strong cargo or non-cargo "
                "indicator found"
            )
    }


# =========================================
# MAIN
# =========================================

def main():

    print(
        "Starting Avalon Cargo "
        "flight collection"
    )


    # -------------------------------------
    # Authenticate to OpenSky
    # -------------------------------------

    print("Authenticating to OpenSky...")

    token = get_access_token()

    print("Authentication successful")


    # -------------------------------------
    # Determine yesterday
    # -------------------------------------

    yesterday, begin, end = (
        get_yesterday_timestamps()
    )

    print(
        f"Collecting flights for: "
        f"{yesterday}"
    )

    print(
        f"Unix start: {begin}"
    )

    print(
        f"Unix end:   {end}"
    )


    # -------------------------------------
    # Store all rows
    # -------------------------------------

    rows = []


    # -------------------------------------
    # Aircraft cache
    #
    # Avoid repeated ADSBDB calls for the
    # same aircraft during this run.
    # -------------------------------------

    aircraft_cache = {}


    # =====================================
    # LOOP THROUGH AIRPORTS
    # =====================================

    for (
        airport_code,
        airport_name
    ) in AIRPORTS.items():


        # ---------------------------------
        # ARRIVALS + DEPARTURES
        # ---------------------------------

        for direction in [
            "Arrival",
            "Departure"
        ]:

            print()

            print(
                f"Collecting {direction}s "
                f"for {airport_code} - "
                f"{airport_name}"
            )

            flights = get_flights(
                token=token,
                airport=airport_code,
                direction=direction,
                begin=begin,
                end=end
            )

            print(
                f"Found {len(flights)} "
                f"flights"
            )


            # =============================
            # PROCESS EACH FLIGHT
            # =============================

            for flight in flights:

                icao24 = (
                    flight.get(
                        "icao24"
                    ) or ""
                ).lower()

                callsign = (
                    flight.get(
                        "callsign"
                    ) or ""
                ).strip()


                # -------------------------
                # ADSBDB LOOKUP
                # -------------------------

                aircraft = {}

                if icao24:

                    if (
                        icao24
                        in aircraft_cache
                    ):

                        aircraft = (
                            aircraft_cache[
                                icao24
                            ]
                        )

                    else:

                        print(
                            "Looking up aircraft "
                            f"{icao24} "
                            f"{callsign}"
                        )

                        aircraft = (
                            get_aircraft_details(
                                icao24,
                                callsign
                            )
                        )

                        aircraft_cache[
                            icao24
                        ] = aircraft


                # -------------------------
                # CARGO CLASSIFICATION
                # -------------------------

                cargo_result = classify_cargo(

                    operator=aircraft.get(
                        "registered_owner"
                    ),

                    aircraft_type=aircraft.get(
                        "type"
                    ),

                    icao_type=aircraft.get(
                        "icao_type"
                    ),

                    callsign=callsign
                )


                # -------------------------
                # TIMESTAMPS
                # -------------------------

                first_seen = flight.get(
                    "firstSeen"
                )

                last_seen = flight.get(
                    "lastSeen"
                )


                # =========================
                # BUILD OUTPUT ROW
                # =========================

                rows.append({

                    "CaptureDate":
                        datetime.now(
                            MELBOURNE_TZ
                        ).strftime(
                            "%Y-%m-%d"
                        ),

                    "FlightDate":
                        str(yesterday),

                    "Airport":
                        airport_code,

                    "AirportName":
                        airport_name,

                    "Direction":
                        direction,

                    "ICAO24":
                        icao24,

                    "Callsign":
                        callsign,

                    "OriginAirport":
                        flight.get(
                            "estDepartureAirport"
                        ) or "",

                    "DestinationAirport":
                        flight.get(
                            "estArrivalAirport"
                        ) or "",

                    "FirstSeenUnix":
                        first_seen or "",

                    "LastSeenUnix":
                        last_seen or "",

                    "FirstSeenLocal":
                        unix_to_melbourne(
                            first_seen
                        ),

                    "LastSeenLocal":
                        unix_to_melbourne(
                            last_seen
                        ),

                    "DepartureAirportDistance":
                        flight.get(
                            "estDepartureAirportHorizDistance"
                        ) or "",

                    "ArrivalAirportDistance":
                        flight.get(
                            "estArrivalAirportHorizDistance"
                        ) or "",

                    "Registration":
                        aircraft.get(
                            "registration"
                        ) or "",

                    "Manufacturer":
                        aircraft.get(
                            "manufacturer"
                        ) or "",

                    "AircraftType":
                        aircraft.get(
                            "type"
                        ) or "",

                    "ICAOType":
                        aircraft.get(
                            "icao_type"
                        ) or "",

                    "Operator":
                        aircraft.get(
                            "registered_owner"
                        ) or "",

                    "OperatorCountry":
                        aircraft.get(
                            "registered_owner_country_name"
                        ) or "",

                    "CargoClassification":
                        cargo_result[
                            "classification"
                        ],

                    "CargoConfidence":
                        cargo_result[
                            "confidence"
                        ],

                    "ClassificationReason":
                        cargo_result[
                            "reason"
                        ],

                    "Source":
                        "OpenSky + ADSBDB"
                })


    # =====================================
    # WRITE CSV
    # =====================================

    print()

    print(
        "Total movements collected: "
        f"{len(rows)}"
    )

    os.makedirs(
        "data",
        exist_ok=True
    )


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

        "FirstSeenUnix",
        "LastSeenUnix",

        "FirstSeenLocal",
        "LastSeenLocal",

        "DepartureAirportDistance",
        "ArrivalAirportDistance",

        "Registration",
        "Manufacturer",
        "AircraftType",
        "ICAOType",

        "Operator",
        "OperatorCountry",

        "CargoClassification",
        "CargoConfidence",
        "ClassificationReason",

        "Source"
    ]


    with open(
        OUTPUT_FILE,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )

        writer.writeheader()

        writer.writerows(
            rows
        )


    print(
        f"Saved to {OUTPUT_FILE}"
    )

    print(
        "Unique aircraft looked up: "
        f"{len(aircraft_cache)}"
    )

    print("Finished")


# =========================================
# RUN SCRIPT
# =========================================

if __name__ == "__main__":
    main()
