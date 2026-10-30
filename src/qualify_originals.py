"""Compare every native sample with WFDB; no recording119 features or scores."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import wfdb

from source_reader import read, sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--private-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    acquisition = json.loads((args.private_root / 'acquisition-verification.json').read_text(encoding='utf-8'))
    assert acquisition['status'] == 'PASS_CAPTURE_AND_PUBLISHER_SHA256'
    requests = json.loads((root / 'data/source_requests.json').read_text(encoding='utf-8'))
    records = [(x['dataset'], x['record']) for x in requests if x['name'].endswith('.dat')]
    assert len(records) == 14
    originals = {}
    rows = []
    digital_cells = 0
    physical_cells = 0
    clean_cells = 0
    for dataset, record in records:
        folder = args.private_root / dataset
        meta, digital, physical = read(folder, record)
        independent = wfdb.rdrecord(str(folder / record), physical=False)
        assert independent.d_signal.shape == digital.shape
        assert np.array_equal(independent.d_signal, digital)
        converted = independent.dac()
        assert np.allclose(converted, physical, rtol=0, atol=1e-14)
        assert independent.fs == meta['sample_rate'] and independent.sig_len == meta['samples']
        assert independent.sig_name == [x['label'] for x in meta['signals']]
        digital_cells += digital.size
        physical_cells += physical.size
        clean_offsets = []
        if dataset == 'mitdb':
            originals[record] = (meta, digital)
        else:
            source_meta, source_digital = originals[record[:3]]
            assert [x['gain'] for x in meta['signals']] == [x['gain'] for x in source_meta['signals']]
            for start, end in [(0, 300), (420, 540), (660, 780), (900, 1020), (1140, 1260), (1380, 1500), (1620, 1740)]:
                delta = digital[start*360:end*360] - source_digital[start*360:end*360]
                ranges = np.ptp(delta, axis=0)
                assert np.all(ranges <= 1), (record, start, ranges.tolist())
                clean_cells += delta.size
                clean_offsets.append(dict(start_seconds=start, end_seconds=end, minimum_offset_adc=delta.min(axis=0).tolist(), maximum_offset_adc=delta.max(axis=0).tolist(), range_adc=ranges.tolist()))
        rows.append(dict(dataset=dataset, **meta, header_sha256=sha256(folder / (record + '.hea')), signal_sha256=sha256(folder / (record + '.dat')), digital_sample_comparison='all_equal', physical_conversion='all_within_1e-14_mV', clean_segment_shape_checks=clean_offsets))
    # Verify the original bytes still match the retrieval and publisher checksums.
    for item in acquisition['records']:
        assert sha256(args.private_root / item['dataset'] / item['name']) == item['sha256']
    result = dict(status='PASS_ORIGINALS_AND_INDEPENDENT_WFDB', wfdb_version=wfdb.__version__, numpy_version=np.__version__, records=len(rows), digital_samples_compared=digital_cells, physical_samples_compared=physical_cells, clean_interval_cells_checked=clean_cells, recording119_feature_or_performance_output=False, original_files_unchanged=True, native_records=rows)
    args.output.write_bytes((json.dumps(result, indent=2) + '\n').encode())
    print(json.dumps({k: v for k, v in result.items() if k != 'native_records'}))


if __name__ == '__main__':
    main()
