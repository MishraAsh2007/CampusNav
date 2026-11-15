# CampusNav frontend: exact spec and merge guide

This describes the Role 2 frontend on branch `role-2-map-ui` (commit `ef1af94` and later): what it looks like, what every part does, and which files carry it. It exists so the backend can be merged in **without changing how the app looks or losing features**.

**Source of truth:** the `role-2-map-ui` branch. Everything under `src/`, `public/`, `index.html`, `tailwind.config.js`, `postcss.config.js`, `vite.config.ts`, `package.json` and `package-lock.json` should come from that branch unchanged. A backend merge should only add `backend/` (and the backend's own docs), plus, if needed, small edits to `src/services/api.ts` described in [section 9](#9-merging-the-backend-what-to-keep).

---

## Contents

1. [Stack and how to run](#1-stack-and-how-to-run)
2. [Design system](#2-design-system)
3. [Screen layout](#3-screen-layout)
4. [Top bar](#4-top-bar)
5. [Left card (trip planner)](#5-left-card-trip-planner)
6. [The map](#6-the-map)
7. [Sheets, judge mode, report flow](#7-sheets-judge-mode-report-flow)
8. [Indoor navigation](#8-indoor-navigation)
9. [Merging the backend: what to keep](#9-merging-the-backend-what-to-keep)
10. [After merging: check it looks and works the same](#10-after-merging-check-it-looks-and-works-the-same)
11. [File map](#11-file-map)

---

## 1. Stack and how to run

- React 18.3, TypeScript 5.6, Vite 5.4, Tailwind CSS 3.4 (PostCSS + autoprefixer).
- Maps: `@vis.gl/react-google-maps` (Google, when a key is set) or `leaflet` 1.9 + `react-leaflet` 4.2 (OpenStreetMap fallback, and all indoor 2D plans).
- Icons: `lucide-react`. Class helpers: `clsx`, `tailwind-merge` (`cx()` in `src/components/ui.tsx`).
- 3D 360° photos: `pannellum` (used directly, not `pannellum-react`). Confetti: `canvas-confetti`.
- Phone HTTPS (needed for GPS): `@vitejs/plugin-basic-ssl`, enabled only by `npm run dev:phone` (`vite --mode https`).

**Keep these versions.** `react-leaflet` must stay at 4.x: version 5 needs React 19. `pannellum-react` must not be added; it needs React 16 and breaks `npm install`.

Run (project folder `HackUmass-2026`):

```powershell
npm install
npm run dev          # http://localhost:5173/
npm run dev:phone    # https://<laptop Wi-Fi IP>:5173/ for phones (accept the certificate)
npm run build        # tsc && vite build: must pass with 0 errors
```

`.env` is git-ignored. Copy `.env.example` to `.env`. Every key is optional; with none, the app runs fully offline:

| Key | Default | Effect |
|---|---|---|
| `VITE_GOOGLE_MAPS_API_KEY` | empty | Google basemap + Google accessibility info in building sheets. Empty or rejected: OpenStreetMap. |
| `VITE_GOOGLE_MAPS_MAP_ID` | `DEMO_MAP_ID` | Needed for Google advanced markers. |
| `VITE_GEMINI_API_KEY`, `VITE_GEMINI_MODEL` | empty, `gemini-3.8-flash` | Gemini route summary. Without it, an instant template summary is shown. |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Role 4 backend. |
| `VITE_ROUTING_API_URL` | same as API base | Role 1 engine (`http://localhost:8001`). |
| `VITE_ROUTING_ENGINE` | `auto` | `auto` / `local` (always in-browser) / `remote`. |
| `VITE_MAP_DEFAULT_LAT`, `_LNG` | `42.3903`, `-72.5275` | Initial map center. |
| `VITE_GROUND_ALTITUDE_M` | 65 | Indoor floor detection from GPS altitude. |
| `VITE_INDOOR_API_URL` | empty | Optional live indoor maps (`GET /indoor/status`, `/indoor/maps/{id}`). |
| `VITE_INDOOR_SAMPLES` | `fallback` | Built-in sample floor plans: `fallback`, `prefer`, `off`. |

URL shortcuts: `?demo` opens judge mode; `?indoor=ilc` (or `dubois-library`, `student-union`, `campus-center`, or any indoor map id) jumps to the room picker for that building. Keyboard: **J** toggles judge mode (ignored while typing).

---

## 2. Design system

The look is "Apple Maps-like": a full-bleed soft map, frosted-glass floating panels, large rounded corners, Inter type, quiet greys with a few strong status colors.

### Colors (`tailwind.config.js`)

| Token | Hex | Used for |
|---|---|---|
| `ink` / `ink-2` / `ink-3` / `ink-4` | `#1d1d1f` / `#424245` / `#6e6e73` / `#8e8e93` | Text, primary buttons, start pin |
| `canvas` | `#f5f5f7` | Page background |
| `hairline` | `rgba(0,0,0,0.08)` | Dividers |
| `brand` / `brand-soft` | `#8f2d35` / `#f7ecec` | Logo circle (UMass maroon) |
| `go` / soft / ink | `#2a9d64` / `#e8f6ee` / `#1c6b45` | Accessible route, "works for you", destination pin, OK entrances |
| `stop` / soft / ink | `#e5484d` / `#fdecec` / `#a8262b` | Closures, stairs, Report button, regular-map route |
| `warn` / soft / ink | `#f0a020` / `#fdf4e3` / `#8a5a00` | Degraded issues, manual doors, warnings |
| `lift` / soft / ink | `#6e56cf` / `#f1eefc` / `#4b389a` | Elevators, reroute banner, Gemini summary |
| `sky` / soft / ink | `#0a84ff` / `#e8f2ff` / `#0758b4` | Focus rings, links, official notices, map picking |

Map-only colors (`src/components/map/scene.ts`, `src/styles/map.css`): high alert `#c4262b`, reported `#f2777a`, road closures and buses `#5b6b8c` / `#eef1f7` / `#33405c`, previous route `#8e8e93`, step-free entrance off `#9a9aa0`.

### Type, radius, shadow, motion

- Font: Inter (Google Fonts, weights 400/500/600, loaded in `index.html`), falling back to SF Pro / Segoe UI. Font features `cv11, ss01, ss03`. Big numbers use `font-display` with `tabular-nums`.
- Radius: pills `rounded-full`; cards `rounded-2xl` / `rounded-3xl`; panels `rounded-4xl` (1.75rem).
- Shadows: `shadow-float` (panels), `shadow-lift` (sheets, dropdowns), `shadow-ring` (1px hairline).
- Easing `ease-soft` = `cubic-bezier(0.22, 1, 0.36, 1)`. Animations: `animate-rise` (slide up 8px + fade, 0.45s), `animate-pop` (scale 0.96→1, 0.28s), `animate-fade`, `animate-shimmer` (loading skeleton).
- `prefers-reduced-motion` turns all animation off (`src/index.css`).

### Component classes (`src/index.css`)

| Class | Definition |
|---|---|
| `.glass` | `bg-white/80 backdrop-blur-2xl backdrop-saturate-150 border border-white/60 shadow-float` (frosted panel) |
| `.card` | `rounded-3xl bg-white shadow-ring` |
| `.eyebrow` | 11px, semibold, uppercase, `tracking-[0.08em]`, `text-ink-4` |
| `.btn` | pill, 13px medium, `active:scale-[0.97]`, 200 ms soft transition |
| `.btn-primary` / `.btn-quiet` / `.btn-ghost` | ink fill / 4% black fill / transparent |
| `.chip` | small pill, 11px |
| `.field` | `rounded-2xl bg-black/[0.04]` input, white with sky ring on focus |
| `.scroll-soft` | thin, faint scrollbar |

Focus: every focusable element shows a 2px `#0a84ff` outline (`*:focus-visible`).

### Accessibility display modes

- **High contrast** (`html.hc`, toggled in the top bar): glass panels turn solid white with 2px black borders and no shadows, grey text darkens, map tiles go greyscale, the accessible route turns `#0047ff` on a black casing, the regular route `#b00000`.
- **Larger text** (`html.text-large`): root font size 112.5%. Everything is rem-based, so the whole UI scales.

---

## 3. Screen layout

Root: `fixed inset-0 overflow-hidden bg-canvas` (`src/App.tsx`). The map fills the screen; everything else floats on top.

**Desktop (≥ 1024 px, Tailwind `lg`)**

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [logo CampusNav]                    [• 5 issues today · 1 high alert][T][Demo][Report] │  top bar, 16px from edges
│ ┌──────────────┐ ┌───────────────────────────┐                           │
│ │ Left card    │ │ 🔎 Search a building or…  │   map (full screen)       │
│ │ 400 px wide  │ └───────────────────────────┘                           │
│ │ top 84 px,   │                                                         │
│ │ bottom 16 px │                                                         │
│ │ scrolls      │                                        [+]              │
│ │              │                [At ILC? Go inside]     [−]              │
│ └──────────────┘                                                         │
└──────────────────────────────────────────────────────────────────────────┘
```

- Left card: `glass fixed lg:left-4 lg:top-[84px] lg:bottom-4 lg:w-[400px] lg:rounded-4xl`, inner area `scroll-soft overflow-y-auto p-4 space-y-4`.
- Destination search: `lg:left-[432px] lg:top-[84px]`, 380 px wide, directly right of the card.
- "Go inside" button: bottom center of the map area (`lg:left-[calc(50%+210px)]`).
- Map zoom buttons: bottom right.

**Phone (< 1024 px)**

- Top bar row stays at the top; the issues pill is hidden below 768 px, and the Demo label below 640 px.
- Destination search: full width under the top bar (`fixed inset-x-3 top-[64px]`).
- Left card becomes a **bottom sheet**: `inset-x-0 bottom-0 max-h-[58vh] rounded-t-4xl`, with a small grey grabber bar at the top.
- "Go inside" button sits just above the sheet (`bottom-[calc(58vh+12px)]`).
- Map fit-to-route padding leaves room for the sheet (bottom 360 px on phones, left 440 px on desktop).

**z-order (low → high):** map 0 · left card 20 · top bar, search, Go-inside 30 · picking banner, judge panel 40 · sheets 50 · indoor views 60 · indoor modal 70.

---

## 4. Top bar

`src/components/TopBar.tsx`, `fixed inset-x-0 top-0 z-30 p-3 sm:p-4`.

- **Left, logo pill** (`glass rounded-full`): 32 px maroon circle with a white accessibility glyph, "CampusNav" (15px semibold), subtitle "Routes that know what's broken today" (11px grey, hidden on small phones). Opens the About sheet.
- **Right**, 6 px apart:
  - **Status pill** (glass, from 768 px): a dot (green with a ping animation when the backend is live, amber when offline), "N issues today · just now", and a red pill "N high alert(s)". Tooltip explains live vs cached.
  - **Display menu** (`T` icon, 40 px glass circle): dropdown with "Larger text", "High contrast" (green ✓ when on), "About and sources".
  - **Demo** (glass, Sparkles icon): toggles judge mode; solid black while open. Tooltip "Judge mode (J)".
  - **Report** (red `bg-stop` pill, warning-triangle icon, white "Report").

---

## 5. Left card (trip planner)

Panels appear in this order (`src/App.tsx`):

### 5.1 Trip planner (`TripPlanner.tsx`)

Two stacked rows on a `bg-black/[0.04] rounded-2xl` background:
- **From** (black dot with a soft ring), **To** (green dot). Each row: small grey label, 15px place name input (combobox), crosshair button "Choose on map" (turns sky blue while picking).
- Dropdown (`shadow-lift rounded-2xl animate-pop`): each result has a code tile (building code, or a bus / parking / pin icon), name and subtitle. Arrow keys + Enter work. Empty: "No match. Try a building code like ILC."
- **Swap** button: small white circle with ↑↓ between the rows.
- While picking on the map, a black pill banner appears at the top center: "Tap the map to set your start · cancel".

Default trip: Student Union → Campus Center upper terrace (`src/data/places.ts`, `DEMO_TRIP`).

### 5.2 Needs menu (`NeedsMenu.tsx`, data in `src/data/profiles.ts`)

Collapsed: a `rounded-3xl bg-black/[0.03]` row with a white accessibility icon tile, the profile name ("Manual wheelchair", plus " · edited" if changed), a summary line ("No stairs · ≤ 6% slope · Smooth · Auto doors") and a chevron.

Expanded (`animate-rise`):
1. **Plain-language box** (Sparkles icon): "Describe it: “sprained ankle, it’s icy”" + **Apply**. Parsed locally (no AI call). Confirms "Set to …" in green or explains which words work.
2. **"I get around with"**: 2-column grid of presets; selected one is solid black:
   - Manual wheelchair (6% max slope, auto doors, smooth) · Power chair or scooter (8.3%) · Crutches or injury (5%, handrails, covered paths) · Walker or cane (5%, short stairs with handrails) · Stroller, cart or luggage (8.3%, no stairs) · Low vision or guide dog (10%, fewer crossings).
3. **"Steepest slope I can manage"** slider: 2–12%, step 0.5, with labels "2% flat", "5% ADA walkway", "8.3% ramp max".
4. **Switches** (iOS-style, green when on, 44×26 px): Wheelchair required · Avoid all stairs · Handrails on any stairs · Smooth surfaces · Prefer covered paths · Automatic doors · Accessible restroom at destination · Fewer street crossings. Each has an icon tile and a grey hint line.
5. Footnote: "Slopes come from USGS 1 m lidar; stairs, handrails and surfaces from OpenStreetMap."

Default needs: manual wheelchair.

### 5.3 Route summary (`RouteSummary.tsx`)

- **Loading:** a shimmering grey skeleton bar.
- **Engine badge** (top right): green "● Main routing engine" when Ash's engine answered, grey "● In-browser router" otherwise.
- **Reroute banner** (purple `bg-lift-soft`, ↻ icon, pops in): "Rerouted around Campus Center concourse elevator (+267 m, about 4 min)".
- **Two big tabs**, side by side:
  - **Works for you** (green ✓): big "3 min", then "131 m · max 1.5%". Selected: green tint with a green ring.
  - **Regular map** (red footprints): "2 min", then "27 steps · max 1.5%". Selected: red tint with a red ring.
- **Skips box:** "Skips **27 steps** that a regular map would use, for 14 m more walking." plus up to 3 lines like "· 27 steps by the Lincoln Campus Center".
- **Arrival line** (green door icon): "Arrive at the southeast entrance (automatic door)."
- **Warnings** (amber rows), e.g. degraded curb cuts, no accessible restroom, bus stop detours.
- **Elevation profile:** small area chart (green for the accessible route, red for the regular one), "↑ 0.3 m · 64–69 m".
- **Footer:** "Hide regular route" / "Compare on map" ghost button, and "In-browser router · 11.2 ms · 2,347 paths".
- **No route** (red `bg-stop-soft` card): "No step-free route available via Main routing engine" (or "No route that fits your needs"), the reason, the UMass **Accessible Van Service** link, and "A regular map would say X min with N steps."

### 5.4 Summary / narrator (`Narrator.tsx`, `src/services/geminiService.ts`)

Purple-to-blue gradient card (`from-lift-soft/70 to-sky-soft/60`): label "✦ Summary" (or "Summary by Gemini"), a **Read aloud** / **Stop** pill, and a 2–4 sentence plain summary ("About 3 min (131 m) from Student Union to Campus Center upper terrace with no stairs. The steepest part is 1.5%… You'll use the Campus Center concourse elevator. It skips 27 steps…"). The template text appears instantly; Gemini replaces it if it answers within 2.5 s.

### 5.5 Directions (`Directions.tsx`)

Collapsible list "DIRECTIONS · N STEPS". Each step: a 32 px icon tile (purple for elevator, red for stairs, amber for slopes ≥ 5%, green flag for arrival, grey otherwise), instruction text, distance. Tapping a step flies the map there; tapping the arrival step at a building with an indoor map opens the indoor room picker.

### 5.6 "On campus today" (`OutageList.tsx`, `IncidentBits.tsx`, `src/services/incidents.ts`)

- Header: "ON CAMPUS TODAY · 5 ISSUES", red "1 high alert" pill, live dot.
- Filter chips: **All · Facilities · Students · Roads & buses**, with counts; selected chip is black.
- Each issue row: colored icon tile (dark red = high alert, red = closed, amber = degraded, slate = road), severity badge (**High alert** red / **Facilities notice** blue shield / **Likely** amber / **Reported** grey), a "Sample" chip for demo data, title, bus line ("Buses detoured:" plus route number chips), source chips ("UMass Facilities", "6 students"), "updated 1 h ago". High-alert rows have a pink tint.
- Ranking: an official notice + student reports of the same problem merge into one **High alert**; then Facilities only; then 3+ student confirmations ("Likely"); then single reports. Newest first within each.
- Footer: "Live from the CampusNav backend" or "Offline: showing cached and sample reports", sync time, a UMass Transit link.

Finally, when the map is on OpenStreetMap, a tiny grey line explains how to switch to Google.

---

## 6. The map

`src/components/MapView.tsx` builds one "scene" (`src/components/map/scene.ts`) and draws it with either `GoogleMapView.tsx` or `LeafletMapView.tsx`. Both renderers must look the same; all styling lives in `scene.ts` and `src/styles/map.css`.

- **Basemap:** Google (light scheme, no default UI, zoom buttons bottom right, POIs not clickable) if a key works; otherwise OSM tiles **desaturated** (`saturate(.55) brightness(1.04) contrast(.95)`) on `#eceae4`, so the route reads first.
- **Accessible route:** green `#2a9d64`, 6 px, on a 10 px white casing. Elevator segments purple `#6e56cf`, 7 px, with a purple "Elevator" tag where you board.
- **Regular-map route** (when "Compare on map" is on): dashed coral `#f2777a`, 4 px; stair segments solid red `#e5484d`, 6 px, with a pink "27 steps" tag.
- **Previous route after a live reroute:** dashed grey, fades after 4 s.
- **Pins:** A = black 30 px circle, B = green, both with white 3 px borders.
- **Buildings:** white pills with the building code and a 16 px status dot: ✓ green (step-free), ! amber (an issue today), – red (limited). Selected building turns black. Hover lifts slightly.
- **Entrances** (zoom ≥ 17, or always for the chosen door / selected building): 14 px dots, green (step-free, powered door), amber (manual door), red (door reported broken), grey (steps). The chosen entrance is 20 px with a green halo.
- **Issues:** 30 px red circles with an icon (elevator, door, cone, slope, path); amber for degraded; slate with a bus icon for road-only closures; **high alerts are 36 px dark red with a double ring and a black "!" badge**; official notices get a blue shield badge. Confirmed in the last 2 h: a pulsing ring. Each issue also draws a faint circle for its affected area (dashed for degraded or road). Bus impact shows as a small grey-blue tag with up to 4 route numbers ("30 · 31 …").
- Picking mode: crosshair cursor.

---

## 7. Sheets, judge mode, report flow

All sheets use `Sheet` from `src/components/ui.tsx`: a bottom sheet on phones (`rounded-t-4xl`, max 88vh), a floating panel on desktop (right side 420 px, or centered 480 px), dim blurred backdrop, title in 22px semibold, round close button, Escape closes.

- **Building sheet** (`BuildingSheet.tsx`, right side): code + name, "Not every floor is reachable without stairs…" warning when relevant, each entrance with a status chip ("Step-free · powered door", "Step-free · manual door", "Door reported broken", "Steps at entrance"), elevators "X of N working", restroom / lactation chips, "Google Maps says" accessibility chips (Google only), "What students have said" quotes, a red link "Report a broken door, elevator or ramp here", and footer buttons **Start here** / **Directions**.
- **Issue sheet** (`ClosureSheet.tsx`, centered): type + "Out of service", severity banner (High alert explains "Two independent sources agree…"), road note or "Walking routes avoid this spot automatically.", bus routes box, Facilities notice cards with dates and a link, student report quotes ("Student reports expire after 48 h unless someone confirms them."), Facilities phone 413-545-6401, footer **Still a problem** / **It works now**.
- **Report sheet** (`ReportSheet.tsx`), the two-tap flow: "What's not working?" → type grid (Elevator, Door opener, Ramp, Path or curb cut, Construction) → status pills (Not working, Blocked (snow, ice, cars), Fixed now) → building/elevator select or "Drop a pin on the map instead" → optional details → preview "Will post as: …" → **Send report**. Success screen: green check, "Thanks. Routes are updating." (closes after 1.4 s). The route reroutes immediately.
- **About sheet** (`AboutSheet.tsx`): "Maps know where ramps are. Not what's broken today.", student research quotes, graph stats (path segments, staircases, steps, walkway km), basemap, Disability Services / Accessible Van link.
- **Judge mode** (`JudgePanel.tsx`): a dark floating panel (`bg-ink/95 rounded-4xl`, bottom center on phones, bottom right on desktop) titled "Judge mode · Break an elevator, watch the route move", with four buttons: **1 · Load trip**, **2 · Break elevator** (red), **3 · Facilities confirms** (blue, makes it a High alert), **4 · Fix it** (green), a monospace log of the last 5 network/route events with timings, and **Reset**. The route visibly moves with no page refresh.

---

## 8. Indoor navigation

All indoor code lives in `src/components/indoor/` (plus `src/services/voiceEngine.ts`). It is self-contained; App only renders `<IndoorFlow>` and the search box.

**Flow:** outdoor route ends at a building with an indoor map → green pill **"🏛️ At ILC? Go inside to S220"** → **arrival modal** ("Outdoor route complete · You have arrived at … Want to access inside?", room search, two big buttons **2D Floor Plan · Bird's Eye View** (black) and **3D Immersive View · First-person, wheelchair height** (blue)) → indoor 2D ↔ 3D.

**Universal search box** (top of the map, "Search a building or room, e.g. ILC 311"): finds buildings, floors ("Du Bois Floor 3", or "isn't mapped yet") and rooms ("ILC 311", "ballroom", "restroom") across every building with an indoor map. Picking a room sets the destination and preselects the room.

**2D floor plan** (`IndoorNavigator2D.jsx`, Leaflet `CRS.Simple` over the plan image):
- Compact header: round **←** back button, dark title card ("INTEGRATIVE LEARNING CENTER / To S220 Classroom", truncated), and a horizontal pill **floor picker** (1 · 2 · 3; blue dot = floors on your route; scrolls for tall buildings).
- **Toolbar pill** under the header: 📍 **Locate** (shows "±10 m" when on), **Follow**, floor chip "Fl 2" (from GPS altitude), 🔎 room (opens the room search), ⚠️ route warnings (phones).
- Route: white casing with a faint blue dotted full path, the current step in solid blue, completed steps green, a green 🏁 destination flag, and a pulsing blue GPS dot with an accuracy circle and a "📍 Current location · ±10 m · Floor 2" label (or a dark "Current location · step 1" marker without GPS).
- Bottom right: round black **3D** button above the zoom stack (+, −, ◎ center on me, ⤢ whole floor).
- Plans: the built-in sample layouts say "Sample layout · not to scale"; real map files without a usable image get a drawn schematic ("Schematic from building data").

**3D view** (`IndoorNavigator.jsx`, `IndoorSimulation.jsx`, `PanoramaView.jsx`): a 360° photo when a step has one, otherwise a simulated first-person corridor at seated eye height (signs, doors, elevators). Same header and toolbar; distance HUD top right ("AHEAD 60 ft"); round **2D** button above the zoom (+/−, 1.0×); **Auto** and **⬆ Hold to roll** buttons bottom left; WASD / arrow keys to drive, Space for doors.

**Step panel** (`IndoorStepPanel.jsx`, shared by 2D and 3D): white card at the bottom (bottom sheet on phones, 400 px card on desktop), "STEP 1 OF 3 · 60 FT LEFT", **🔊 Voice on**, **All steps** / **Hide steps**, a segmented progress bar, the current step in large text with a blue icon tile, and **Back · Repeat · Next step** (Done on the last step). Keys N / P / R. The voice (device default or Google US English) reads each step; switching 2D/3D keeps your place.

**GPS:** follow mode advances steps as you walk, reroutes after 4 s off route ("Recalculating route…"), switches floors from altitude (Floor 1 when the phone reports none). Location requires HTTPS on phones (`npm run dev:phone`).

**Data-driven:** buildings come from `data/indoor/*.json` (team IndoorMap v1 format), the indoor API, or the 4 built-in samples (`floorPlans.js` → `sampleMaps.js`). See the README section "Adding a building (dorms included): no frontend change".

---

## 9. Merging the backend: what to keep

### Do

- Take **all of `src/`, `public/`, `index.html`, the Tailwind/PostCSS/Vite configs and `package.json`/`package-lock.json` from `role-2-map-ui`**. In merge conflicts on those files, choose the `role-2-map-ui` side.
- Add the backend in `backend/` only.
- Run `npm install` after merging, then `npm run build` (must pass) and the checks in [section 10](#10-after-merging-check-it-looks-and-works-the-same).

### Don't

- **Don't copy `src/` from the `backend` or `frontend-backend` branches.** They contain an older copy of this frontend (no indoor navigation, no engine badge, no data-driven buildings, old `RouteSummary`). Merging their `src/` over this one is how features get lost.
- **Don't copy `frontend/` from `routing-scraper`**: it is another older snapshot. Only its `data/indoor/*.json` files are useful (drop them into `data/indoor/`).
- Don't add the admin key (`CAMPUSNAV_ADMIN_KEY`) to frontend code or `.env` for the frontend.
- Don't change these without checking every user: `src/types/index.ts`, `src/services/api.ts` exports, `tailwind.config.js` colors, `src/index.css`, `src/styles/map.css`, `src/components/map/scene.ts`.

### The frontend ↔ backend contract (already implemented in `src/services/api.ts`)

| Frontend call | Backend endpoint | Notes |
|---|---|---|
| `checkBackendHealth()` every 15 s | `GET /health` | Only the HTTP status matters. Also checks `GET {VITE_ROUTING_API_URL}/health` when the engine is on another port. |
| `getClosures()` every 5 s | `GET /closures` (falls back to `/api/closures`) | Each record is normalized by `normalizeClosure()`: `status` `working/fixed/repaired`→repaired, `degraded`→degraded, else closed; `source` official/verified kept, everything else → community; `details`→description. Unknown extra fields are ignored. |
| `getBuildings()` once | `GET /buildings` (falls back to `/api/buildings` on 404) | `normalizeBuilding()` accepts the backend shape (flat `lat`/`lng`, `hasAutoDoorOpener`, `IsKeyCardRequired`, `isAccessibleToAllFloors`, `bathrooms[]`, elevators array). Built-in buildings the backend lacks are kept. |
| `submitUserReport()` | `POST /community-reports` (then `/reports`, then `/api/report`) | Body is exactly `{lat, lng, type, radius}` so every backend version accepts it. Title, description and connector id are kept in the browser and re-attached when the report comes back. |
| `confirmClosure()` | `POST /community-reports/{id}/confirm` | Fire and forget. |
| `planRoutes()` | `POST {VITE_ROUTING_API_URL}/api/route` (Ash's engine) | Not the backend. Falls back to the in-browser router. |

Kept in the browser on purpose (the backend has no endpoint for them): "It works now" / "Fixed now" reports, door-opener (`automatic_door`) reports, and the judge demo's simulated Facilities notice. The frontend never calls `/official-reports`; Role 3 posts those.

If the backend changes shape, **adapt `normalizeClosure()` / `normalizeBuilding()` in `api.ts`** rather than changing types or components.

### Things that silently break if removed

- `App.tsx` needs these exports and shapes from `api.ts`: `getClosures` → `{closures, live, ms}`; `submitUserReport` → `{closure, live, ms, browserOnly?}`; `confirmClosure`, `markClosureResolved`, `resetClosures`, `addLocalOfficialNotice` → `Closure[]` (synchronous); `planRoutes(origin, destination, prefs, closures, buildings, indoorIntent)` → `PlanResult` with `accessible`, `standard`, `failure`, `notes`, `engine`, `endEndpointId`, `startEndpointId`, `arrivalPoint`; `checkBackendHealth` → boolean; `closuresSignature`, `getBuildings`; types `PlanResult`, `IndoorIntent`.
- Type unions used by data and UI: `BarrierType` must keep `automatic_door`; `Building.category` must keep `administration` (Whitmore); elevator status must keep `none` (Boyden).
- `connector_id: 'cc-concourse-elevator'` links the judge demo's elevator report to the graph's elevator edge. Without it the demo's "Break elevator" no longer moves the route.
- Id prefixes mean something: `local-…` = created in this browser (not confirmed on the backend), `demo-…` = sample data (shown with a "Sample" chip).
- `public/data/campusGraph.json` and `busRoutes.json` must stay (built by `scripts/build-campus-graph.mjs` and `scripts/build-bus-routes.mjs`).
- Backend CORS must allow the frontend origin: `http://localhost:5173`, `http://127.0.0.1:5173`, and for phones `https://<laptop IP>:5173`.

---

## 10. After merging: check it looks and works the same

Run `npm run dev`, open `http://localhost:5173/` on a desktop window and a phone-sized window (DevTools device mode, 390×844).

1. **First load:** frosted top bar (maroon logo, "CampusNav"), left card with Student Union → Campus Center upper terrace, a **green route with a purple Elevator segment**, a dashed coral regular route with a red "27 steps" tag, building pills with green ✓ dots, five issue markers including one large dark-red high alert at the ILC.
2. **Route card:** "In-browser router" badge (green "Main routing engine" when Ash's engine runs), tabs "Works for you 3 min" and "Regular map 2 min · 27 steps", the Skips box, the elevation chart, the purple-blue Summary card with Read aloud.
3. **On campus today:** 5 issues, 1 high alert, filter chips work.
4. **Backend on:** the status pill dot turns green and pings; reports sent from the Report sheet appear within 5 s; closures from the backend appear on the map.
5. **Judge mode (J):** Break elevator → route moves (old line fades grey), purple "Rerouted around…" banner; Facilities confirms → High alert; Fix it → route snaps back.
6. **Display menu:** Larger text scales everything; High contrast gives white panels with black borders and a blue route.
7. **Indoor:** open `/?indoor=ilc`, pick S220, choose 2D: header with ←, floor picker 1·2·3, toolbar pill, blue route, round **3D** button above the zoom buttons, step panel with Back / Repeat / Next step. 3D shows the simulated corridor with the round **2D** button. Search "ILC 311" in the top search box.
8. **Phone width:** the left card is a bottom sheet (58% height) with a grabber; nothing overlaps the step text indoors.
9. `npm run build` finishes with no TypeScript errors.

If any of these differ, compare the file in question with `role-2-map-ui` (`git diff origin/role-2-map-ui -- <file>`).

---

## 11. File map

| Area | Files |
|---|---|
| App shell, state, polling, layout | `src/App.tsx`, `src/main.tsx`, `index.html` |
| Design tokens and global styles | `tailwind.config.js`, `src/index.css`, `src/styles/map.css` |
| UI primitives | `src/components/ui.tsx` (`cx`, `Sheet`, `Switch`, `Stat`, `useClickOutside`) |
| Top bar | `src/components/TopBar.tsx` |
| Trip planner and needs | `src/components/TripPlanner.tsx`, `NeedsMenu.tsx`, `src/data/profiles.ts`, `src/data/places.ts` |
| Route card, summary, directions | `src/components/RouteSummary.tsx`, `ElevationProfile.tsx`, `Narrator.tsx`, `Directions.tsx`, `src/services/geminiService.ts`, `audioService.ts`, `voiceEngine.ts` |
| Issues | `src/components/OutageList.tsx`, `IncidentBits.tsx`, `ClosureSheet.tsx`, `src/services/incidents.ts`, `src/data/mockClosures.ts` |
| Buildings, reports, about, demo | `src/components/BuildingSheet.tsx`, `GooglePlaceAccess.tsx`, `ReportSheet.tsx`, `AboutSheet.tsx`, `JudgePanel.tsx`, `src/data/mockBuildings.ts` |
| Map | `src/components/MapView.tsx`, `src/components/map/` (`MapsProvider.tsx`, `GoogleMapView.tsx`, `LeafletMapView.tsx`, `scene.ts`, `icons.ts`, `config.ts`) |
| Data and routing gateway | `src/services/api.ts` (backend + engine calls, offline store), `src/services/routingEngine.ts` (in-browser router), `src/types/index.ts` |
| Indoor | `src/components/indoor/` (`IndoorFlow.jsx` state machine, `IndoorNavigator2D.jsx`, `IndoorNavigator.jsx`, `IndoorSimulation.jsx`, `PanoramaView.jsx`, `IndoorStepPanel.jsx`, `BuildingTransitionModal.jsx`, `DestinationInput.jsx`, `ViewToggleFab.jsx`, `layout.js`, `indoorCatalog.js`, `indoorModel.js`, `indoorRouter.js`, `sampleMaps.js`, `floorPlans.js`, `floorCalibration.js`, `indoorGps.js`, `altitudeFloor.js`, `RouteWarningsPanel.jsx`, `useSpeech.js`, `mockIndoorData.js`), `indoor.html` + `src/indoor-preview.jsx` (standalone 3D preview) |
| Static data | `public/data/campusGraph.json`, `public/data/busRoutes.json` |
| Data build scripts | `scripts/build-campus-graph.mjs`, `build-bus-routes.mjs`, `curated-connectors.json`, `check-demo.mjs`, `analyze-graph.mjs` |
| Contracts | `contracts/*.contract.json`, `contracts/README.md` |
