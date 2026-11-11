# Current-source reproducibility

All three selected programs were rebuilt from the current working-tree sources
into separate directories. Their complete PRG bytes and every named symbol
address match the original, actually captured programs:

| Program | Bytes | SHA256 |
| --- | ---: | --- |
| Stardust | 37,170 | `ee0b7514369a9e1d55a4523500d21c87d901a76b92a65c3d18b988b379e0e29b` |
| Hyperbased, gain 3 | 50,429 | `0434f8171b94a1c6f44d9923b2143fc91b8688443061f5db3b49090297a4a980` |
| Contextual Madness | 45,039 | `3961595a2efa07e0338f058dd7d56ae1006aac6210aed397c104e0884f590df6` |

The initial Hyperbased and contextual Madness build receipts recorded an older
`score_dictionary.py` hash. The only intervening change was its leading module
docstring, expanded to explain the one-byte dictionary format. Replacing the
current docstring with the previous text reconstructs the recorded old hash
exactly. Every byte after the docstring is unchanged, and the executable Python
AST after the docstring is identical. The CLI help description also reflects
the new documentation; codec behavior did not change.

- `summary.json`: overall result and all current source hashes.
- `source-drift.json`: documentation-only hash reconstruction and AST check.
- `sources/`: immutable previous/current module snapshots and current builder
  and assembly sources.
- `{stardust,hyperbased,madness-contextual}/reproduction.json`: original and
  rebuilt program hashes, source hashes and symbol-address identity.
- Each reproduced `c64/build.json`: the ordinary build receipt from current
  sources, rather than a retroactively edited original receipt.

The original build directories, VICE execution evidence and live audio captures
were left untouched. Reproduction adds current-source evidence to those results.
