# Retained operational lessons

- Python `gi` existing does not prove `Gtk` can load. Import the actual namespace.
- Keep locks under the private runtime. An installed source tree can stay read-only.
- Openbox reparents windows: parse absolute screen coordinates, not frame-relative
  offsets. Calibrated geometry remains a supported-layout condition.
- Native `filehelper` has localized system titles. Match that exact native
  identity and a checked title; never relax arbitrary contact-title matching.
- WCDB may preallocate zero pages beyond its authenticated logical size. Check
  header validity, authenticate active pages and WAL, then check SQLite integrity.
- A durable pre-send checkpoint with `noSend` is distinct from an uncertain
  terminal attempt. Only explicit evidence permits ending the former request;
  the latter remains the original request and is never blindly replayed.
- A single successful live text is bounded acceptance. It does not establish
  media coverage, unattended cleanup, ordinary restart or 24–72 hour stability.
- A passing dependency doctor can coexist with a traced process, changed main
  layout and transient services. Keep structural runtime findings distinct from
  dependencies and historical send acceptance; retain nonzero audit status.
- Persistent service preparation must include private runtime-directory and
  Xauthority creation plus readiness. A generated unit file is not an activated
  service: transient definitions have higher load priority than `/etc` definitions.
- A target's stop job can return before its propagated child stop jobs finish.
  Before replacing runtime authorization, explicitly wait for every affected
  service/socket/connection unit and verify cleanup. This race occurred in the
  isolated systemd migration rehearsal, without restarting the production client.
