#!/usr/bin/env python3
"""Build the native C64 line scroller with Megaplot's character renderer."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import letters
import motion

HERE = Path(__file__).resolve().parent
RENDERER = HERE.parent / "megaplot"
BUILD = HERE / "build"
DEFAULT_TEXT = "NOICE  MEGAPLOT  TWIST AND BEND"
MAX_TEXT = 120

sys.path.insert(0, str(RENDERER))
from build_megaplot import build_assets as renderer_assets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", default=DEFAULT_TEXT, help="scrolling text, A–Z and spaces")
    args = parser.parse_args()
    text = args.text.strip().upper()
    if not 1 <= len(text) <= MAX_TEXT:
        parser.error(f"text must contain 1–{MAX_TEXT} letters and spaces")
    try:
        message = letters.encode_message(text + "   ")
    except ValueError as error:
        parser.error(str(error))

    BUILD.mkdir(exist_ok=True)
    assets = {
        **renderer_assets(),
        **letters.build_assets(),
        **motion.build_assets(),
        "letter-message": message + b"\xff",
    }
    for name, data in assets.items():
        (BUILD / f"{name}.bin").write_bytes(data)

    program = BUILD / "line-scroller.prg"
    symbols = BUILD / "main.sym"
    kickass = Path.home() / ".local/bin/kickass"
    command = [
        kickass, "main.asm", "-define", "LINE_SCROLLER", "-odir", BUILD, "-o", program, "-symbolfile",
        ":background=blank", f":assets={BUILD}",
        f":scrollStart={motion.START_X}", f":scrollLeft={motion.LEFT_LIMIT}",
        f":scrollSpacing={motion.SPACING}", f":scrollStep={motion.SCROLL_STEP}",
        f":waveCenter={motion.WAVE_CENTER}",
    ]
    result = subprocess.run(command, cwd=RENDERER, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    log = BUILD / "build.log"
    log.write_text(result.stdout)
    if result.returncode or "Internal error" in result.stdout or not symbols.is_file() or not symbols.stat().st_size:
        raise SystemExit(f"Assembly or symbol generation failed. See {log}")
    manifest = {
        "text": text,
        "messageLength": len(message),
        "programSha256": hashlib.sha256(program.read_bytes()).hexdigest(),
    }
    (BUILD / "scroller.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built {program}")


if __name__ == "__main__":
    main()
