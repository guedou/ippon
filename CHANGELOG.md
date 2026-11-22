# Changelog

## 0.2.1 — 2026-11-22

- Use a single raylib pointer stream for touchscreen taps and mouse clicks.
- Keep valid taps through weather/source refreshes and tolerate small finger
  movement while still cancelling drags and releases on a different button.
- Start fullscreen automatically on Raspberry Pi, with an explicit windowed
  option, and keep the existing desktop orientation and 800 × 480 canvas.
- Restrict the Retina high-DPI window flag to macOS.

## 0.2.0 — 2026-11-22

- Replace the viewer with an 800 × 480 tactile dashboard for HyperPixel 4 and
  macOS development, including bundled fonts and club logos.
- Add an offline demo, paginated scores, goal scorers, lessons and homework.
- Display the clock with seconds and select today's school schedule by default.
- Keep independent cached data and source states during background refreshes.
- Preserve renewed Pronote credentials and include the last requested school day.
- Resolve Ligue 1 matchday labels using the official season calendar.
- Display weather conditions in French, including previously cached conditions.
