# WiiPointer design lab

Two interactive, framework-free browser prototypes:

- **Original Wii**: blue-edged channel tiles, enamel-like surfaces, rounded controls,
  channel-grid keyboard navigation and the familiar curved menu footer.
- **Neo Wii**: a warm, adaptive companion app with an illustrated controller,
  direct navigation, porcelain cards, light/dark appearance and a pointer playground.

All illustrations, SVG icons and optional interface tones are original to this prototype.
No Nintendo artwork, fonts, music, external assets, analytics or third-party CDN is used.

## Open

```sh
cd /home/hugo/WiiPointer
/usr/bin/python3 -m http.server 8765 --bind 127.0.0.1 --directory prototypes
```

Visit <http://127.0.0.1:8765/>. Stop the preview server with Ctrl+C.
Use the comparison bar to switch designs; the current page and browser-local settings
carry across. A server is needed because these pages use JavaScript modules.

## Safety boundary

This is a **design prototype**, not a frontend for the real daemon. It never reads input
devices, calls systemd/BlueZ, writes real configuration, injects pointer events, requests
Bluetooth/notification permissions, or changes the remote's actual LEDs. Service controls,
battery readings, connection states and calibration are explicitly simulated.

Settings are saved under `wiipointer.design-lab.v1` in this origin's localStorage. Import
and export are local JSON operations. Bad stored data falls back to defaults; imported
files are size-limited, validated, and names are escaped when rendered.

## Interaction coverage

| Area | Included |
| --- | --- |
| Home | Connection/battery preview, profile summary, direct navigation, pause/resume |
| Pointer | Sensitivity, linked or separate axes, smoothing, acceleration enable/strength/thresholds, curve, presets, soft deadzone, raw axis inversion, roll compensation, activation mode, visual test pad |
| Buttons | A/B/HOME/D-pad/+/−/1/2 maps, selectable illustration, action selectors, typed custom-shortcut proposals, reset, warnings for missing aim/click assignments |
| Connected-idle lights | Player number, custom binary combination, all on/off, slow blink, wave, pace, steady Presentation mode |
| Calibration | Five-second countdown, fast measurement chase, movement extending the stable window, cancellation, success, failure, retained previous bias, explanation of drift vs heading |
| Profiles | Three built-ins, up to eight browser-local custom profiles, save/apply/update/delete, modified indicator, validated import/export |
| Settings | Startup/recovery/calibration/minimised proposals, simulated service control, messages, appearance, text size, contrast, motion, optional sound, demo diagnostics/activity, reset confirmation |
| Alternate states | Disconnected, low battery, permission needed, paused, stopped service, measurement in progress, failed calibration |
| Accessibility | Native labelled controls, visible keyboard focus, skip link, dialog focus handling, channel-grid arrows, reduced motion, contrast option, text scaling, no essential hover-only actions |

The real backend currently has fewer settings than this exploration. In particular,
individual mapping edits, independent axis sensitivity, acceleration thresholds, idle
patterns, profile management and live updates need separate daemon/API work. The test
pad is a visual mouse-input approximation, not a validated recreation of gyro physics.

The calibration animation is deliberately **not** editable in Lights. Real Wii player
LEDs are binary, so brightness/colour controls are deliberately absent. The POWER button
is not remappable. No unobservable absolute heading or fake live gyro telemetry is shown.

## Tests

```sh
node --test prototypes/model.test.mjs
/usr/bin/python3 -m unittest test_wii_mouse
```

Optional real-browser smoke tests use an already available Playwright installation,
not a runtime dependency of the prototypes; see `browser.test.mjs`.

```sh
PLAYWRIGHT_MODULE=/absolute/path/to/playwright/index.mjs \
CHROMIUM_EXECUTABLE=/absolute/path/to/chrome \
node prototypes/browser.test.mjs
```

With the preview server running, this checks the interactive flows, keyboard/dialog
behaviour, both motion settings, and 84 page/viewport/text-size combinations. Screenshots
go outside the repository to `/tmp/opencode/wiipointer-designs` by default (override with
`SCREENSHOT_DIR`). The prototypes themselves need only a modern browser and Python's
static server; Playwright and Chromium are development-test tools, not installed dependencies.
