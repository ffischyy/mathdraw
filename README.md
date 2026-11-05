# MathDraw — draw a curve in the air, get its equation

Draw a curve with your index finger in front of the webcam. MathDraw tracks your hand, discovers an equation for what you drew using symbolic regression, and shows it in a persistent top-right panel. It also reports calculus properties of the result: derivative, antiderivative, integrals, limits, and series.

Built for Windows with Python + PySide6 + MediaPipe + SymPy.

> **Selling it?** Start with **`SELLING.md`**: naming, licence keys, building the installer, code signing and legal. Run **`build.bat`** to produce the Windows installer.

## Run from source (Windows)

1. Install **Python 3.11 or 3.12** (64-bit) from python.org and tick "Add python.exe to PATH".
2. Unzip this folder, then double-click **`run.bat`**. The first run creates a virtual environment and installs the dependencies, which takes a few minutes.

   Or, manually:
   ```bat
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python -m mathdraw
   ```
3. When running from source, the hand-tracking model (~8 MB) is downloaded once on first launch. Installer builds bundle it and never go online.

Settings, the last stroke, the last equation and the licence key are saved in `%LOCALAPPDATA%\MathDraw\state.json`, with logs in `logs\` next to it.

Run the automated tests with `python -m pytest -q`. To check every component without a camera (also used on built installs), run `python -m mathdraw --selftest`.

## Using it

### Choosing when your finger draws
Your index fingertip always moves a cursor; it only leaves ink when the **pen is down**. Pick the trigger from the **Draw:** box on the toolbar (or Settings → Gestures):

| Draw mode | Pen goes down when… | Pen lifts when… |
|---|---|---|
| **Pinch to draw** (default) | you touch your thumb to your index finger | you separate them |
| **Hold key to draw** | you hold the key (default `Space`; works globally on Windows, even with another app focused) | you release it |
| **Pen on/off switch** | the pen is ON (toolbar **Pen** button, `Ctrl+Alt+D`, or an optional gesture) *and* you point | you stop pointing or switch the pen OFF |
| **Always draw when pointing** | you point (original behaviour) | you stop pointing |

The cursor ring turns red while ink is going down. The stroke is analysed when the pen lifts.

| Default gesture | Action |
|---|---|
| ✋ Open palm (hold 0.8 s) | Hide the graph and equation overlay. No data is deleted. |
| 👍 Thumbs up (hold 0.8 s) | Show the overlay again, exactly as it was. |
| ✌ Peace sign (hold 0.8 s) | Hide or show only the equation panel. |

| Default hotkey (global on Windows) | Action |
|---|---|
| `Ctrl+Alt+O` | Show/hide the overlay (recovery if tracking fails) |
| `Ctrl+Alt+E` | Show/hide the equation panel |
| `Ctrl+Alt+T` | Toggle click-through on the desktop overlay |
| `Ctrl+Alt+C` | Clear the drawing and the equation |
| `Ctrl+Alt+D` | Pen on/off (switches to pen on/off mode) |

### Auto-smoothing (toolbar **Smooth**, on by default)
Hand tracking always shakes a little. With auto-smoothing on:
- the line is smoothed **while you draw**, and the cursor itself is steadier;
- the shake is **measured** and treated as noise when choosing the equation, so the app doesn't invent wiggly formulas to follow your tremor;
- after analysis, your drawing is **replaced by the clean function**. The function is drawn bright across the range you drew and dimmer beyond it.

Settings ▸ Drawing sets the strength (low keeps small details; high irons out strong shake), whether the drawing gets replaced, and how bright the extension is. The equation search still fits your actual points rather than the smoothed line, because smoothing rounds off real corners and peaks (for example |x|).

### Zoom and grid size
| Action | How |
|---|---|
| Zoom in / out | toolbar **+ / −**, `Ctrl =` / `Ctrl −`, or the mouse wheel |
| Zoom only x / only y | `Shift`+wheel / `Ctrl`+wheel, or Graph menu |
| Fit to drawing | toolbar **Fit** or `Ctrl F` |
| Exact window | Graph ▸ Graph settings: type xmin, xmax, ymin, ymax |
| Reset | double-click the graph or `Ctrl 0` |
| Pan | right-drag |

**Grid size:** the toolbar **Grid** box offers Auto (normal, fine or coarse, adapting as you zoom) or fixed spacing of 0.1, 0.25, 0.5, 1, 2, 5, 10, or π/2 for trig. Graph ▸ Graph settings adds:
- any custom x and y spacing
- x in multiples of π
- minor grid lines (2, 4, 5 or 10 per cell)
- axis-number size

A custom grid that would be unreadably dense at the current zoom is widened temporarily, so the app never freezes drawing thousands of lines. The toolbar shows the zoom level (separately for x and y when they differ).

### Equation tools
- **Edit ▸ Copy equation** as LaTeX (`Ctrl Shift C`) or plain text (`f(x) = 0.4*x**2 - 3`).
- **File ▸ Export graph image** (`Ctrl E`) saves a PNG without the camera image; there is also a variant that includes the camera.
- **View ▸ Equation details** (`Ctrl I`) gives the full calculus report, alternatives and fit statistics.

### Display modes
- **Mode A — Webcam overlay:** your live camera image is the background, with the grid, strokes, fitted curve, and equation panel drawn on top.
- **Mode B — Transparent desktop overlay:** a floating, borderless, always-on-top window. Its background is truly transparent (per-pixel alpha), and only the graph layers, any tint you choose, and the equation panel are painted. Drag it with the "⠿ move" handle and resize it from the bottom-right corner. In this mode the main window acts as the camera/control window and can be minimized.

### Settings
- **Display:** opacity sliders for the overall graph, grid, axes, drawing, fitted curve, background tint, and panel; colours; panel font size, width, padding, and margin; layer visibility.
- **Overlay window:** always on top, borderless, click-through, exclude from screen capture, camera index, mirror, and exact position and size.
- **Analysis:** a *simpler ⟷ more complex* slider, time budget, maximum expression complexity, which function families to search, and automatic live updates (off by default, so the previous equation persists until a new analysis succeeds).
- **Gestures:**
  - Pick the draw, hide, show, panel-only, and clear gestures, and set the confidence threshold, hold duration, cooldown, and stroke-end delay.
  - The tab has a live landmark preview, and you can record custom gestures (hold the pose for 3 s).
  - **Test mode** shows what would trigger without doing anything.
  - Changes are staged until you click **Save**. Conflicts with the drawing gesture are blocked.
- **Shortcuts:** rebind all hotkeys.

## How recognition works

Code lives in `mathdraw/math_engine/`.

1. **Stroke classification.** Each stroke is classified as one of:
   - `y = f(x)`
   - `x = g(y)` (e.g. a sideways parabola)
   - a closed curve, tested as a circle, a general conic (implicit), or a polar `r(θ)` about the origin or the centroid
   - a general parametric curve `(x(t), y(t))`
2. **Expression grammar (`grammar.py`).** Models are generated from a configurable grammar rather than a list of answers:
   - polynomials up to degree 6
   - shifted, scaled, and reflected primitives: roots, logs, absolute value, rational poles, powers with fractional or negative exponents, exponentials with arbitrary base
   - all six trig functions, inverse trig, hyperbolic and inverse hyperbolic functions, the logistic function, and erf
   - sinusoids with amplitude, frequency, phase, and shift, plus sums with trends
   - piecewise-linear functions
   - **products** `p(x)·g(x)`, where p(x) ∈ {x, x², x³, 1/x, 1/x², √x, ln x} and g is a sinusoid or exponential
   - damped oscillations
   - **compositions** `outer(b·p(x)+c)`, where outer ∈ {sin, cos, exp, ln, √, ∛, tanh, atan, 1/·} and p(x) ∈ {x², x³, 1/x, √|x|, eˣ, sin x}
   
   x²sin x, e^(−x²), ln(x²+1), sin x/x, √(x²+1), and eˣcos 2x all emerge from these generic rules. Each is recovered exactly in the tests.
3. **Fitting.** Linear coefficients are solved exactly (variable projection). Only the nonlinear parameters are optimized, using multi-start bounded least squares within a time budget.
4. **Model selection against noise.** Candidates are scored as `score = n·ln(MSE + τσ²) + λ·k·ln n`, where:
   - σ is the tracking noise estimated from the stroke itself, so the search stops rewarding accuracy once a model fits to the noise level
   - λ comes from the simplicity slider
   
   Each fit also uses held-out validation points to flag overfitting.
5. **Honest uncertainty.**
   - Candidates that predict the same curve are grouped as *equivalent forms*.
   - If other models fit about as well, the result is marked **UNCERTAIN**, the confidence drops, and alternatives are listed.
   - If nothing fits well, the result is labelled **APPROXIMATION**.
   - Exact-looking results only show `=` when unambiguous; otherwise `≈`.
6. **Coefficient snapping.** Coefficients are replaced with clean values (integers, halves, multiples of π) only when that doesn't measurably worsen the fit.
7. **Calculus (`calculus.py`).** This module is separate from recognition and every SymPy call is time-limited. It reports:
   - derivatives, an antiderivative, and the integration techniques SymPy used (u-substitution, by parts, …)
   - the definite integral over the drawn domain, with a trapezoid/Simpson error table
   - the tangent line, critical and inflection points, limits at ±∞, and singularities or the continuity domain
   - improper integrals, a Taylor polynomial, and a convergence test for Σf(n)
   - for parametric and polar curves: slope, arc length, and area; for implicit curves: the implicit derivative

## Architecture

```
mathdraw/
  app.py              entry point (python -m mathdraw)
  state.py            persistent state manager (runtime tracking state kept separate)
  geometry.py         camera-normalised ⟷ math ⟷ pixel coordinate mapping
  tracking.py         webcam + MediaPipe HandLandmarker thread (mirrored before detection)
  gestures.py         invariant hand features, classifier, custom gestures, hold/cooldown controller
  platform_win.py     Windows click-through, capture exclusion, global hotkeys (with Qt fallbacks)
  math_engine/        grammar, regression, analyzer, calculus, LaTeX helpers
  ui/                 canvas + equation panel, desktop overlay, settings, main window
tests/test_engine.py  automated tests (pytest)
TESTING.md            manual acceptance checklist (camera / desktop-dependent items)
```

### Design guarantees
- **Visibility is independent of data.** Hiding never stops the webcam, tracking, or analysis, and never deletes anything.
- **The equation persists.** It changes only when a new analysis *succeeds* (or when you clear or dismiss it). Losing the hand, lowering it, or starting a new stroke keeps it on screen.
- **Resizing never changes the mathematics.** Strokes are stored in mathematical coordinates, and the graph is letter-boxed at the camera's aspect ratio.
- **The equation panel fades** to 35% when your fingertip passes behind it, so it doesn't hide your hand.
- **No screen capture is used.** The overlay is also excluded from capture by default, so recording software can't create feedback loops.

## Limitations
- A hand-drawn curve cannot uniquely determine an arbitrary formula. Short or featureless strokes are reported as uncertain, with alternatives.
- Parametric strokes use normalised arc length as `t`. The resulting equations describe the drawing but are rarely "textbook" parametrisations.
- Click-through on Windows uses `WS_EX_TRANSPARENT`. Use `Ctrl+Alt+T` (global) to turn it off again.
- Global hotkeys are Windows-only. On other systems the shortcuts work while a MathDraw window has focus.
