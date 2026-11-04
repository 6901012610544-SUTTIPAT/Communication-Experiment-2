import struct
import zlib

# ค่าคงที่ของ KISS Protocol
FEND = 0xC0   # Frame End
FESC = 0xDB   # Frame Escape
TFEND = 0xDC  # Transposed Frame End
TFESC = 0xDD  # Transposed Frame Escape
KISS_CMD_DATA = 0x00

# ค่าคงที่ของ AX.25
AX25_CTRL_UI = 0x03      # Unnumbered Information (UI) Frame
AX25_PID_NOL3 = 0xF0     # No Layer 3 protocol implemented


def crc32(data: bytes) -> int:
    """คำนวณ CRC-32/ISO-HDLC ให้ตรงกับฝั่ง Arduino"""
    return zlib.crc32(data) & 0xFFFFFFFF


def encode_ax25_address(callsign: str, ssid: int, is_command: bool, is_last: bool) -> bytes:
    """
    Manual Codec สำหรับเข้ารหัส Address ของ AX.25 (7 bytes):
    - 6 ไบต์แรก: ตัวอักษร ASCII 6 ตัว เลื่อนบิตไปทางซ้าย 1 บิต (<< 1)
    - ไบต์ที่ 7 (SSID byte): [C | R | R | SSID(4 bits) | Extension bit]
    """
    padded = callsign.upper().ljust(6)[:6]
    addr_bytes = bytearray()

    for ch in padded:
        addr_bytes.append((ord(ch) & 0x7F) << 1)

    c_bit = 0x80 if is_command else 0x00
    reserved_bits = 0x60  # บิตสำรอง 2 บิตเซ็ตเป็น 11 เสมอตามมาตรฐาน AX.25
    ssid_bits = (ssid & 0x0F) << 1
    ext_bit = 0x01 if is_last else 0x00  # 0 = มีฟิลด์ถัดไป, 1 = สิ้นสุด Address field

    ssid_byte = c_bit | reserved_bits | ssid_bits | ext_bit
    addr_bytes.append(ssid_byte)
    return bytes(addr_bytes)


def decode_ax25_address(raw_addr: bytes) -> dict:
    """Manual Codec สำหรับถอดรหัส Address 7 ไบต์ของ AX.25 กลับเป็น Callsign และสถานะบิต"""
    if len(raw_addr) != 7:
        raise ValueError("AX.25 address field must be 7 bytes")

    chars = []
    for b in raw_addr[:6]:
        chars.append(chr(b >> 1))

    callsign = "".join(chars).rstrip()
    ssid_byte = raw_addr[6]

    return {
        "callsign": callsign,
        "ssid": (ssid_byte >> 1) & 0x0F,
        "c_bit": (ssid_byte >> 7) & 0x01,
        "reserved": (ssid_byte >> 5) & 0x03,
        "extension_bit": ssid_byte & 0x01,
        "raw_hex": raw_addr.hex().upper(),
    }


def manual_ax25_encode(
    info_payload: bytes,
    dest_callsign: str = "GROUND",
    dest_ssid: int = 0,
    src_callsign: str = "CUBSAT",
    src_ssid: int = 0,
) -> bytes:
    """
    สร้างเฟรม AX.25 UI แบบ Manual (16-byte Header + Info Payload)
    ตรงกับฟังก์ชัน makeAxHeader() ใน LinkProtocol.h
    """
    dest_addr = encode_ax25_address(dest_callsign, dest_ssid, is_command=True, is_last=False)
    src_addr = encode_ax25_address(src_callsign, src_ssid, is_command=False, is_last=True)
    header = dest_addr + src_addr + bytes([AX25_CTRL_UI, AX25_PID_NOL3])
    return header + info_payload


def manual_ax25_decode(ax25_frame: bytes) -> dict:
    """ถอดรหัสเฟรม AX.25 แบบ Manual เพื่อแยก Header และ Info Payload"""
    if len(ax25_frame) < 16:
        raise ValueError(f"AX.25 frame too short ({len(ax25_frame)} bytes)")

    dest = decode_ax25_address(ax25_frame[0:7])
    src = decode_ax25_address(ax25_frame[7:14])
    control = ax25_frame[14]
    pid = ax25_frame[15]
    info = ax25_frame[16:]

    valid = (
        dest["callsign"] == "GROUND"
        and dest["ssid"] == 0
        and dest["raw_hex"][-2:] == "E0"
        and src["callsign"] == "CUBSAT"
        and src["ssid"] == 0
        and src["raw_hex"][-2:] == "61"
        and control == AX25_CTRL_UI
        and pid == AX25_PID_NOL3
    )

    return {
        "valid": valid,
        "dest": f"{dest['callsign']}-{dest['ssid']}",
        "src": f"{src['callsign']}-{src['ssid']}",
        "dest_detail": dest,
        "src_detail": src,
        "control": control,
        "pid": pid,
        "header_hex": ax25_frame[:16].hex().upper(),
        "info_hex": info.hex().upper(),
        "info_bytes": info,
    }


def manual_kiss_encode(frame_payload: bytes, cmd_byte: int = KISS_CMD_DATA) -> tuple[bytes, list[str]]:
    """
    Manual Codec สำหรับหุ้ม KISS Frame ทีละไบต์ (State-by-State):
    [FEND (0xC0)] + [CMD (0x00)] + [Escaped Data] + [FEND (0xC0)]
    """
    out = bytearray()
    escape_log = []

    out.append(FEND)

    # รวม Command Byte เข้ากับข้อมูลที่จะทำ Byte Stuffing
    raw_input = bytes([cmd_byte]) + frame_payload

    for idx, b in enumerate(raw_input):
        if b == FEND:
            out.append(FESC)
            out.append(TFEND)
            escape_log.append(f"byte[{idx}]=0xC0(FEND) -> 0xDB 0xDC")
        elif b == FESC:
            out.append(FESC)
            out.append(TFESC)
            escape_log.append(f"byte[{idx}]=0xDB(FESC) -> 0xDB 0xDD")
        else:
            out.append(b)

    out.append(FEND)
    return bytes(out), escape_log


def manual_kiss_decode(kiss_wire: bytes) -> dict:
    """
    Manual Codec สำหรับถอดกรอบ KISS ทีละไบต์เหมือน State Machine ใน Arduino KissRx
    """
    if len(kiss_wire) < 3 or kiss_wire[0] != FEND or kiss_wire[-1] != FEND:
        raise ValueError("Invalid KISS frame boundary (missing FEND 0xC0)")

    inner = kiss_wire[1:-1]
    unescaped = bytearray()
    escaped = False
    unescape_log = []

    for idx, b in enumerate(inner):
        if escaped:
            if b == TFEND:
                unescaped.append(FEND)
                unescape_log.append(f"pos[{idx}]: 0xDB 0xDC -> 0xC0")
            elif b == TFESC:
                unescaped.append(FESC)
                unescape_log.append(f"pos[{idx}]: 0xDB 0xDD -> 0xDB")
            else:
                raise ValueError(f"Invalid KISS escape sequence: 0xDB 0x{b:02X}")
            escaped = False
        elif b == FESC:
            escaped = True
        elif b == FEND:
            raise ValueError("Unexpected unescaped FEND inside KISS frame")
        else:
            unescaped.append(b)

    if escaped or len(unescaped) < 1:
        raise ValueError("Incomplete KISS frame")

    cmd_byte = unescaped[0]
    payload = bytes(unescaped[1:])

    return {
        "cmd_byte": cmd_byte,
        "payload": payload,
        "payload_hex": payload.hex().upper(),
        "unescape_log": unescape_log,
        "raw_hex": kiss_wire.hex().upper(),
    }


def format_codec_proof(app_packet: bytes, label: str = "PACKET") -> str:
    """สร้างข้อความสรุปการพิสูจน์การเข้าและถอดรหัส AX.25 + KISS แบบละเอียด"""
    local_kiss, local_esc = manual_kiss_encode(app_packet)
    ax25_frame = manual_ax25_encode(app_packet)
    rf_kiss, rf_esc = manual_kiss_encode(ax25_frame)

    # ทดสอบถอดรหัสย้อนกลับเพื่อพิสูจน์ว่า Manual Codec ทำงานถูกต้อง 100%
    decoded_kiss = manual_kiss_decode(rf_kiss)
    decoded_ax25 = manual_ax25_decode(decoded_kiss["payload"])
    loopback_match = decoded_ax25["info_bytes"] == app_packet

    lines = [
        f"=== [MANUAL CODEC PROOF: {label}] ===",
        f"1) Application Packet ({len(app_packet)} bytes):",
        f"   HEX : {app_packet.hex().upper()}",
        f"2) Local KISS Frame [PC -> UNO -> Mega] ({len(local_kiss)} bytes):",
        f"   HEX : {local_kiss.hex().upper()}",
        f"   Stuffing: {local_esc if local_esc else 'None (no 0xC0/0xDB in packet)'}",
        f"3) AX.25 UI Frame [Mega builds 16B Header + App Packet] ({len(ax25_frame)} bytes):",
        f"   Dest Address (7B): {ax25_frame[0:7].hex().upper()} ('GROUND-0' shifted << 1, SSID=0xE0)",
        f"   Src  Address (7B): {ax25_frame[7:14].hex().upper()} ('CUBSAT-0' shifted << 1, SSID=0x61)",
        f"   Control & PID(2B): {ax25_frame[14:16].hex().upper()} (Ctrl=0x03 UI, PID=0xF0 No L3)",
        f"   Full AX.25 HEX   : {ax25_frame.hex().upper()}",
        f"4) RF KISS Frame [Mega -> HC-12 -> GS] ({len(rf_kiss)} bytes):",
        f"   HEX : {rf_kiss.hex().upper()}",
        f"   Stuffing: {rf_esc if rf_esc else 'None (no 0xC0/0xDB in AX.25 frame)'}",
        f"5) Manual Codec Loopback Verification: {'PASS (EXACT MATCH)' if loopback_match else 'FAIL'}",
        "==========================================",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    # ทดสอบจำลองข้อมูลที่มีทั้งข้อความและไบต์พิเศษ 0xC0, 0xDB เพื่อพิสูจน์ Byte Stuffing
    test_payload = b"HELLO_CUBESAT_" + bytes([0xC0, 0xDB, 0x12, 0x34])
    print(format_codec_proof(test_payload, label="STANDALONE SELF-TEST WITH 0xC0 & 0xDB"))