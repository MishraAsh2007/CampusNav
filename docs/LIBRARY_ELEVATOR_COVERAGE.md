# Du Bois elevator coverage

The GIS catalog contains **one mapped elevator location**, `umass-elevator-121`.
`mapped_locations: 1` is a count of source map points, not a count of physical
elevator cars. `total_count` and `working_count` remain null because that source
does not establish them. Both the central and expanded building catalogs retain
this distinction.

The project owner reports **five cars, all serving all floors now**. That current
report supersedes the historical express/local pattern for this project's planning.
It is recorded here separately from the GIS catalog. The car-to-plan-position
mapping and current operational status are still missing from the scraped records.
The teammate's ground-truth JSON will be combined with this source work later.

The existing indoor pilot represents elevator travel with one aggregate asset,
`library-elevator-main`, labeled "Library elevator group (individual cars not
mapped)". Its 27 elevator edges all reference that asset. This graph is a
simplified pilot; it does not establish that any particular car serves every
modeled floor. The GIS point does not prove that all physical cars share one bank.

## Additional sources collected

- [StackMap entrance-floor view](https://umass.stackmap.com/explore/16?c=55):
  the source image shows five elevator symbols, arranged two on one side and
  three on the other. Its two interactive regions cover groups of symbols;
  `place-51` and `place-52` are source region IDs, not physical car numbers.
- [UMass-hosted directory, July 9, 2007](https://people.umass.edu/ref/clipboardmessages/directory.pdf):
  page 2 explicitly identifies cars 1–5. Its old express/local service division
  is historical evidence only and is **not applied to current routes**.
- [Library interruption item 424](https://umass.sharepoint.com/sites/impactnotices/Lists/Service%20Interruption%20Notices/DispForm.aspx?ID=424):
  the authenticated official source describes an August 21, 2025 inspection of
  car #5. This is an archived inspection, not a current outage or floor-service
  confirmation. Sanitized research records remain under `data/private`.

The public collector is `campus_notices/library_elevators.py`. Run:

```powershell
.\.venv\Scripts\python.exe -m scripts.refresh_library_elevators
```

It saves `data/library_elevator_sources.json`: 26 explicit floor references,
52 floor-local elevator regions across those pages, and five historical car
references. **52 regions does not mean 52 elevators.** Coordinates remain in each
source image; no geographic coordinates, car-to-region matches or routing edges
are inferred. A failed refresh retains the previous published evidence file.
The currently linked StackMap set still omits a third-floor image.

## Current routing limitation

A closure matched to this aggregate asset currently removes all its modeled
rides. Therefore the router cannot distinguish "one car is down, others still
serve this floor" from "the whole group is unavailable". An unmatched car ID
cannot establish a working alternative either. Do not describe this as verified
per-car outage routing.

To implement per-car alternatives, collect:

- Current car IDs matched to their bank/landing positions, including confirmation
  that the historical numbering still matches today's physical cars.
- Shared hall connections to those landings, including entrance/LL floor labels.
- How maintenance notices identify a car versus an entire bank, with timestamps.
- Any restrictions such as express service, staff-only access or scheduled access.

Role 3 can then normalize a notice to the documented car or bank ID. Role 1 can
give each documented car its own stop connections and block only affected rides;
bank-wide closures must still block all documented member cars. A five-car count
alone is insufficient to construct those connections.

The current Oak, Campus Center and Student Union scope is documented separately
in [Expanded indoor pilots](EXPANDED_INDOOR_PILOTS.md).
