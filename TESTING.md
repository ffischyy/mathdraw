# Acceptance tests

**Automated** (`python -m pytest -q`, 46 tests):
- Recognition of 15 representative functions with simulated tracking noise (test 10)
- Exact recovery of the spec's composition examples
- Ambiguity and approximation reporting (test 11)
- Circle, polar, and inverse curves
- The calculus module, including the numerical-error table and the improper integral ∫e^(−x²) = √π
- Coordinate consistency across window sizes (test 9)
- Gesture scale/rotation invariance, custom-gesture learning, hold/cooldown/release, drawing priority, and test mode
- Drawing trigger modes: pinch, hold key, pen switch, and always-draw
- Auto-smoothing: removes shake but keeps endpoints and shape; a shaky parabola is still recognised as a quadratic; a shaky stroke that steps backwards is still read as y = f(x)
- Zoom (anchored, x-only, y-only), exact graph window, fit to drawing, grid spacing (auto, custom, π, minor lines, auto-widening), tick labels
- Licence keys: genuine keys verify, tampered or foreign keys fail, trial countdown and expiry
- `python -m mathdraw --selftest` checks every component (Qt, engine, rendering, MediaPipe, OpenCV, licensing)
- State persistence: hiding or losing the hand never deletes data (logic behind tests 1–4 and 12)

**Manual** — run these on your PC with the webcam. Tick each one.

| # | Steps | Expected |
|---|---|---|
| 0 | Set Draw: *Pinch to draw*. Move a pointing finger around; then pinch and draw; release. Repeat with *Hold key* (hold Space) and *Pen on/off* (Ctrl+Alt+D). | No ink appears until the pen is down in each mode; the stroke is analysed when the pen lifts. |
| 1 | Pinch (thumb to index finger) and draw a U shape, then release the pinch. | Within a few seconds, the top-right panel shows a quadratic, e.g. `f(x) = 0.5x² − 2`, with model, fit error, and confidence. It stays visible. |
| 2 | Lower your hand out of the frame and wait 30 s. | The status bar shows "Hand –"; the equation and drawing remain. |
| 3 | Show an open palm and hold it for about 1 s (a yellow ring fills around your fingertip). | The grid, curves, and panel disappear; the camera image and status bar stay. Nothing is erased. |
| 4 | Hold a thumbs-up for about 1 s. | The same graph, zoom, layers, and equation return. |
| 5 | Settings → Gestures: set Hide = Fist and Show = Rock, enable Test mode, and try the gestures. The log says "would trigger…". Click Save, close Settings, and repeat. | The new gestures hide and show the overlay; the old ones no longer do. Recording a custom gesture and assigning it also works. |
| 6 | Settings → Display: set the background tint to 0.4, then 0. Switch to Mode B. | The tint visibly darkens the graph area; at 0, the camera/desktop shows through completely. In Mode B, the desktop windows behind the overlay are visible. |
| 7 | Set the grid opacity to 0.1, overall opacity to 0.4, and panel opacity to 0.3, then 1.0. | The graph fades but the equation stays readable. At a low panel opacity, the text gets a dark outline. |
| 8 | Toolbar → Mode: switch A → B → A. | B shows a floating transparent always-on-top overlay; A returns to the webcam background. The equation persists in both. |
| 9 | Resize the main window and the overlay (corner grip) to very different shapes. | Tick labels and curve positions stay mathematically the same (the vertex is still at the same x, y); only the letter-boxing changes. |
| 10 | Draw: x³ (S-shape), a sine wave, an exponential (rising fast), a log (fast rise then flattening, starting just right of a vertical line), a bell curve (e^(−x²)), a sideways parabola, and a circle. | Each gives a sensible model. Open **Details…** to check the derivative, integral, and limits. |
| 11 | Draw a very short, nearly straight arc, then a random scribble. | The short arc shows "UNCERTAIN — see alternatives" with a confidence below 60%. The scribble shows "APPROXIMATION". Neither claims an exact formula. |
| 12 | Hide the overlay (gesture or Ctrl+Alt+O), draw a new curve while hidden, then show it. | The camera kept running; the new curve was analysed while hidden and its equation now appears. |
| 13 | Mode B: enable click-through, then click on a window behind the overlay; press Ctrl+Alt+T. | The click reaches the window below; the hotkey restores mouse control. |
| 14 | Close and reopen the app. | The mode, overlay position, opacities, gestures, last drawing, and last equation are all restored. |
| 15 | Draw a deliberately shaky parabola with **Smooth** on, then again with it off (Re-analyse). | With smoothing on, the line looks clean while drawing and is replaced by a smooth quadratic. With it off, the raw jitter is shown. |
| 16 | Use + / −, Shift+wheel, Ctrl+wheel and **Fit**; pick Grid 0.5, then π/2 (trig); set minor lines to 5 in Graph settings; type a window of x −1…1, y −50…50. | Each changes the view as described. Axis numbers read 0.5 steps, then π/2, π, 3π/2. The window matches exactly. |
| 17 | Edit ▸ Copy equation (plain text) and paste it into a text editor; File ▸ Export graph image. | The text matches the panel; the PNG shows the graph without your camera image. |
| 18 | Installed build: first launch shows the welcome screen and "Trial: 14 days left" in the title; Help ▸ Enter licence key accepts a key from tools/issue_license.py. | The title loses the trial note and About shows "Licensed to …". |
