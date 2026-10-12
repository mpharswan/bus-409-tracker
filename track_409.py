#!/usr/bin/env python3
"""
Route 409 delay tracker (Eyre Square <-> Parkmore, Galway, Bus Eireann).

Polls the NTA GTFS-Realtime feed every minute and logs, for every 409 trip,
the scheduled vs actual departure from the first stop and arrival at the last
stop, in both directions. Results go to 409_delays.csv next to this script.

Usage:
    python track_409.py YOUR_NTA_API_KEY        # runs until Ctrl+C
    NTA_API_KEY=... python track_409.py --minutes 55   # runs 55 min then exits

Get a free key at https://developer.nationaltransport.ie (subscribe to the
GTFS-R product). Needs only Python 3.8+, no extra packages.
Leave it running (computer awake). Stop with Ctrl+C; restarting resumes safely.
"""

import csv
import io
import json
import os
import sys
import time
import urllib.request
import zipfile
from datetime import datetime, timedelta

ROUTE = "409"
POLL_SECONDS = 60
GTFS_STATIC_URL = "https://www.transportforireland.ie/transitData/Data/GTFS_Realtime.zip"
GTFS_RT_URL = "https://api.nationaltransport.ie/gtfsr/v2/TripUpdates?format=json"
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "409_state.json")
CSV_FILE = os.path.join(HERE, "409_delays.csv")
STATIC_REFRESH_HOURS = 24
TRIPS_CACHE = os.path.join(HERE, "409_trips.json")


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def fetch(url, headers=None, timeout=60):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "track_409"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def read_csv_from_zip(zf, name):
    with zf.open(name) as f:
        return csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))


def load_static():
    """Return {trip_id: info} for route 409 trips from the GTFS schedule."""
    log("Downloading timetable (GTFS schedule)...")
    zf = zipfile.ZipFile(io.BytesIO(fetch(GTFS_STATIC_URL, timeout=300)))

    route_ids = {r["route_id"] for r in read_csv_from_zip(zf, "routes.txt")
                 if r.get("route_short_name", "").strip() == ROUTE}
    if not route_ids:
        sys.exit(f"Route {ROUTE} not found in the timetable file.")

    trips = {}
    for t in read_csv_from_zip(zf, "trips.txt"):
        if t["route_id"] in route_ids:
            trips[t["trip_id"]] = {
                "direction_id": t.get("direction_id", ""),
                "headsign": t.get("trip_headsign", ""),
                "first": None, "last": None,
            }

    for st in read_csv_from_zip(zf, "stop_times.txt"):
        info = trips.get(st["trip_id"])
        if not info:
            continue
        seq = int(st["stop_sequence"])
        row = (seq, st["stop_id"], st["departure_time"] or st["arrival_time"],
               st["arrival_time"] or st["departure_time"])
        if info["first"] is None or seq < info["first"][0]:
            info["first"] = row
        if info["last"] is None or seq > info["last"][0]:
            info["last"] = row

    stop_names = {s["stop_id"]: s.get("stop_name", "")
                  for s in read_csv_from_zip(zf, "stops.txt")}
    for info in trips.values():
        info["first_name"] = stop_names.get(info["first"][1], info["first"][1])
        info["last_name"] = stop_names.get(info["last"][1], info["last"][1])
    log(f"Loaded {len(trips)} scheduled 409 trips.")
    return trips


def gtfs_time(date_str, hhmmss):
    """GTFS times can exceed 24:00:00; resolve against the service date."""
    h, m, s = (int(x) for x in hhmmss.split(":"))
    base = datetime.strptime(date_str, "%Y%m%d")
    return base + timedelta(hours=h, minutes=m, seconds=s)


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)


def write_csv(state):
    cols = ["service_date", "direction", "from_stop", "to_stop", "trip_id",
            "scheduled_departure", "actual_departure", "departure_delay_min",
            "scheduled_arrival", "actual_arrival", "arrival_delay_min",
            "status", "last_seen"]
    rows = sorted(state.values(), key=lambda r: (r["service_date"], r["scheduled_departure"]))
    tmp = CSV_FILE + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    try:
        os.replace(tmp, CSV_FILE)
    except PermissionError:
        log("CSV is open in another program (e.g. Excel); will update next time.")


def poll(api_key, trips, state):
    data = json.loads(fetch(GTFS_RT_URL, headers={
        "x-api-key": api_key, "Cache-Control": "no-cache", "User-Agent": "track_409"}))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    seen = 0
    for ent in data.get("entity", []):
        tu = ent.get("trip_update") or {}
        trip = tu.get("trip") or {}
        info = trips.get(trip.get("trip_id"))
        if not info:
            continue
        seen += 1
        date = trip.get("start_date") or datetime.now().strftime("%Y%m%d")
        key = f"{date}|{trip['trip_id']}"
        sched_dep = gtfs_time(date, info["first"][2])
        sched_arr = gtfs_time(date, info["last"][3])
        rec = state.setdefault(key, {
            "service_date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
            "direction": info["headsign"] or f"direction {info['direction_id']}",
            "from_stop": info["first_name"], "to_stop": info["last_name"],
            "trip_id": trip["trip_id"],
            "scheduled_departure": sched_dep.strftime("%Y-%m-%d %H:%M"),
            "scheduled_arrival": sched_arr.strftime("%Y-%m-%d %H:%M"),
            "actual_departure": "", "departure_delay_min": "",
            "actual_arrival": "", "arrival_delay_min": "",
            "status": "",
        })
        rec["last_seen"] = now
        if trip.get("schedule_relationship") == "CANCELED":
            rec["status"] = "cancelled"
            continue
        rec["status"] = "tracked"

        updates = tu.get("stop_time_update") or []
        if not updates:
            continue
        first_seq, last_seq = info["first"][0], info["last"][0]
        for u in updates:
            seq = int(u.get("stop_sequence", -1))
            ev = u.get("departure") or u.get("arrival") or {}
            if "delay" not in ev:
                continue
            delay = int(ev["delay"])
            # Departure: lock in the delay reported at the first stop, or the
            # earliest delay we saw if the bus was already past it.
            if seq == first_seq or (rec["departure_delay_min"] == "" and seq <= first_seq + 1):
                rec["departure_delay_min"] = round(delay / 60, 1)
                rec["actual_departure"] = (sched_dep + timedelta(seconds=delay)).strftime("%Y-%m-%d %H:%M")
        # Arrival: keep the most recent delay estimate; the last one seen before
        # the trip leaves the feed is effectively the actual arrival delay.
        last_u = max(updates, key=lambda u: int(u.get("stop_sequence", -1)))
        ev = last_u.get("arrival") or last_u.get("departure") or {}
        if "delay" in ev:
            d = int(ev["delay"])
            if int(last_u.get("stop_sequence", -1)) <= last_seq:
                rec["arrival_delay_min"] = round(d / 60, 1)
                rec["actual_arrival"] = (sched_arr + timedelta(seconds=d)).strftime("%Y-%m-%d %H:%M")
    return seen


def get_trips():
    """Load route 409 trips, reusing today's cached copy when available."""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with open(TRIPS_CACHE, encoding="utf-8") as f:
            cached = json.load(f)
        if cached.get("date") == today:
            log(f"Using cached timetable ({len(cached['trips'])} trips).")
            return cached["trips"]
    except (OSError, ValueError, KeyError):
        pass
    trips = load_static()
    with open(TRIPS_CACHE, "w", encoding="utf-8") as f:
        json.dump({"date": today, "trips": trips}, f)
    return trips


def main():
    args = sys.argv[1:]
    run_minutes = None
    if "--minutes" in args:
        i = args.index("--minutes")
        run_minutes = float(args[i + 1])
        del args[i:i + 2]
    api_key = (args[0] if args else os.environ.get("NTA_API_KEY", "")).strip()
    if not api_key:
        key_file = os.path.join(HERE, "nta_key.txt")
        try:
            with open(key_file, encoding="utf-8-sig") as f:
                api_key = f.read().strip()
        except OSError:
            pass
    if not api_key:
        sys.exit("No API key: set NTA_API_KEY, put it in nta_key.txt next to "
                 "this script, or run: python track_409.py YOUR_NTA_API_KEY")

    trips = get_trips()
    loaded_at = time.time()
    started = time.time()
    state = load_state()
    log(f"Tracking route {ROUTE}. Writing to {CSV_FILE}.")
    while True:
        try:
            if time.time() - loaded_at > STATIC_REFRESH_HOURS * 3600:
                trips = get_trips()
                loaded_at = time.time()
            n = poll(api_key, trips, state)
            save_state(state)
            write_csv(state)
            log(f"{n} live 409 trips in feed; {len(state)} trips logged so far.")
        except KeyboardInterrupt:
            raise
        except Exception as e:  # network blips, API hiccups: keep going
            log(f"Error: {e} (will retry)")
        if run_minutes is not None and time.time() - started >= run_minutes * 60:
            log("Run time limit reached; stopping.")
            return
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Stopped.")
