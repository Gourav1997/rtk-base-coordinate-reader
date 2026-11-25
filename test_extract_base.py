import unittest
from collections import Counter
from types import SimpleNamespace

from pyrtcm import calc_crc24q

from extract_base import Reassembler


def frame1005():
    # Independent RTCM bit layout: station 7, ECEF=(6378137, 0, 0) m.
    fields = [(1005, 12), (7, 12), (0, 6), (1, 1), (1, 1),
              (1, 1), (0, 1), (63781370000, 38), (0, 1), (0, 1),
              (0, 38), (0, 2), (0, 38)]
    bits = ''.join(f'{value:0{width}b}' for value, width in fields)
    payload = int(bits, 2).to_bytes(len(bits) // 8, 'big')
    raw = b'\xd3' + len(payload).to_bytes(2, 'big') + payload
    return raw + calc_crc24q(raw).to_bytes(3, 'big')


def message(data, seq=0, index=0, fragmented=True):
    return SimpleNamespace(flags=(seq << 3) | (index << 1) | int(fragmented),
                           len=len(data), data=data, _timestamp=123.0)


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.stats = Counter()
        self.found = []
        self.r = Reassembler(self.stats, lambda msg, time: self.found.append(msg))

    def test_unfragmented_and_stream_spanning_packets(self):
        raw = frame1005()
        self.r.add(message(raw[:10], fragmented=False))
        self.r.add(message(raw[10:] + raw, fragmented=False))
        self.assertEqual(len(self.found), 2)
        self.assertEqual(self.found[0].DF025, 6378137)
        self.assertEqual(self.found[0].DF003, 7)

    def test_out_of_order_and_wrap(self):
        raw = frame1005()
        data = raw * 10  # 250 bytes, requiring two fragments.
        for seq in (31, 0):
            self.r.add(message(data[180:], seq, 1))
            self.r.add(message(data[:180], seq, 0))
        self.assertEqual(len(self.found), 20)

    def test_four_full_fragments(self):
        data = frame1005() * 28 + b'\x00' * 20
        self.assertEqual(len(data), 720)
        for index in (3, 1, 0, 2):
            self.r.add(message(data[index * 180:(index + 1) * 180], 2, index))
        self.assertEqual(len(self.found), 28)

    def test_zero_length_terminator(self):
        self.r.add(message(b'', 1, 1))
        self.r.add(message(frame1005() * 7 + b'\x00' * 5, 1, 0))
        self.assertEqual(len(self.found), 7)

    def test_missing_fragment_does_not_join_streams(self):
        self.r.add(message(frame1005()[:10], fragmented=False))
        self.r.add(message(b'x' * 180, 1, 0))
        self.r.add(message(frame1005(), 2, 0))
        self.assertEqual(len(self.found), 0)  # Held behind missing group.
        self.r.finish()
        self.assertEqual(len(self.found), 1)
        self.assertEqual(self.stats['incomplete_fragment_groups'], 1)

    def test_crc_recovery_and_truncation(self):
        raw = frame1005()
        bad = raw[:-1] + bytes([raw[-1] ^ 1])
        self.r.add(message(bad + raw + raw[:8], fragmented=False))
        self.r.finish()
        self.assertEqual(len(self.found), 1)
        self.assertEqual(self.stats['invalid_rtcm_frames'], 1)
        self.assertEqual(self.stats['incomplete_rtcm_streams'], 1)


if __name__ == '__main__':
    unittest.main()
