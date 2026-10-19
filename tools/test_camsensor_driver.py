#!/usr/bin/env python3
"""Regression for Renoir front's wrapped sensorDriverData layout."""
from pathlib import Path
import importlib.util
import struct
spec = importlib.util.spec_from_file_location('camsensor', Path(__file__).with_name('camsensor.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
expected = tuple(range(20))
for prefix in [b'', b'camera-module-root!!\0']:
    data = prefix + struct.pack('<20I', *expected)
    symbols = {7: ('sensorDriverData', len(prefix), 80)}
    def value(sid):
        _, offset, size = symbols[sid]
        return data[offset:offset+size]
    assert module.sensor_driver_words(value, symbols, [7]) == expected
for symbols, data in [({}, b''), ({7: ('sensorDriverData', 0, 12)}, b'\0'*12)]:
    try:
        module.sensor_driver_words(lambda sid: data, symbols, list(symbols))
    except ValueError:
        pass
    else:
        raise AssertionError('missing or truncated driver accepted')
print('Camera module parser: flat/wrapped driver, missing/truncated symbol passed')
