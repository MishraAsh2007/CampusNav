# Test this checkout on a phone with Vite

Use the checkout containing the latest work. On this laptop it is:
`C:\Users\Jash_\Projects\active\CampusNavigation\tmp\main-integration`.
These commands do not push to GitHub or deploy to Vercel.

In the first PowerShell terminal:

```powershell
cd C:\Users\Jash_\Projects\active\CampusNavigation\tmp\main-integration
.\start-server.cmd --memory
```

In a second terminal, in the same folder:

```powershell
npm.cmd --prefix frontend run dev:phone
```

Open the Wi-Fi **Network** HTTPS address printed by Vite on the phone. Both
devices must be on the same network; keep the laptop awake and both servers
running. Ctrl+C stops each server. Phone mode forces the local same-origin API
proxy and turns sample data off, even if `.env.local` names a deployed backend.
The backend stays on `127.0.0.1:8000`; Vite exposes the UI and proxies API requests
through port 5173. Memory mode keeps test reports out of MongoDB and discards
them when the backend restarts. The scraper's saved data may still be displayed.

## What to test

- Outdoor-to-indoor handoff: plan Student Union → Integrative Learning Center,
  then **Go inside**. The routed southwest doorway supplies the floor-2 start.
  Pick N211 (same floor) or N111/N155 (floor 1, requiring an elevator).
- Direct indoor testing: append `/?indoor=ilc`. This opens the indoor picker;
  it does not prove an outdoor arrival. If no matched arrival exists, choose
  **Start a separate indoor route from a known landmark**, select
  **Southwest entrance - floor 2**, and choose the destination.
- Check map focus/full-floor view, room outlines, Next/Back, automatic floor
  switching at the elevator, voice on/off, and Repeat. Voice is on by default;
  taps on Next/Back read the selected instruction.
- Open **Map options** and switch between **Detailed map** (default), **Simple map**
  and **Original drawing**. The selected step and route should stay aligned.
  Floor 2 should show the **N151 auditorium — Upper level** outline in both drawn views.
- Drag the indoor map with one finger; pinch with two fingers to zoom. The +/−
  controls also zoom. Full floor / Focus step resets the view. A keyboard can pan
  with arrow keys and reset with Home while the map is focused.
- Pull down the **More map** handle (or tap it) to collapse the directions.
  Pull up or tap **Show directions** to expand them again. The compact card keeps
  the current step and Next available while showing more map.
- Test community reports against the temporary memory backend if needed.

## Limits of this setup

Vite basic-ssl generates a **self-signed development certificate**. The phone may
show a certificate warning, and a browser that does not trust that certificate
may deny GPS. A working HTTPS URL alone does not establish a trusted secure
context. Trusted HTTPS is needed to test the outdoor **Use my location** feature
reliably. Do not disable browser security or the Windows firewall.

The current source-plan indoor guide does **not** offer continuous indoor GPS or
a Locate button. It follows the selected instruction landmark. The older Locate
instructions apply to an earlier UI; serving it over HTTPS does not supply indoor
positioning, floor detection or room-level accuracy.

Campus/guest Wi-Fi may isolate devices. A timeout can also mean an inbound
firewall rule is needed; a successful request from the laptop alone does not
verify phone reachability. Keep any firewall exception scoped to the dev server
port and trusted network rather than disabling the firewall.

Sources: [Vite basic-ssl](https://github.com/vitejs/vite-plugin-basic-ssl),
[Geolocation secure-context requirement](https://developer.mozilla.org/en-US/docs/Web/API/Geolocation_API).
