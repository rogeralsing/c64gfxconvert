from pathlib import Path
import hashlib
import json
import re
import socket
import subprocess
import sys
import time


name = sys.argv[1]
assert name in ('dragon', 'abyss', 'tentacles')
base = Path(__file__).resolve().parent.parent
root = base / ('proof-' + name)
root.mkdir(parents=True, exist_ok=True)
program = base / 'final-six' / (name + '.prg')
source = Path('/Users/rogerjohansson/Downloads') / ('^^' + name + '.fp2')
original = source.read_bytes()
expected = original[17402:]
assert len(original) == 33694 and len(expected) == 16292
assert original[:2] == bytes.fromhex('f0 3f')
assert original[2:16] == b'FUNPAINT (MT) ' and original[16] == 0
occupied = subprocess.run(
    ['lsof', '-nP', '-iTCP:6519', '-sTCP:LISTEN'], capture_output=True, encoding='latin1'
)
assert not occupied.stdout.strip(), occupied.stdout
command = [
    '/opt/homebrew/bin/x64sc', '-pal', '-speed', '100', '+warp', '+reu',
    '+refreshonbreak', '-sounddev', 'dummy', '-autostartprgmode', '1',
    '-remotemonitor', '-remotemonitoraddress', 'ip4://127.0.0.1:6519',
    '-autostart', str(program)
]
receipt = {
    'name': name, 'program': str(program), 'program_bytes': program.stat().st_size,
    'program_sha256': hashlib.sha256(program.read_bytes()).hexdigest(),
    'source': str(source), 'source_sha256': hashlib.sha256(original).hexdigest(),
    'command': command, 'direct_prg_autostart': True
}
with (root / 'vice.log').open('wb') as log:
    process = subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True, cwd=str(root)
    )
(root / 'vice-pid.txt').write_text(str(process.pid) + '\n')
receipt['pid'] = process.pid
connection = None


def request(text):
    connection.sendall((text + '\n').encode())
    result = bytearray()
    while True:
        try:
            chunk = connection.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            raise RuntimeError('VICE closed the monitor connection')
        result.extend(chunk)
    return result.decode('latin1')


def read_pc(registers):
    match = re.search(r'\(C:\$([0-9a-fA-F]{4})\)', registers)
    return int(match.group(1), 16) if match else None


try:
    time.sleep(3)
    connection = socket.create_connection(('127.0.0.1', 6519), timeout=1)
    connection.settimeout(1)
    request('')
    attempts = []
    for attempt in range(6):
        registers = request('r')
        pc = read_pc(registers)
        attempts.append({'pc': hex(pc) if pc is not None else None, 'registers': registers})
        print(name, 'attempt', attempt + 1, 'PC', hex(pc) if pc is not None else None, flush=True)
        if pc == 0x2088:
            break
        request('x')
        time.sleep(.5)
    else:
        raise RuntimeError('Program did not reach $2088')
    receipt['attempts'] = attempts
    receipt['first_display_pc'] = hex(pc)
    # Give the first visible PAL frame time to finish before taking a screenshot.
    request('x')
    second_registers = request('r')
    receipt['capture_registers'] = second_registers
    receipt['capture_pc'] = hex(read_pc(second_registers)) if read_pc(second_registers) is not None else None
    request('resourceset RefreshOnBreak 0')
    request('warp off')
    image = root / (name + '-vice.png')
    receipt['screenshot_response'] = request('screenshot "' + str(image) + '" 2')
    assert image.exists(), 'Screenshot not saved'
    request('bank ram')
    dump = request('m c000 ffa3')
    (root / 'phase-b-ram.txt').write_text(dump)
    memory = {}
    for line in dump.splitlines():
        match = re.search(r'>C:([0-9a-f]{4})\s+(.+)', line, re.I)
        if not match:
            continue
        address = int(match.group(1), 16)
        if not 0xc000 <= address <= 0xffa3:
            continue
        count = min(16, 0xffa4 - address)
        tokens = match.group(2).split()[:count]
        assert len(tokens) == count and all(re.fullmatch('[0-9a-f]{2}', item, re.I) for item in tokens)
        for offset, value in enumerate(tokens):
            memory[address + offset] = int(value, 16)
    assert len(memory) == 16292, ('RAM byte count', len(memory))
    actual = bytes(memory[address] for address in range(0xc000, 0xffa4))
    assert actual == expected, 'Relocated phase B differs from FP2 source'
    receipt.update({
        'phase_b_bytes': len(actual), 'phase_b_exact_match': True,
        'phase_b_sha256': hashlib.sha256(actual).hexdigest(), 'screenshot': str(image),
        'refresh_on_break': False, 'warp': False, 'passed_binary_playback_checks': True
    })
    request('x')
    print(name, 'PASS: direct PRG display loop, screenshot, exact 16292-byte phase B.', flush=True)
finally:
    if connection is not None:
        connection.close()
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    receipt['emulator_exit_code'] = process.returncode
    receipt['owned_emulator_closed'] = True
    (root / 'verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
