/**
 * Export the AFLI underlay and one monochrome raster mask in a stored ZIP.
 * sprites.bin is 192 × 200 bits, not a sequence of 64-byte VIC sprite frames.
 * Requires afli-export.js; the native checker prototype does not load this mask.
 * ZIP records follow https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT.
 */
function encodeAfliSpriteLayers(result, palette) {
  const validImage = image => image?.width === 320 && image.height === 200 &&
    ArrayBuffer.isView(image.data) && image.data.BYTES_PER_ELEMENT === 1 &&
    image.data.length === 320 * 200 * 4;
  const mask = result?.spriteMask;
  if (!validImage(result?.pixels) || !validImage(result?.afli?.pixels) ||
      !ArrayBuffer.isView(mask) || mask.BYTES_PER_ELEMENT !== 1 || mask.length !== 64000) {
    throw new Error('AFLI sprite export requires 320 × 200 images and a matching sprite mask.');
  }
  const colorIndex = result.spriteColorIndex;
  if (!Number.isInteger(colorIndex) || colorIndex < 0 || colorIndex > 15) {
    throw new Error('AFLI sprite export requires a C64 sprite color from 0 to 15.');
  }

  const packedMask = packSpriteLayerMask(mask, 'AFLI');

  // Keep the real AFLI encoder's palette, row-color and pixel validation.
  const afliFile = encodeAfli(result.afli, palette);
  const color = palette.find(entry => entry.index === colorIndex);
  const manifest = {
    format: 'c64-afli-sprite-layers',
    version: 1,
    files: { afli: 'image.afl', spriteMask: 'sprites.bin' },
    image: { width: 320, height: 200, pixelAspectRatio: [1, 1] },
    spriteColor: {
      index: color.index,
      name: typeof color.name === 'string' ? color.name : `C64 color ${color.index}`,
      rgb: [...color.rgb]
    },
    layout: {
      afliValidRect: { x: 112, y: 0, width: 208, height: 200 },
      spriteRect: { x: 112, y: 0, width: 192, height: 200 },
      spriteCountPerRow: 8,
      hardwareSpriteWidth: 24,
      hardwareSpriteHeight: 21
    },
    mask: {
      format: 'packed-raster-mask',
      byteLength: 4800,
      bytesPerRow: 24,
      rowOrder: 'top-to-bottom',
      columnOrder: 'left-to-right',
      bitOrder: 'msb-first',
      setBit: 'sprite-color',
      clearBit: 'afli-underlay',
      hardwareFrames: false
    },
    referencePlayer: {
      programIncluded: false,
      acceptsThisMask: false,
      imageFirstRaster: 48,
      firstSpriteVisibleRaster: 32,
      spriteReuseRows: 21
    }
  };
  const utf8 = new TextEncoder();
  const files = [
    { name: 'image.afl', data: afliFile },
    { name: 'sprites.bin', data: packedMask },
    { name: 'manifest.json', data: utf8.encode(`${JSON.stringify(manifest, null, 2)}\n`) }
  ];
  return encodeStoredLayerZip(files);
}

/** Pack a validated full-resolution 320 × 200 binary mask for the shared field. */
function packSpriteLayerMask(mask, formatName) {
  const packedMask = new Uint8Array(4800);
  for (let pixel = 0; pixel < mask.length; pixel += 1) {
    if (mask[pixel] !== 0 && mask[pixel] !== 1) {
      throw new Error(`${formatName} sprite mask values must be 0 or 1.`);
    }
    if (mask[pixel] === 0) continue;
    const x = pixel % 320;
    if (x < 112 || x >= 304) {
      throw new Error(`${formatName} sprite mask pixels must stay inside columns 112 through 303.`);
    }
    const y = Math.floor(pixel / 320);
    const column = x - 112;
    packedMask[y * 24 + (column >> 3)] |= 0x80 >> (column & 7);
  }

  return packedMask;
}

/** Stored ZIP writer shared by the AFLI and FLI layer exporters. */
function encodeStoredLayerZip(files) {
  const utf8 = new TextEncoder();
  let localSize = 0;
  let centralSize = 0;
  for (const file of files) {
    file.nameBytes = utf8.encode(file.name);
    file.offset = localSize;
    let crc = 0xffffffff;
    for (const byte of file.data) {
      crc ^= byte;
      for (let bit = 0; bit < 8; bit += 1) {
        crc = crc >>> 1 ^ (crc & 1 ? 0xedb88320 : 0);
      }
    }
    file.crc = (crc ^ 0xffffffff) >>> 0;
    localSize += 30 + file.nameBytes.length + file.data.length;
    centralSize += 46 + file.nameBytes.length;
  }

  const archive = new Uint8Array(localSize + centralSize + 22);
  const view = new DataView(archive.buffer);
  const word = (offset, value) => view.setUint16(offset, value, true);
  const long = (offset, value) => view.setUint32(offset, value, true);
  let central = localSize;
  for (const file of files) {
    const local = file.offset;
    long(local, 0x04034b50);
    word(local + 4, 20);
    word(local + 6, 0x0800); // UTF-8, without encryption or data descriptors.
    word(local + 10, 0); // Deterministic DOS timestamp: 1980-01-01 00:00.
    word(local + 12, 0x0021);
    long(local + 14, file.crc);
    long(local + 18, file.data.length);
    long(local + 22, file.data.length);
    word(local + 26, file.nameBytes.length);
    archive.set(file.nameBytes, local + 30);
    archive.set(file.data, local + 30 + file.nameBytes.length);

    long(central, 0x02014b50);
    word(central + 4, 20);
    word(central + 6, 20);
    word(central + 8, 0x0800);
    word(central + 12, 0);
    word(central + 14, 0x0021);
    long(central + 16, file.crc);
    long(central + 20, file.data.length);
    long(central + 24, file.data.length);
    word(central + 28, file.nameBytes.length);
    long(central + 42, file.offset);
    archive.set(file.nameBytes, central + 46);
    central += 46 + file.nameBytes.length;
  }
  long(central, 0x06054b50);
  word(central + 8, files.length);
  word(central + 10, files.length);
  long(central + 12, centralSize);
  long(central + 16, localSize);
  return archive;
}
