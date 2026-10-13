import argparse
import json
import re
import sys
import time
import zlib
from datetime import datetime
from itertools import islice
from pathlib import Path

import serial


CHUNK = 128
MAX_FILE_SIZE = 4 * 1024 * 1024
MAX_LINE = 1024


def timestamp():
    return datetime.now().astimezone().isoformat(
        timespec="milliseconds"
    )


def serial_lines(port):
    """Read complete ASCII records; tolerate partial USB reads."""
    buffer = bytearray()
    discard = False

    while True:
        block = port.read(min(port.in_waiting or 1, 4096))

        if not block:
            yield None
            continue

        for value in block:
            if value == 10:
                if not discard:
                    yield bytes(buffer).rstrip(b"\r")

                buffer.clear()
                discard = False
                continue

            if not discard:
                if len(buffer) < MAX_LINE:
                    buffer.append(value)
                else:
                    buffer.clear()
                    discard = True
                    print("[WARN] Oversized USB record discarded")


def safe_filename(name_bytes):
    text = name_bytes.decode("utf-8", errors="replace")
    text = text.replace("\\", "/").rsplit("/", 1)[-1]

    #Keep output paths independent of names received over RF.
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", text)
    cleaned = cleaned.strip("._")[:80]

    return "payload_" + (cleaned or "file.bin")


def allocate_directory(root):
    day = datetime.now().astimezone().strftime("%Y-%m-%d")
    day_directory = root / day
    day_directory.mkdir(parents=True, exist_ok=True)

    #Directory name depends only on the daily counter.
    #mkdir() reserves the counter without overwriting an old session.
    for number in range(1, 1_000_000):
        directory = day_directory / f"RX_{number:06d}"

        try:
            directory.mkdir()
            return directory, number
        except FileExistsError:
            continue

    raise RuntimeError("Daily receive counter exhausted")


def parse_meta(fields):
    if len(fields) != 7:
        raise ValueError("META field count")

    transfer_id, total, size, file_crc, chunk = map(
        int, fields[1:6]
    )
    name = bytes.fromhex(fields[6])

    if not 1 <= transfer_id <= 0xFFFFFFFF:
        raise ValueError("META transfer ID")

    if not 0 <= size <= MAX_FILE_SIZE:
        raise ValueError("META file size")

    if not 0 <= file_crc <= 0xFFFFFFFF:
        raise ValueError("META CRC32")

    if chunk != CHUNK:
        raise ValueError("META chunk size")

    if total != (size + CHUNK - 1) // CHUNK:
        raise ValueError("META total")

    if not 1 <= len(name) <= 48:
        raise ValueError("META filename length")

    return transfer_id, total, size, file_crc, chunk, name


class Transfer:
    def __init__(self, root, metadata):
        self.metadata = metadata

        (
            self.id,
            self.total,
            self.size,
            self.expected_crc,
            self.chunk,
            self.name,
        ) = metadata

        self.directory, self.daily_number = allocate_directory(root)

        log_name = (
            f"RX_{self.daily_number:06d}_{self.id:08X}.txt"
        )

        self.log_path = self.directory / log_name
        self.final_path = self.directory / safe_filename(self.name)
        self.part_path = Path(str(self.final_path) + ".part")

        self.log_file = self.log_path.open(
            "x", encoding="utf-8", newline="\n"
        )

        self.file = self.part_path.open("x+b")
        self.file.truncate(self.size)

        self.seen = bytearray(self.total)
        self.received = 0
        self.received_bytes = 0
        self.duplicates = 0

        self.done = False
        self.failed = False

        self.started = time.monotonic()
        self.last_seen = self.started
        self.last_report = 0.0
        self.idle_reported = False

        original_name = self.name.decode(
            "utf-8", errors="replace"
        )

        self.log(
            "START "
            f"id=0x{self.id:08X} "
            f"daily_receive={self.daily_number} "
            f"size={self.size} "
            f"total={self.total} "
            f"crc32={self.expected_crc:08X} "
            "original_name="
            + json.dumps(original_name, ensure_ascii=False)
        )

        print(
            f"\n[START] id=0x{self.id:08X}, "
            f"daily receive={self.daily_number}, "
            f"size={self.size}, chunks={self.total}"
        )
        print(f"[LOG] {self.log_path}")

    def log(self, message):
        self.log_file.write(f"{timestamp()} {message}\n")
        self.log_file.flush()

    def touch(self):
        self.last_seen = time.monotonic()
        self.idle_reported = False

    def missing_preview(self):
        return list(islice(
            (i for i, present in enumerate(self.seen) if not present),
            20,
        ))

    def report_missing(self, reason):
        if self.done or self.failed:
            return

        missing = self.total - self.received
        preview = self.missing_preview()

        message = (
            f"{reason} received={self.received}/{self.total} "
            f"missing={missing} first_missing={preview}"
        )

        self.log(message)
        print(f"[INCOMPLETE 0x{self.id:08X}] {message}")

    def fail(self, reason):
        self.failed = True
        self.log("FAILED " + reason)

        if self.file is not None:
            self.file.flush()
            self.file.close()
            self.file = None

        print(f"[FAILED 0x{self.id:08X}] {reason}")
        print(f"[PARTIAL] {self.part_path}")

    def accept_data(self, sequence, total, payload):
        if total != self.total:
            raise ValueError("DATA total differs from META")

        if not 0 <= sequence < self.total:
            raise ValueError("DATA sequence out of range")

        offset = sequence * self.chunk
        expected_length = min(self.chunk, self.size - offset)

        if len(payload) != expected_length:
            raise ValueError("DATA length differs from file layout")

        self.touch()

        if self.done or self.failed:
            self.duplicates += 1
            return

        if self.seen[sequence]:
            self.duplicates += 1

            self.file.seek(offset)
            previous = self.file.read(len(payload))

            if previous != payload:
                self.fail(
                    f"Conflicting payload for sequence={sequence}; "
                    "use a new transfer ID and investigate."
                )

            return

        self.file.seek(offset)
        written = self.file.write(payload)

        if written != len(payload):
            raise OSError("Incomplete file write")

        self.seen[sequence] = 1
        self.received += 1
        self.received_bytes += len(payload)

        now = time.monotonic()

        if now - self.last_report >= 1.0 or self.received == self.total:
            self.last_report = now

            percent = (
                100.0 * self.received_bytes / self.size
                if self.size else 100.0
            )

            print(
                f"[RX 0x{self.id:08X}] "
                f"{self.received}/{self.total} chunks, "
                f"{percent:6.2f}%, "
                f"{self.received_bytes}/{self.size} bytes, "
                f"duplicates={self.duplicates}"
            )

        self.maybe_finish()

    def maybe_finish(self):
        if self.done or self.failed:
            return

        if self.received != self.total:
            return

        self.file.flush()
        self.file.seek(0)

        actual_crc = 0

        while True:
            block = self.file.read(65536)

            if not block:
                break

            actual_crc = zlib.crc32(block, actual_crc)

        actual_crc &= 0xFFFFFFFF

        if actual_crc != self.expected_crc:
            self.fail(
                f"FILE_CRC_MISMATCH expected={self.expected_crc:08X} "
                f"actual={actual_crc:08X}"
            )
            return

        self.file.close()
        self.file = None

        # Directory is unique to this receive session.
        self.part_path.replace(self.final_path)

        self.done = True
        elapsed = time.monotonic() - self.started

        self.log(
            f"COMPLETE crc32={actual_crc:08X} "
            f"size={self.size} elapsed_seconds={elapsed:.3f} "
            f"file={self.final_path.name}"
        )

        print(
            f"[COMPLETE 0x{self.id:08X}] "
            f"CRC32 OK={actual_crc:08X}, {self.size} bytes"
        )
        print(f"[FILE] {self.final_path}")

        # Also make small UTF-8 telemetry readable in the text log.
        # json.dumps prevents embedded newlines/control characters
        # from changing the log structure.
        if self.size <= 65536:
            try:
                text = self.final_path.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                pass
            else:
                self.log(
                    "TEXT_UTF8 "
                    + json.dumps(text, ensure_ascii=False)
                )

    def close(self):
        if self.file is not None:
            self.file.flush()
            self.file.close()
            self.file = None

        status = (
            "COMPLETE" if self.done
            else "FAILED" if self.failed
            else "INCOMPLETE"
        )

        self.log(
            f"SESSION_CLOSED status={status} "
            f"received={self.received}/{self.total} "
            f"duplicates={self.duplicates}"
        )

        self.log_file.close()


def main():
    parser = argparse.ArgumentParser(
        description="Receive decoded application records from GS Mega"
    )

    parser.add_argument("--port", required=True)
    parser.add_argument("--out", type=Path, default=Path("logs"))
    parser.add_argument("--idle", type=float, default=30.0)

    args = parser.parse_args()

    if args.idle <= 0:
        parser.error("--idle must be > 0")

    current = None

    try:
        with serial.Serial(
            args.port,
            115200,
            timeout=0.2,
            write_timeout=2,
        ) as port:
            # Opening the port commonly resets the GS Arduino.
            time.sleep(2.5)
            port.reset_input_buffer()

            print(f"[READY] GS USB port={args.port}")
            print("[READY] Start the CubeSat sender now.")

            for raw in serial_lines(port):
                if raw is None:
                    if (
                        current is not None
                        and not current.done
                        and not current.failed
                        and not current.idle_reported
                        and time.monotonic() - current.last_seen >= args.idle
                    ):
                        current.report_missing("IDLE_TIMEOUT")
                        current.idle_reported = True

                    continue

                if not raw:
                    continue

                try:
                    line = raw.decode("ascii")
                    fields = line.split("\t")
                    kind = fields[0]

                    if kind == "STAT":
                        if len(fields) != 4:
                            raise ValueError("STAT field count")

                        accepted, rejected, bad_kiss = map(
                            int, fields[1:]
                        )

                        print(
                            f"[GS] accepted={accepted}, "
                            f"rejected_packet={rejected}, "
                            f"rejected_kiss={bad_kiss}"
                        )

                        if current is not None:
                            current.log("GS_" + line)

                        continue

                    if kind.startswith("READY"):
                        print("[ARDUINO] " + line)
                        continue

                    if kind == "META":
                        metadata = parse_meta(fields)

                        if current is None or current.id != metadata[0]:
                            if current is not None:
                                current.report_missing("NEW_TRANSFER")
                                current.close()
                                current = None

                            current = Transfer(args.out, metadata)

                        elif current.metadata != metadata:
                            raise ValueError(
                                "Same transfer ID has different metadata"
                            )

                        current.touch()
                        current.log("RX " + line)
                        current.maybe_finish()
                        continue

                    if kind == "DATA":
                        if len(fields) != 6:
                            raise ValueError("DATA field count")

                        transfer_id, sequence, total, length = map(
                            int, fields[1:5]
                        )

                        payload = bytes.fromhex(fields[5])

                        if length != len(payload) or not 1 <= length <= CHUNK:
                            raise ValueError("DATA payload length")

                        if current is None or current.id != transfer_id:
                            print(
                                f"[ORPHAN] DATA id=0x{transfer_id:08X}; "
                                "waiting for its META"
                            )
                            continue

                        current.log("RX " + line)
                        current.accept_data(sequence, total, payload)
                        continue

                    if kind == "END":
                        if len(fields) != 3:
                            raise ValueError("END field count")

                        transfer_id, total = map(int, fields[1:])

                        if current is None or current.id != transfer_id:
                            continue

                        if total != current.total:
                            raise ValueError("END total differs from META")

                        current.touch()
                        current.log("RX " + line)
                        current.maybe_finish()
                        current.report_missing("END_OF_PASS")
                        continue

                    print("[WARN] Unknown USB record:", repr(line))

                except ValueError as exc:
                    # UnicodeDecodeError is also a ValueError.
                    print(f"[WARN] Bad USB record: {exc}; raw={raw!r}")

                    if current is not None:
                        current.log(
                            f"BAD_USB_RECORD error={exc!s} raw={raw!r}"
                        )

    finally:
        if current is not None:
            current.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nReceiver stopped; incomplete files remain .part.")
        sys.exit(130)
    except (OSError, RuntimeError, serial.SerialException) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)