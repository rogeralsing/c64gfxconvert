# Usage Report

## Scope

- Page: C64 image converter, Save IFLI flow.
- Route: http://127.0.0.1:55115/index.html
- Environment: local in-app browser and VICE x64sc 3.10, PAL at normal speed.
- Login state: local application; no account required.
- Date: 2026-10-31.

## User Stories Tested

- Select IFLI before loading an image and see Save disabled.
- Load an image and save from the Unrestricted tab.
- Change brightness and background, then export from the Palette tab.
- Open the restricted IFLI preview and save the same settings again.
- Switch to FLI and return to IFLI.
- Load the downloaded FP2 data with GoDot's original PAL viewer.
- Validate and display the user's `^^R-Type_-Bi.fp2` export.
- Reserve two left character columns in FLI, IFLI, FLI Virtual, and AFLI while fitting the complete source image.
- Switch through all six graphics modes and return to FLI without accumulating resize or margin errors.
- Export the reserved area with every image effect at maximum.
- Validate and display the user's `^^Skarmavbil.fp2` export.

## Story Results

- Passed: all listed stories. Every download contained 33,694 bytes and the raw FunPaint II header.
- Passed: brightness +3 and blue background produced different bytes from the initial export. Both background tables contained color index 6.
- Passed: Palette and restricted preview exports with identical settings were byte-for-byte equal.
- Passed: the configured test export and the user's R-Type export displayed in VICE without a REU, at normal speed with warp disabled.
- Passed: the user's Skarmavbil export displayed in the same PAL player.
- Passed: all four FLI modes report the requested 304×200 display area (152×200 multicolor), while Bitmap/Hires retain full width. The red and green source-edge markers remain in the fitted image.
- Passed: the actual downloaded FP2 retained eight blank logical columns in both phases, including all 3,200 reserved pixels with every image effect at maximum.
- Passed: the open converter was refreshed and its image, selected mode, preview tab, background, sliders, grid, and paused state were restored exactly.
- Failed: none.
- Unclear: none in the tested export path.

## 0. Bugs

- None.

## 1. Must fix

- None.

## 2. Should fix

- None introduced by the export flow. The existing hardware-preview limitations are listed under Follow-up.

## 3. Nice to have

- None added to this scope.

## Code And Tests Consulted

- `index.html`: the implementation's cache invalidation, loading request tokens, export-button state, filename, and browser download lifecycle.
- `ifli-export.js`: the external FP2 binary contract, because browser appearance cannot establish screen-page order or bitmap packing.
- `tests/ifli-export.test.cjs`: three passing tests cover literal external-format offsets and codes, invalid allocation data, and unrepresentable pixels.
- `image-layout.js` and `tests/image-layout.test.cjs`: four passing geometry checks cover the four reserved modes, wide/tall source fitting, unchanged Bitmap/Hires placement, and invalid dimensions. All seven focused checks passed together.
- An independent official butterfly reference check retained all 64,000 phase pixels after encoding.
- Inline JavaScript syntax passed `node --check`.

## Screenshots And Evidence

- `.playwright-mcp/ifli-export/save-ifli-ui.png`: Save IFLI beside the preview controls.
- `.playwright-mcp/ifli-export/configured-vice.png`: actual browser download displayed by the original PAL player.
- `.playwright-mcp/ifli-export/r-type-vice.png`: the user's export displayed by the same player.
- `.playwright-mcp/ifli-export/configured.d64` and `r-type.d64`: reproducible player/image disks.
- Browser accessibility state confirmed disabled Save without an image, enabled Save after loading, and hidden Save outside IFLI mode.
- `.playwright-mcp/fli-geometry/fli-margin-ui.png`: updated converter with the two-column reservation and restored controls.
- `.playwright-mcp/fli-geometry/mode-checks.json`: actual browser mode-switch results.
- `.playwright-mcp/fli-geometry/export-geometry-verification.json`: downloaded FP2 color decoding verifies the reserved area and retained source-edge markers.
- `.playwright-mcp/fli-geometry/skarmavbil-vice.png`: the user's second export displayed in VICE.

## Follow-up

- Added Save IFLI, lazy fitting shared with preview, local FP2 download, and focused format tests.
- Loading-state and stale-request guards were reviewed; no artificial delayed-decode test seam was introduced.
- Export preserves the current 160×200 backing. The requested two-column margin is implemented. The stock PAL player's documented affected region is three character columns, and browser playback cadence remains a separate renderer concern.
- FP2 contains rendered image data and color allocations. The included PAL player displays it; conversion controls are not a reloadable project format.
