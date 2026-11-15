# Spindle 3.1 low-level loader

Loader by **lft / Linus Åkesson**. This directory retains the minimal upstream
source subset needed for Spin, plus its MIT license and original README.

- Release: <https://www.linusakesson.net/software/spindle/v3.php>
- Archive: <https://hd0.linusakesson.net/files/spindle-3.1.zip>
- Exact source and generated-file hashes: [UPSTREAM.json](UPSTREAM.json).
- License: [COPYING](COPYING).

Ordinary builds run `python3 giana/tools/build-spindle.py`. They compile Spin
with the host C compiler into ignored `giana/build/tools/`; they need no network,
global installation, prebuilt host executable or additional assembler.

`src/datatables.h` contains the native loader/drive bytes produced by the
unchanged upstream sources. It was generated with locally compiled xa 2.4.1;
its source URL and checksum are recorded in the manifest. To regenerate it,
copy `src/` into a scratch build directory, then run these commands there:

```sh
make mkheader CC=cc
make datatables.h CC=cc XA65=/path/to/xa-2.4.1/xa
```

The generated table must match its pinned SHA-256. Upstream examples, manuals,
framework programs and Linux/Windows executables are not vendored.
