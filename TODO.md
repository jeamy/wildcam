# TODO

## Refactor `main.py` into modules (best practice)

### Goals

- Reduce `main.py` size and cognitive load
- Separate UI, business logic, and I/O
- Improve testability (services/config without GUI)
- Reduce coupling and circular imports

### Proposed module layout

- `app.py`
  - Application start (`QApplication`), wiring, entry point
- `ui/`
  - `ui/main_window.py` (main window, menus, layout wiring)
  - `ui/camera_widget.py` (`CameraWidget`, frame update/render + controls)
  - `ui/dialogs.py` (add/edit camera dialogs, settings dialogs)
- `services/`
  - `services/discovery.py` (`CameraDiscoveryThread`, scan logic)
  - `services/stream.py` (RTSP/OpenCV capture loop, reconnect logic)
  - `services/recording.py` (recording, snapshots)
- `config.py`
  - Load/save `camera_config.json`, defaults, validation
- `models.py` (optional)
  - `dataclass` models such as `Camera`, typed config structures
- `constants.py`
  - Shared constants (paths, defaults, ports, keys)

### Migration strategy 

- [ ] Extract the easiest, least-coupled code first (e.g. `config.py` + `models.py`)
- [ ] Move one UI class at a time into `ui/*` and keep imports stable
- [ ] Move worker threads / background logic into `services/*`
- [ ] After each extraction:
  - [ ] Run the app
  - [ ] Verify core flows (stream start/stop, recording, snapshot, discovery, config persistence)

### Notes / pitfalls

- Avoid circular imports: keep `ui/*` depending on `services/*`, not the other way around
- Prefer passing dependencies (objects/functions) into UI classes instead of importing singletons
- Keep file I/O and network access out of UI event handlers (use threads/workers)
- If dictionaries are used heavily, consider `dataclass` models to make refactors safer
