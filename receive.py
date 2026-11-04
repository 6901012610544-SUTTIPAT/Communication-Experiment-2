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

from manual_codec import (
    manual_ax25_decode,
    manual_ax25_encode,
    manual_kiss_decode,
    manual_kiss_encode,
)

CHUNK = 128
MAX_FILE_SIZE = 4 * 1024 * 1024
MAX_LINE = 4096  # ขยายจาก 1024 เพื่อรองรับบรรทัด FRAME ที่มี KISS Raw + AX.25 Hex


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
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", text)
    cleaned = cleaned.strip("._")[:80]
    return "payload_" + (cleaned or "file.bin")


def allocate_directory(root):
    day = datetime.now().astimezone().strftime("%Y-%m-%d")
    day_directory = root / day
    day_directory.mkdir(parents=True, exist_ok=True)

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
    def __init__(self, root, metadata, expected_reference=None):
        self.metadata = metadata
        self.expected_reference = expected_reference

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
        self.first_data_proof_printed = False

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

    def log_protocol_layers(self, packet_label, frame_proof, data_hex, data_summary):
        """
        บันทึก KISS_RAW, AX25, และ DATA ลงในไฟล์ .txt log อย่างชัดเจน
        พร้อมพิสูจน์การถอดรหัสด้วย Manual Codec
        """
        if frame_proof is not None:
            kiss_hex, ax25_hex, app_hex = frame_proof
            try:
                kiss_info = manual_kiss_decode(bytes.fromhex(kiss_hex))
                ax25_info = manual_ax25_decode(bytes.fromhex(ax25_hex))
                unesc_str = ",".join(kiss_info["unescape_log"]) or "none"
                ax25_hdr_desc = (
                    f"dest={ax25_info['dest']} "
                    f"src={ax25_info['src']} "
                    f"ctrl=0x{ax25_info['control']:02X} "
                    f"pid=0x{ax25_info['pid']:02X} "
                    f"valid={ax25_info['valid']}"
                )
            except ValueError as exc:
                unesc_str = f"decode_err({exc})"
                ax25_hdr_desc = "decode_err"

            self.log(
                f"KISS_RAW [{packet_label}] "
                f"len={len(kiss_hex)//2} "
                f"unescaped={unesc_str} "
                f"hex={kiss_hex}"
            )
            self.log(
                f"AX25     [{packet_label}] "
                f"{ax25_hdr_desc} "
                f"header_hex={ax25_hex[:32]} "
                f"full_ax25_hex={ax25_hex}"
            )
        else:
            self.log(f"KISS_RAW [{packet_label}] (no raw frame record from GS)")
            self.log(f"AX25     [{packet_label}] (no AX.25 frame record from GS)")

        self.log(
            f"DATA     [{packet_label}] "
            f"{data_summary} "
            f"payload_hex={data_hex}"
        )

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

    def accept_data(self, sequence, total, payload, frame_proof=None):
        if total != self.total:
            raise ValueError("DATA total differs from META")

        if not 0 <= sequence < self.total:
            raise ValueError("DATA sequence out of range")

        offset = sequence * self.chunk
        expected_length = min(self.chunk, self.size - offset)

        if len(payload) != expected_length:
            raise ValueError("DATA length differs from file layout")

        self.touch()

        if not self.first_data_proof_printed and frame_proof is not None:
            self.first_data_proof_printed = True
            kiss_hex, ax25_hex, _ = frame_proof
            ax_info = manual_ax25_decode(bytes.fromhex(ax25_hex))
            print(f"\n=== [GS PROTOCOL UNWRAP PROOF: DATA SEQ={sequence}] ===")
            print(f"  1) KISS RAW  ({len(kiss_hex)//2}B): {kiss_hex}")
            print(
                f"  2) AX.25 HDR (16B): {ax25_hex[:32]} "
                f"[Dest={ax_info['dest']}, Src={ax_info['src']}, "
                f"Ctrl=0x{ax_info['control']:02X}, PID=0x{ax_info['pid']:02X}]"
            )
            print(f"  3) DATA HEX  ({len(payload)}B): {payload.hex().upper()}")
            print("=======================================================")

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

        self.part_path.replace(self.final_path)

        self.done = True
        elapsed = time.monotonic() - self.started

        received_content = self.final_path.read_bytes()

        self.log(
            f"COMPLETE crc32={actual_crc:08X} "
            f"expected_crc32={self.expected_crc:08X} "
            f"crc_match=True "
            f"size={self.size} elapsed_seconds={elapsed:.3f} "
            f"file={self.final_path.name}"
        )

        print(
            f"[COMPLETE 0x{self.id:08X}] "
            f"CRC32 MATCH OK (expected={self.expected_crc:08X}, actual={actual_crc:08X}), "
            f"{self.size} bytes"
        )
        print(f"[FILE] {self.final_path}")

        # ตรวจสอบเทียบกับไฟล์/ข้อความต้นทางแบบ Byte-by-Byte (ถ้าผู้ใช้ระบุ --verify-file หรือ --verify-text)
        if self.expected_reference is not None:
            exact_match = received_content == self.expected_reference
            ref_crc = zlib.crc32(self.expected_reference) & 0xFFFFFFFF
            verify_msg = (
                f"SOURCE_VERIFY exact_byte_match={exact_match} "
                f"source_size={len(self.expected_reference)} "
                f"received_size={len(received_content)} "
                f"source_crc32={ref_crc:08X} "
                f"received_crc32={actual_crc:08X}"
            )
            self.log(verify_msg)
            print(f"[VERIFY] {verify_msg}")

        if self.size <= 65536:
            try:
                text = received_content.decode("utf-8")
            except UnicodeDecodeError:
                pass
            else:
                self.log(
                    "TEXT_UTF8 "
                    + json.dumps(text, ensure_ascii=False)
                )
                print(f"[TEXT PREVIEW] {text!r}")

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
        description="Receive decoded application records and KISS/AX.25 proof from GS Mega"
    )

    parser.add_argument("--port", required=True)
    parser.add_argument("--out", type=Path, default=Path("logs"))
    parser.add_argument("--idle", type=float, default=30.0)

    verify_group = parser.add_mutually_exclusive_group()
    verify_group.add_argument(
        "--verify-file",
        type=Path,
        help="Optional original file path to verify byte-for-byte match against received data",
    )
    verify_group.add_argument(
        "--verify-text",
        type=str,
        help="Optional original text string to verify byte-for-byte match against received data",
    )

    args = parser.parse_args()

    if args.idle <= 0:
        parser.error("--idle must be > 0")

    expected_reference = None
    if args.verify_file is not None:
        expected_reference = args.verify_file.read_bytes()
    elif args.verify_text is not None:
        expected_reference = args.verify_text.encode("utf-8")

    current = None
    pending_frame_proof = None

    try:
        with serial.Serial(
            args.port,
            115200,
            timeout=0.2,
            write_timeout=2,
        ) as port:
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

                    if kind == "FRAME":
                        if len(fields) != 4:
                            raise ValueError("FRAME field count")
                        # เก็บ (kiss_raw_hex, ax25_hex, app_hex) ไว้จับคู่กับ META/DATA/END ถัดไปทันที
                        pending_frame_proof = (fields[1], fields[2], fields[3])
                        continue

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

                            current = Transfer(
                                args.out, metadata, expected_reference
                            )

                        elif current.metadata != metadata:
                            raise ValueError(
                                "Same transfer ID has different metadata"
                            )

                        current.touch()
                        current.log_protocol_layers(
                            packet_label="META",
                            frame_proof=pending_frame_proof,
                            data_hex=fields[6],
                            data_summary=(
                                f"id=0x{metadata[0]:08X} total={metadata[1]} "
                                f"size={metadata[2]} crc32={metadata[3]:08X}"
                            ),
                        )
                        pending_frame_proof = None
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
                            pending_frame_proof = None
                            continue

                        current.log_protocol_layers(
                            packet_label=f"DATA seq={sequence}/{total}",
                            frame_proof=pending_frame_proof,
                            data_hex=fields[5],
                            data_summary=(
                                f"id=0x{transfer_id:08X} seq={sequence} "
                                f"total={total} len={length}"
                            ),
                        )
                        proof_to_pass = pending_frame_proof
                        pending_frame_proof = None
                        current.accept_data(
                            sequence, total, payload, frame_proof=proof_to_pass
                        )
                        continue

                    if kind == "END":
                        if len(fields) != 3:
                            raise ValueError("END field count")

                        transfer_id, total = map(int, fields[1:])

                        if current is None or current.id != transfer_id:
                            pending_frame_proof = None
                            continue

                        if total != current.total:
                            raise ValueError("END total differs from META")

                        current.touch()
                        current.log_protocol_layers(
                            packet_label="END",
                            frame_proof=pending_frame_proof,
                            data_hex="",
                            data_summary=f"id=0x{transfer_id:08X} total={total}",
                        )
                        pending_frame_proof = None
                        current.maybe_finish()
                        current.report_missing("END_OF_PASS")
                        continue

                    print("[WARN] Unknown USB record:", repr(line))

                except ValueError as exc:
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