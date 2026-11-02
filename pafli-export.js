/** Embed both AFLI phases in the checked PAL PAFLI player; BASIC RUN starts it. */
function encodePafliPrg(result, palette) {
  if (result?.frames?.length !== 2) throw new Error('PAFLI export requires two fitted AFLI frames.');
  // The existing encoder validates every pixel against its row's two colors.
  const phases = result.frames.map(frame => encodeAfli(frame, palette));
  const program = new Uint8Array(48013);
  program.set([0x01, 0x08]);
  const ram = program.subarray(2);
  ram.set(C64_PAFLI_PLAYER.engine, 0);
  ram.set(C64_PAFLI_PLAYER.bootstrap, 0x2000 - 0x0801);
  for (const [phase, file] of phases.entries()) {
    // This is the same phase-B staging address and backwards relocation used
    // by the AFLI player. It lands at $c000 before speedcode occupies $8400.
    const start = (phase === 0 ? 0x4000 : 0x83e8) - 0x0801;
    ram.set(file.subarray(2, 8194), start);
    ram.set(file.subarray(8194, 16194), start + 8192);
    // Preserve the PAL engine's three-column hardware mask in both banks.
    // The last character row has zero bitmap and zero ink/paper colors.
    for (let bank = 0; bank < 8; bank += 1) {
      for (let row = 0; row < 25; row += 1) ram.fill(0, start + bank * 1024 + row * 40,
        start + bank * 1024 + row * 40 + (row === 24 ? 40 : 3));
    }
    for (let row = 0; row < 25; row += 1) ram.fill(0, start + 8192 + row * 320,
      start + 8192 + row * 320 + (row === 24 ? 320 : 24));
  }
  return program;
}
