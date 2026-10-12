# Route 409 delay tracker

Logs scheduled vs actual times for Bus Éireann route 409 (Eyre Square ↔ Parkmore, Galway) from the NTA real-time feed.

- Runs automatically every hour from 6 AM to midnight Galway time (GitHub Actions, `.github/workflows/track.yml`).
- Results are saved to **`409_delays.csv`** in this repository after each run.
- Needs a repository secret named `NTA_API_KEY` holding your key from https://developer.nationaltransport.ie.

## Columns in 409_delays.csv

| Column | Meaning |
|---|---|
| service_date | Date the trip ran |
| direction | Destination shown on the bus |
| from_stop / to_stop | First and last stop of the trip |
| scheduled_departure / actual_departure | Timetabled vs real departure from the first stop |
| departure_delay_min | Minutes late (negative = early) leaving the first stop |
| scheduled_arrival / actual_arrival | Timetabled vs real arrival at the last stop |
| arrival_delay_min | Minutes late (negative = early) at the last stop |
| status | `tracked` or `cancelled` |

Actual times are the delays reported by Bus Éireann's live feed. Blank actual times mean no live data came through for that trip.
