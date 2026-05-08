# Engine Lines Board Feature Implementation Summary

## Overview
Implemented the Engine Lines board feature for the game analysis page, allowing users to click engine suggestion arrows on the main board to explore continuation lines.

## Files Modified

### 1. Templates
- **`templates/games/analysis.html`**
  - Changed layout from single-column to 2-column grid for boards + full-width row for charts
  - Added Engine Lines board container with controls (separate from main board)
  - Added responsive CSS to stack boards vertically on mobile (max-width: 1200px)
  - Added ANALYSIS_DATA object with slug for JavaScript access
  - Included engineLines.js script

- **`templates/games/_board_partial.html`**
  - Added `no_arrows` parameter support to conditionally hide arrow visibility toggles
  - Arrow toggles now only display when `no_arrows=False`

- **`templates/games/_engine_line_partial.html`** (NEW)
  - Template for engine line continuation board
  - Displays context label showing which engine line is being viewed (e.g., "Best SF (ply 5+3)")
  - Includes board frames JSON data and initialization script
  - Sets up separate ply sync for the Engine Lines board

### 2. Backend - views.py
- **Modified `board_partial` view**
  - Added `"no_arrows": False` to template context

- **Added `engine_line_partial` view** (NEW)
  - Accepts query parameters: ply, move_uci, engine, tier, orientation
  - Reconstructs board position up to clicked move
  - Generates continuation frames from game moves (up to 50 moves)
  - Returns rendered engine line partial with context label

- **Updated imports**
  - Added `chess` module import
  - Imported `_BOARD_COLORS` constant from board_builder

### 3. Backend - board_builder.py
- **Modified `build_board_frames` function**
  - Now injects arrow indices (data-arrow-index) into SVG elements
  - Injects arrow labels for each frame
  - Used `_inject_arrow_ids()` and `_inject_arrow_labels()` functions

### 4. Backend - partial_urls.py
- Added route: `path("games/<slug:slug>/engine-line/", views.engine_line_partial, name="games_engine_line_partial")`

### 5. JavaScript - engineLines.js (NEW)
- **`WoodLeagueEngineLines` object** with methods:
  - `setPly()` - set current ply in Engine Lines board
  - `setTotalPlies()` - set total plies (called after loading continuation)
  - `subscribe()` - subscribe to state changes
  - `getState()` - get current state
  - `loadEngineLine()` - fetch and render continuation from server

- **Arrow click handlers**
  - `initializeEngineLineArrowHandlers()` - attach click listeners to arrow SVG elements
  - Extracts arrow metadata (engine, move, tier) from DOM
  - Makes AJAX request to engine-line endpoint
  - Renders returned HTML in Engine Lines container

- **`setupEngineLineBoard()` function**
  - Initializes board controls (play, next, prev, etc.)
  - Manages Engine Lines ply sync independent from main board
  - Mirrors perspective (board flip) from main board

## Features Implemented

### Layout
✓ 2-column boards row (main + engine lines) + charts row
✓ Mobile responsive (stacks vertically below 1200px)
✓ Engine Lines board initially shows "Click engine arrow to explore" placeholder
✓ Disabled controls until a line is loaded

### Engine Lines Board
✓ Shows continuation after clicked arrow
✓ Separate ply sync (independent from main board)
✓ Shares perspective/flip state with main board
✓ Context label shows engine name, tier, and ply info
✓ Supports play/pause animation like main board
✓ Move controls (start, prev, next, end)
✓ Slider for quick navigation
✓ Board flip button (synced with main board)

### Arrow Interaction
✓ Arrow elements have data-arrow-index attribute
✓ Arrows are clickable with visual feedback (opacity/brightness on hover)
✓ Click extracts: engine type (SF/Lc0), move UCI, tier (1/2/3)
✓ Triggers AJAX request to backend

### Backend
✓ Reconstructs game position at any ply
✓ Plays clicked move and generates continuation frames
✓ Handles game continuation from the continuation position
✓ Returns up to 50+ moves of continuation
✓ Validates all inputs (ply, move_uci, engine, tier, orientation)
✓ Graceful error handling

## Implementation Notes

### Architecture
- Engine Lines board uses separate `WoodLeagueEngineLines` state manager (parallel to `WoodLeagueAnalysis`)
- Both boards share the main board's perspective/flip state
- Arrow clicks are captured at the SVG element level with data attributes
- Backend reconstructs position dynamically (no pre-computed continuations stored)

### Continuation Generation
The current implementation:
1. Reconstructs the board position up to the clicked move's ply
2. Plays the clicked move (the engine suggestion)
3. Continues with moves from the actual game if they exist
4. Shows up to 50 moves of continuation
5. If the clicked move doesn't match the actual game, shows just that position

### Responsive Design
- Uses CSS media query on `#boards-container`
- Below 1200px width, switches from `grid-template-columns: 1fr 1fr` to `1fr`
- Charts remain full-width below breakpoint

### Browser Compatibility
- Uses HTMX for AJAX requests (with fetch fallback)
- Uses Data attributes for arrow indexing
- Arrow label interaction using CSS classes

## Testing Checklist
- [ ] Main board renders without errors
- [ ] Engine Lines board placeholder displays initially
- [ ] Can click arrows on main board
- [ ] Engine line loads with correct context label
- [ ] Engine line board controls work (play, prev, next, etc.)
- [ ] Ply slider on engine line board works
- [ ] Board flip on engine line reflects main board perspective
- [ ] Mobile layout stacks boards vertically
- [ ] Arrow visibility toggles still work on main board
- [ ] Error handling for invalid move_uci
- [ ] Continuation moves are generated correctly

## Future Enhancements
- Store pre-computed continuations in DB for faster loading
- Show evaluation for continuation moves
- Display move times/quality indicators
- Allow reverting to main board ply when clicking in continuation
- Animate continuation moves automatically
- Show multiple continuation lines (current: only shows game continuation)
