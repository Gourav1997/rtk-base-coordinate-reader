"""Extract RTCM 1005/1006 antenna reference positions from a MAVLink tlog.

Install: python -m pip install -r requirements.txt
Run: python extract_base.py "C:\\Users\\dutta\\Downloads\\2026-11-25 18-58-54.tlog"
Timestamps are tlog receive times in UTC, not GNSS measurement times.
"""

import argparse
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import sys

from pymavlink import mavutil
from pyrtcm import RTCMReader, ecef2llh


class RTCMStream:
    def __init__(self, stats, on_position):
        self.buffer = bytearray()
        self.stats = stats
        self.on_position = on_position

    def reset(self):
        if self.buffer:
            self.stats['incomplete_rtcm_streams'] += 1
            self.buffer.clear()

    def feed(self, payload, timestamp):
        self.buffer.extend(payload)
        while self.buffer:
            if self.buffer[0] != 0xD3:
                del self.buffer[0]
                self.stats['discarded_bytes'] += 1
                continue
            if len(self.buffer) < 3:
                return
            if self.buffer[1] & 0xFC:
                del self.buffer[0]
                self.stats['discarded_bytes'] += 1
                continue
            size = 6 + ((self.buffer[1] & 3) << 8) + self.buffer[2]
            if len(self.buffer) < size:
                return
            frame = bytes(self.buffer[:size])
            try:
                _, message = RTCMReader(BytesIO(frame), quitonerror=2).read()
            except Exception:
                self.stats['invalid_rtcm_frames'] += 1
                del self.buffer[0]  # Resynchronize, including within a corrupt frame.
                continue
            del self.buffer[:size]
            if message is None:
                continue
            self.stats['valid_rtcm_frames'] += 1
            if message.identity in ('1005', '1006'):
                self.on_position(message, timestamp)


class Reassembler:
    """Per-sender ordered packets, with a bounded sequence reorder window.

    A modulo-32 sequence difference of 1..15 advances the stream; 16..31
    denotes a late packet. Missing packets are retired after 16 groups or
    at EOF. No bytes are joined across a known gap. Reordering beyond half
    the sequence space is inherently ambiguous and is discarded.
    """

    def __init__(self, stats, on_position):
        self.stats = stats
        self.stream = RTCMStream(stats, on_position)
        self.groups = OrderedDict()
        self.latest = None
        self.retired = None

    def drain(self, final=False):
        while self.groups:
            key, group = next(iter(self.groups.items()))
            if group['data'] is not None:
                if self.retired is not None and key != self.retired + 1:
                    self.stream.reset()
                self.stream.feed(group['data'], group['time'])
                self.retired = key
                del self.groups[key]
            elif final or len(self.groups) > 16:
                self.stats['incomplete_fragment_groups'] += 1
                self.stream.reset()
                self.retired = key
                del self.groups[key]
            else:
                break

    def add(self, msg):
        length = int(msg.len)
        if not 0 <= length <= 180 or length > len(msg.data):
            self.stats['invalid_mavlink_lengths'] += 1
            self.stream.reset()
            return
        payload = bytes(msg.data[:length])
        timestamp = getattr(msg, '_timestamp', None)
        if not msg.flags & 1:
            self.drain(final=True)
            self.stream.feed(payload, timestamp)
            # Some senders leave sequence bits zero for unfragmented data.
            self.latest = None
            self.retired = None
            return
        seq = (msg.flags >> 3) & 31
        index = (msg.flags >> 1) & 3
        if self.latest is None:
            absolute = seq
            self.latest = absolute
        else:
            delta = (seq - self.latest) & 31
            absolute = self.latest + (delta if delta < 16 else delta - 32)
            if absolute > self.latest:
                self.latest = absolute
        if absolute not in self.groups:
            if absolute < self.latest or (self.retired is not None and absolute <= self.retired):
                self.stats['late_fragments'] += 1
                return
            self.groups[absolute] = {'parts': {}, 'data': None, 'time': timestamp}
        group = self.groups[absolute]
        parts = group['parts']
        if index in parts:
            self.stats['duplicate_fragments'] += 1
            if parts[index] != payload:
                group['data'] = None
                parts.clear()
                self.stats['conflicting_fragments'] += 1
                self.stream.reset()
                return
        parts[index] = payload
        group['time'] = timestamp
        ends = [i for i, data in parts.items() if len(data) < 180]
        end = min(ends) if ends else 3
        if all(i in parts for i in range(end + 1)):
            if any(i > end for i in parts):
                self.stats['conflicting_fragments'] += 1
                return
            group['data'] = b''.join(parts[i] for i in range(end + 1))
        self.drain()

    def finish(self):
        self.drain(final=True)
        self.stream.reset()


def time_label(value):
    if value is None:
        return 'unknown'
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec='milliseconds')
    except (ValueError, OverflowError, OSError):
        return str(value)


def extract(path):
    stats = Counter()
    positions = OrderedDict()

    def record(message, timestamp):
        xyz = tuple(float(getattr(message, field)) for field in ('DF025', 'DF026', 'DF027'))
        # RTCM ECEF fields have 0.1 mm resolution; retain every distinct position.
        key = tuple(round(value * 10000) for value in xyz)
        if key not in positions:
            positions[key] = dict(xyz=xyz, llh=ecef2llh(*xyz), first=timestamp,
                                  last=timestamp, count=0, stations=set(), types=set())
        position = positions[key]
        position['last'] = timestamp
        position['count'] += 1
        position['stations'].add(message.DF003)
        position['types'].add(message.identity)

    senders = {}
    connection = mavutil.mavlink_connection(str(path), dialect='ardupilotmega')
    try:
        while True:
            msg = connection.recv_match(type='GPS_RTCM_DATA', blocking=False)
            if msg is None:
                break
            stats['gps_rtcm_data_messages'] += 1
            source = (msg.get_srcSystem(), msg.get_srcComponent())
            if source not in senders:
                senders[source] = Reassembler(stats, record)
            senders[source].add(msg)
    finally:
        connection.close()
    for sender in senders.values():
        sender.finish()
    return positions, stats


def format_results(positions, stats):
    """Shared human-readable output for the command line and desktop UI."""
    lines = []
    for number, position in enumerate(positions.values(), 1):
        lat, lon, alt = position['llh']
        lines.append(f'Position {number}: Latitude={lat:.10f} deg, Longitude={lon:.10f} deg, '
              f'Ellipsoidal altitude={alt:.4f} m')
        lines.append(f"  First UTC: {time_label(position['first'])}; Last UTC: {time_label(position['last'])}")
        lines.append(f"  Count: {position['count']}; Stations: {sorted(position['stations'])}; "
              f"RTCM types: {sorted(position['types'])}")
    if not stats['gps_rtcm_data_messages']:
        lines.append('No GPS_RTCM_DATA (233) messages found. This log contains no recorded RTCM injection stream.')
    elif not positions:
        lines.append('No valid RTCM 1005/1006 base positions found in the recorded correction stream.')
    lines.append('Diagnostics: ' + ', '.join(f'{key}={value}' for key, value in sorted(stats.items())))
    lines.append('Altitude is WGS84 ellipsoidal height of the antenna reference point (ARP), not mean sea level.\n'
          'RTCM 1006 antenna height is not added to the ARP coordinates.')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tlog', type=Path, help='MAVLink timestamped .tlog file')
    args = parser.parse_args()
    if not args.tlog.is_file():
        parser.error(f'File does not exist: {args.tlog}')
    try:
        positions, stats = extract(args.tlog)
    except (OSError, ValueError) as exc:
        print(f'Error reading log: {exc}', file=sys.stderr)
        return 1
    print(format_results(positions, stats))
    return 0 if positions else 2


if __name__ == '__main__':
    sys.exit(main())
