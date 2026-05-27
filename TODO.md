# TODO

## ReolinkProxy integration (Reolink WLAN/Baichuan)

- [x] Auto-switch Port 9000 / battery cameras to `rtsp://localhost:8554/<NAME>/mainStream`
- [x] Store proxy settings in `camera_config.json`
- [x] Auto-generate `reolinkproxy.env` from `camera_config.json`
- [x] Handle `#` in passwords (URL parsing)
- [x] Use `docker compose` (v2) for starting/stopping ReolinkProxy

## Refactor `main.py` into modules (best practice)

### Goals

- Reduce `main.py` size and cognitive load
- Separate UI, business logic, and I/O
- Improve testability (services/config without GUI)
- Reduce coupling and circular imports

### Current module layout

- `main.py`
  - application startup only
- `main_window.py`
  - `MainWindow`, high-level UI orchestration
- `widgets.py`
  - `CameraListContainer`, `CameraWidget`, `PreviewLabel`
- `dialogs.py`
  - camera edit dialog and discovery dialog
- `stream.py`
  - `CameraThread`, RTSP/OpenCV capture loop, reconnect logic, recording writer
- `discovery.py`
  - `CameraDiscoveryThread`, network scan flow
- `camera_utils.py`
  - RTSP URL parsing/building, ReolinkProxy normalization, TCP/UDP discovery helpers
- `config.py`
  - `camera_config.json` load/save, repair, dedupe, defaults
- `i18n.py`
  - translations and `tr()`
- `ui_resources.py`
  - resource/icon path helpers
- `reolinkproxy_manager.py`
  - CLI helper for generating `reolinkproxy.env`

### Possible future package layout

Use packages only when the flat module layout becomes hard to navigate. A reasonable target would be:

- `main.py`
  - application start only
- `ui/`
  - `main_window.py`, `widgets.py`, `dialogs.py`, `resources.py`
- `services/`
  - `stream.py`, `discovery.py`, `recording.py`
- `core/`
  - `camera_utils.py`, `config.py`, `i18n.py`, optional `models.py`
- `tools/`
  - `reolinkproxy_manager.py`

### Migration strategy 

- [x] Extract config load/save/repair into `config.py`
- [x] Move `MainWindow` into `main_window.py`
- [x] Move reusable UI classes into `widgets.py`
- [x] Move dialogs into `dialogs.py`
- [x] Move worker threads / background logic into `stream.py` and `discovery.py`
- [x] Move RTSP/ReolinkProxy helpers into `camera_utils.py`
- [ ] Consider package directories (`ui/`, `services/`, `core/`) only if modules keep growing
- [x] After extraction:
  - [x] Run `ruff check .`
  - [x] Run Python compile/import checks
  - [ ] Run the GUI app
  - [ ] Manually verify core flows (stream start/stop, recording, snapshot, discovery, config persistence)

### Notes / pitfalls

- Avoid circular imports: keep `ui/*` depending on `services/*`, not the other way around
- Prefer passing dependencies (objects/functions) into UI classes instead of importing singletons
- Keep file I/O and network access out of UI event handlers (use threads/workers)
- If dictionaries are used heavily, consider `dataclass` models to make refactors safer
