# C64 assembly starter

Open this `asm` folder in VS Code. It contains a KickAssembler project configured for PAL C64 development.

- **Cmd+Shift+B** builds with VS64 and writes `build/hello-raster.prg` and debug symbols.
- **F5** builds and starts VICE x64sc with source debugging. Set a breakpoint in `src/main.asm`, then continue or step through the code.
- **Terminal → Run Task → Build + Run RetroDebugger** builds and loads the program and symbols into RetroDebugger. An existing RetroDebugger instance receives the new program.

The sample prints “C64 TOOLCHAIN READY” and draws six color bands using raster polling. It is a small starting point for raster experiments, not a cycle-stable interrupt routine.

The same workflow is available from a terminal:

```sh
./build.sh
./run-vice.sh
./run-retro.sh
```

Both run scripts build first. The `build` folder contains `hello-raster.prg`, KickAssembler debug data (`hello-raster.dbg`), labels (`main.sym`), and VICE labels (`main.vs`).

Tool paths are configured in `.vscode/settings.json`. KickAssembler lives in `~/.local/share/c64-tools/KickAssembler`; VICE is `/opt/homebrew/bin/x64sc`; RetroDebugger is `/Applications/Retro Debugger.app`.
