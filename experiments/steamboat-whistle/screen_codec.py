"""Exact screen-delta codec retained from the approved monochrome movie builder.

The command selection and byte layout are unchanged. Keeping these helpers
local makes the finished GIF player independent of an experimental worktree.
"""
from collections import defaultdict
import hashlib

import numpy as np


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode_pixels(screen, font):
    bits = np.unpackbits(np.frombuffer(font, dtype=np.uint8)).reshape(256, 8, 8)
    masks = bits[np.asarray(screen)]
    return np.where(masks, 0, 255).astype(np.uint8).reshape(25, 40, 8, 8).transpose(0, 2, 1, 3).reshape(200, 320)


def rgba_hash(pixels):
    image = np.empty((200, 320, 4), dtype=np.uint8)
    image[..., :3] = pixels[..., None]
    image[..., 3] = 255
    return sha(image.tobytes())


def encode_screen(before_screen, after_screen):
    # Byte-optimal cursor commands: 0=end, 1..127=skip, 128..255=copy
    # 1..128 literals. A literal may bridge unchanged cells when that costs
    # less than emitting another skip and literal command.
    cost, choice = [0] * 1001, [None] * 1000
    cost[1000] = 1
    last_change = max(np.flatnonzero(before_screen != after_screen), default=-1)
    for first in range(999, -1, -1):
        if first > last_change:
            cost[first], choice[first] = 1, ('end', 0)
            continue
        options = [(1 + count + cost[first + count], 'copy', count)
                   for count in range(1, min(128, 1000 - first) + 1)]
        for count in range(1, min(127, 1000 - first) + 1):
            if before_screen[first + count - 1] != after_screen[first + count - 1]:
                break
            options.append((1 + cost[first + count], 'skip', count))
        best, operation, count = min(options)
        cost[first], choice[first] = best, (operation, count)
    cursor, first = bytearray(), 0
    while first < 1000:
        operation, count = choice[first]
        if operation == 'end':
            break
        if operation == 'skip':
            cursor.append(count)
        else:
            cursor.append(127 + count)
            cursor.extend(after_screen[first:first + count])
        first += count
    cursor.append(0)
    assert len(cursor) == cost[0]

    grouped = bytearray()
    for page in range(4):
        first, end = page * 256, min((page + 1) * 256, 1000)
        groups = defaultdict(list)
        for position in range(first, end):
            if before_screen[position] != after_screen[position]:
                groups[int(after_screen[position])].append(position - first)
        grouped.extend(len(groups).to_bytes(2, 'little'))
        for value, positions in sorted(groups.items()):
            assert 1 <= len(positions) <= 256
            grouped.extend((value, len(positions) - 1))
            grouped.extend(positions)
    mode = int(len(cursor) <= len(grouped))
    result = bytearray((mode,))
    result.extend(cursor if mode else grouped)
    changed_characters = int(np.count_nonzero(before_screen != after_screen))
    return bytes(result), dict(characterChanges=changed_characters, bytes=len(result), screenMode=('groups','cursor')[mode],
                              cursorBytes=len(cursor), groupedBytes=len(grouped))


def decode_screen(raw, screen):
    """Interpret the stored binary format independently of group selection."""
    screen = screen.copy()
    mode, at = raw[0], 1
    assert mode in (0, 1)
    if mode == 1:
        cursor = 0
        while True:
            command = raw[at]
            at += 1
            if command == 0:
                break
            if command < 128:
                cursor += command
            else:
                count = command - 127
                assert cursor + count <= 1000
                screen[cursor:cursor + count] = list(raw[at:at + count])
                at += count
                cursor += count
    else:
        for page in range(4):
            groups = int.from_bytes(raw[at:at + 2], 'little')
            at += 2
            for _ in range(groups):
                value, minus_one = raw[at:at + 2]
                at += 2
                for position in raw[at:at + minus_one + 1]:
                    target = page * 256 + position
                    assert target < 1000
                    screen[target] = value
                at += minus_one + 1
    assert at == len(raw), 'A mono packet must end at its screen-delta terminator'
    return screen
