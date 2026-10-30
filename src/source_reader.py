"""Read the two native encodings fixed by this study; no demographic comments."""

import hashlib
import re
from pathlib import Path

import numpy as np


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def header(path):
    lines = [line.split() for line in Path(path).read_text(encoding='ascii').splitlines() if line.strip() and not line.startswith('#')]
    first = lines[0]
    if len(first) < 4 or first[1:4] != ['2', '360', '650000'] or len(lines) != 3:
        raise ValueError('Unsupported record dimensions')
    signals = []
    for fields in lines[1:]:
        if len(fields) < 9 or fields[1] not in ['212', '16'] or fields[8:] == []:
            raise ValueError('Unsupported native signal specification')
        match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)(?:\((-?\d+)\))?(?:/(\w+))?', fields[2])
        if match is None:
            raise ValueError('Unsupported gain/baseline specification')
        gain = float(match[1])
        zero = int(fields[4])
        unit = match[3] or 'mV'
        baseline = int(match[2]) if match[2] is not None else zero
        if gain <= 0 or unit != 'mV' or fields[7] != '0':
            raise ValueError('Unsupported physical conversion or block size')
        signals.append(dict(file=fields[0], format=fields[1], gain=gain, baseline=baseline, units=unit, units_defaulted=match[3] is None, adc_resolution=int(fields[3]), adc_zero=zero, initial=int(fields[5]), checksum=int(fields[6]), label=' '.join(fields[8:])))
    if signals[0]['file'] != signals[1]['file'] or signals[0]['format'] != signals[1]['format']:
        raise ValueError('Unexpected signal groups')
    if signals[0]['file'] != first[0] + '.dat':
        raise ValueError('Unexpected native file identity')
    return dict(record=first[0], signals=signals, sample_rate=360, samples=650000)


def decode(data, fmt, samples):
    if fmt == '212':
        if len(data) != samples * 3:
            raise ValueError('Packed source length mismatch')
        packed = np.frombuffer(data, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        output = np.column_stack((packed[:, 0] + ((packed[:, 1] & 15) << 8), packed[:, 2] + ((packed[:, 1] >> 4) << 8)))
        output[output >= 2048] -= 4096
    elif fmt == '16':
        if len(data) != samples * 4:
            raise ValueError('16-bit source length mismatch')
        output = np.frombuffer(data, dtype='<i2').reshape(-1, 2).astype(np.int32)
    else:
        raise ValueError('Unsupported signal encoding')
    if np.any(output == (-2048 if fmt == '212' else -32768)):
        raise ValueError('Native missing-sample sentinel')
    return output


def read(folder, record):
    folder = Path(folder)
    meta = header(folder / (record + '.hea'))
    digital = decode((folder / (record + '.dat')).read_bytes(), meta['signals'][0]['format'], meta['samples'])
    for channel, signal in enumerate(meta['signals']):
        checksum = int(digital[:, channel].sum(dtype=np.int64)) % 65536
        if checksum >= 32768:
            checksum -= 65536
        if checksum != signal['checksum'] or digital[0, channel] != signal['initial']:
            raise ValueError('Native checksum or first-sample mismatch')
    physical = np.column_stack([(digital[:, channel] - signal['baseline']) / signal['gain'] for channel, signal in enumerate(meta['signals'])])
    if not np.isfinite(physical).all():
        raise ValueError('Nonfinite decoded source')
    return meta, digital, physical


def noise_at(seconds):
    return seconds >= 300 and ((seconds - 300) // 120) % 2 == 0
