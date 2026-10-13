import argparse
import secrets
import struct
import sys
import time
import zlib
from pathlib import Path

import serial


CHUNK = 128
MAX_FILE_SIZE = 4 * 1024 * 1024

META = 1
DATA = 2
END = 3

HEADER = struct.Struct("<2sBBIIIH")


def crc32(data):
    return zlib.crc32(data) & 0xFFFFFFFF


def make_packet(kind, transfer_id, sequence, total, payload=b""):
    if len(payload) > CHUNK:
        raise ValueError("Payload exceeds CHUNK")

    header = HEADER.pack(
        b"CS",
        1,
        kind,
        transfer_id,
        sequence,
        total,
        len(payload),
    )

    body = header + payload
    return body + struct.pack("<I", crc32(body))


def kiss_encode(packet):
    raw = b"\x00" + packet
    raw = raw.replace(b"\xDB", b"\xDB\xDD")
    raw = raw.replace(b"\xC0", b"\xDB\xDC")
    return b"\xC0" + raw + b"\xC0"


def wait_local_ack(port, expected_token, timeout=6.0):
    deadline = time.monotonic() + timeout
    line = bytearray()
    discard = False

    while time.monotonic() < deadline:
        char = port.read(1)

        if not char:
            continue

        if char == b"\n":
            if not discard:
                text = line.rstrip(b"\r").decode(
                    "ascii", errors="replace"
                )

                if text == f"OK {expected_token}":
                    return True

                if text.startswith("ERR "):
                    print(f"\n[UNO] {text}")
                    return False

                if text:
                    print(f"\n[UNO] {text}")

            line.clear()
            discard = False
            continue

        if not discard:
            if len(line) < 160:
                line.extend(char)
            else:
                line.clear()
                discard = True

    return False


def send_packet(port, packet, retries=3):
    wire = kiss_encode(packet)
    token = struct.unpack_from("<I", packet, len(packet) - 4)[0]

    for attempt in range(1, retries + 1):
        port.reset_input_buffer()

        written = port.write(wire)

        if written != len(wire):
            raise RuntimeError("Incomplete USB serial write")

        port.flush()

        if wait_local_ack(port, token):
            return

        print(
            f"\n[RETRY LOCAL] attempt={attempt}/{retries}, "
            f"token={token}"
        )
        time.sleep(0.25)

    raise RuntimeError(
        "No local ACK from COMM. Check UNO↔Mega wiring, "
        "power, baud rate, and sketches."
    )


def encoded_name(name):
    # Remove path components; preserve a valid UTF-8 boundary.
    name = name.replace("\\", "/").rsplit("/", 1)[-1]

    raw = name.encode("utf-8")
    raw = raw[:48].decode("utf-8", errors="ignore").encode("utf-8")

    return raw or b"payload.bin"


def load_input(args):
    if args.file is not None:
        path = Path(args.file)

        with path.open("rb") as source:
            data = source.read(MAX_FILE_SIZE + 1)

        default_name = path.name
    else:
        data = args.text.encode("utf-8")
        default_name = "telemetry.txt"

    if len(data) > MAX_FILE_SIZE:
        raise ValueError("Maximum supported file size is 4 MiB")

    name = encoded_name(args.name or default_name)
    return data, name


def main():
    parser = argparse.ArgumentParser(
        description="Send file/text through UNO -> COMM -> HC-12"
    )

    parser.add_argument("--port", required=True)

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file")
    source.add_argument("--text")

    parser.add_argument("--name")
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument(
        "--id",
        type=lambda value: int(value, 0),
        dest="transfer_id",
    )
    parser.add_argument("--meta-every", type=int, default=32)

    args = parser.parse_args()

    if args.passes < 1:
        parser.error("--passes must be >= 1")

    if args.meta_every < 1:
        parser.error("--meta-every must be >= 1")

    if args.transfer_id is not None:
        if not 1 <= args.transfer_id <= 0xFFFFFFFF:
            parser.error("--id must be between 1 and 0xFFFFFFFF")

    assert HEADER.size == 18
    assert crc32(b"123456789") == 0xCBF43926

    data, name = load_input(args)

    transfer_id = args.transfer_id
    if transfer_id is None:
        transfer_id = secrets.randbelow(0xFFFFFFFF) + 1

    total = (len(data) + CHUNK - 1) // CHUNK
    file_crc = crc32(data)

    meta_payload = struct.pack(
        "<IIHB",
        len(data),
        file_crc,
        CHUNK,
        len(name),
    ) + name

    meta_packet = make_packet(
        META, transfer_id, 0, total, meta_payload
    )

    end_packet = make_packet(
        END, transfer_id, total, total
    )

    print(f"Transfer ID : 0x{transfer_id:08X}")
    print(f"Filename    : {name.decode('utf-8')!r}")
    print(f"Size        : {len(data)} bytes")
    print(f"Chunks      : {total}")
    print(f"File CRC32  : {file_crc:08X}")
    print(f"Passes      : {args.passes}")
    print("Local ACK does not confirm reception at GS.")

    started = time.monotonic()

    with serial.Serial(
        args.port,
        115200,
        timeout=0.1,
        write_timeout=3,
    ) as port:
        # Opening USB serial commonly resets an Arduino.
        time.sleep(2.5)
        port.reset_input_buffer()

        for pass_number in range(1, args.passes + 1):
            print(f"\n[PASS {pass_number}/{args.passes}]")

            for _ in range(3):
                send_packet(port, meta_packet)

            for sequence in range(total):
                if sequence and sequence % args.meta_every == 0:
                    send_packet(port, meta_packet)

                start = sequence * CHUNK
                payload = data[start:start + CHUNK]

                packet = make_packet(
                    DATA,
                    transfer_id,
                    sequence,
                    total,
                    payload,
                )

                send_packet(port, packet)

                percent = 100.0 * (sequence + 1) / total

                print(
                    f"\r[TX LOCAL] {sequence + 1}/{total} "
                    f"({percent:6.2f}%)",
                    end="",
                    flush=True,
                )

            if total:
                print()

            for _ in range(3):
                send_packet(port, end_packet)

    elapsed = time.monotonic() - started

    print(f"\nTransmission rounds finished in {elapsed:.1f} s.")
    print("Check the GS terminal for COMPLETE + CRC32 OK.")
    print(
        "To resend the same transfer while GS remains running, "
        f"use --id 0x{transfer_id:08X} with exactly the same data/name."
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped by user.", file=sys.stderr)
        sys.exit(130)
    except (OSError, ValueError, RuntimeError, serial.SerialException) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)