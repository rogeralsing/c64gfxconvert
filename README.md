# C64 GFX Convert

[Open the converter](https://rogeralsing.github.io/c64gfxconvert/)

A browser-based Commodore 64 image converter with FLI, IFLI, AFLI, NUFLI,
PAFLI, hires and multicolor bitmap modes, optional virtual colors, sprite
overlays, and native exports. Image processing stays in your browser.

## Run locally

Open `index.html` in a modern browser. No build step or server is required.

## Tests

```sh
node --test tests/*.test.cjs
```

## GitHub Pages

GitHub Pages publishes the repository root from `main`. Pushes to `main`
automatically update the site. The `.nojekyll` file serves the static app
without Jekyll processing.
