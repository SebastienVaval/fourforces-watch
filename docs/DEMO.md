# Demo guide (2 minutes, no slides)

## Before you go on stage (T-5 min)
1. Start with demo mode on:
   `DEMO_MODE=1 uvicorn app:app --port 8000`, or the hosted URL with `DEMO_MODE=1`.
2. Make sure `XAI_API_KEY` is set, so Grok checks the cameras and writes the messages. Wait about 30 s for the first
   refresh, until the **Status** tab shows feeds as `live` and "cameras checked" > 0.
3. Open http://localhost:8000. Check that:
   - the orange **DEMO / SIMULATED** banner is visible;
   - 5 cameras with a yellow ring are red.
4. Check the live hooks on the **Status** and **Map** tabs:
   - **NWS Coastal Flood Statement** for Miami-Dade, active until Sun Oct 11, 12:00 PM ET. If it has expired, say "no
     active NWS alert right now" and lean on the tide instead.
   - **Tide card (NOAA Virginia Key):** about +0.8 ft above forecast this morning. Projected next high tide around
     9:30 PM ET is ≈3.56 ft MLLW, just above the NWS minor-flood level of 3.53 ft.

## Script

| Time | Screen | Say |
|---|---|---|
| 0:00 | Map | "Miami floods on sunny days. Right now the National Weather Service has a **coastal flood statement** out for Miami-Dade: water on low-lying roads through Sunday morning." |
| 0:15 | Tide card | "NOAA's Virginia Key gauge is running **0.8 feet above the tide forecast**. Add that to tonight's high tide and we cross the **minor-flood line**. The data is public, but it's spread across 8 agencies, and nobody is watching the 389 traffic cameras." |
| 0:35 | Click a red, yellow-ringed camera | "So we let Grok watch them. This is a **simulated** dry-day image, an archived 2016 Miami king-tide photo, clearly labelled. Grok looks at it live: water on road, 90% confidence." |
| 0:55 | Click a real camera → "Check now with Grok" | "And this is a live FDOT camera, analysed right now. Snapshots are never stored." |
| 1:10 | Toggle Water/Air/Land/Fire, then Hazard Board | "Four forces, one schema: canals, storms, evacuation zones, heat index. Every neighborhood gets a status and a message in **English, Spanish and Haitian Creole**." Click Kreyòl. |
| 1:35 | Open data tab → `/api/cap` | "Everything is an open API: JSON, GeoJSON and **CAP 1.2**, the alerting standard. Another city reuses it with one YAML file." |
| 1:50 | Status tab | "Live feed health, MIT license, built today. Not an official warning system: it points you to the official ones." |

## If something breaks
- **No key or the xAI API is down:** cameras stay grey and the board shows template messages. Say so and show the
  tide, NWS and canal layers. Those don't need AI.
- **Wi-Fi down:** have the backup video ready.
