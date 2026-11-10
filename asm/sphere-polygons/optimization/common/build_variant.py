#!/usr/bin/env python3
"""Build one isolated raster strategy against the frozen parent renderer."""
import argparse
from pathlib import Path
import shutil
import subprocess
import re

BASE = Path(__file__).resolve().parents[2]

def build(directory):
    directory = directory.resolve()
    output = directory / "build"
    source = output / "source"
    source.mkdir(parents=True, exist_ok=True)
    for name in ("main.asm", "geometry.asm"):
        shutil.copy2(BASE / name, source / name)
    shutil.copytree(BASE / "assets", source / "assets", dirs_exist_ok=True)
    shutil.copy2(directory / "raster.asm", source / "raster.asm")
    extra = directory / "extra.asm"
    if extra.exists():
        shutil.copy2(extra, source / "extra.asm")
        with (source / "main.asm").open("a") as handle:
            handle.write('\n#import "extra.asm"\n')
    kernel = (directory / "raster.asm").read_text() + (extra.read_text() if extra.exists() else "")
    if re.search(r"^\s*delta_init:", kernel, re.M):
        main = source / "main.asm"
        main.write_text(main.read_text().replace("\nmain:\n", "\n    jsr delta_init\n\nmain:\n", 1))
    command = ["rtk", "proxy", "/Users/rogerjohansson/.local/bin/kickass", "main.asm",
               "-odir", str(output), "-o", str(output / "variant.prg"),
               "-debugdump", "-debug", "-symbolfile", "-vicesymbols"]
    subprocess.run(command, cwd=source, check=True)
    return output

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    print(build(parser.parse_args().directory))
