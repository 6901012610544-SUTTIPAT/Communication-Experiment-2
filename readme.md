## CubeSat Communication Experiment

ทดลองสื่อสารจาก CubeSat จำลองไปยัง Ground Station โดยใช้ Arduino, HC-12, KISS และ AX.25 พร้อมโปรแกรม Python สำหรับส่งข้อความ/ไฟล์ และรับข้อมูลเพื่อบันทึก log หรือประกอบไฟล์กลับ

> โครงการนี้เป็นชุดทดลองบนโต๊ะปฏิบัติการ ไม่ใช่ระบบสื่อสารสำหรับการบินจริง โค้ดต้องผ่านการคอมไพล์และทดสอบกับฮาร์ดแวร์ก่อนใช้งาน

### 1. วัตถุประสงค์

- จำลองการส่งข้อมูลจาก Payload/OBC ไปยัง Communication Subsystem ของ CubeSat
- ใช้ KISS สำหรับแบ่งขอบเขตเฟรมในการสื่อสารระหว่าง Arduino
- ส่งข้อมูลผ่าน HC-12 โดยใช้ AX.25 UI frame ที่หุ้มด้วย KISS
- ให้ Arduino ฝั่ง Ground Station ถอด KISS และ AX.25 ก่อนส่งข้อมูลเข้า Laptop
- ใช้ Python ฝั่ง CubeSat ส่งข้อความหรือไฟล์ เช่น telemetry, JPEG และ PNG
- ใช้ Python ฝั่ง Ground Station บันทึก log พร้อมวันเวลาและเลขครั้งรับประจำวัน
- ตรวจสอบความครบถ้วนของข้อมูลด้วย sequence number และ CRC32
- ทดลองผลของข้อมูลสูญหาย การส่งซ้ำ และการประกอบไฟล์จาก packet ที่ได้รับ

**ข้อจำกัดสำคัญ:** Ground Station รับข้อมูลผ่านวิทยุอย่างเดียว ไม่มี RF ACK กลับไปยัง CubeSat ดังนั้นสถานะส่งสำเร็จฝั่งผู้ส่งไม่ได้ยืนยันว่าฝั่ง Ground Station ได้รับข้อมูลครบ

### 2. ภาพรวมระบบ

```text
Laptop ฝั่ง CubeSat
  send.py
  อ่านข้อความ/ไฟล์ → Application packet + CRC32 → KISS
        |
        | USB serial: 115200 baud
        v
Arduino UNO R3
  จำลอง Payload/OBC
  รับ KISS → ตรวจ packet → ส่งต่อด้วย KISS
        |
        | UART: 9600 baud
        | มี ACK เฉพาะสาย UNO ↔ COMM
        v
Arduino Mega 2560 ฝั่ง COMM
  ถอด KISS → เพิ่ม AX.25 header → หุ้ม KISS
        |
        | Serial1: 9600 baud
        v
HC-12 ฝั่ง CubeSat
        |
        | RF: ส่งทางเดียว
        v
HC-12 ฝั่ง Ground Station
        |
        | Serial1: 9600 baud
        v
Arduino Mega 2560 ฝั่ง Ground Station
  ถอด KISS → ตรวจ/ถอด AX.25 → ตรวจ Application CRC32
        |
        | USB serial: 115200 baud
        | ส่งข้อมูลที่ถอดแล้วเป็น record แบบข้อความ
        v
Laptop ฝั่ง Ground Station
  receive.py
  บันทึก log → ประกอบไฟล์ → ตรวจ CRC32 ของไฟล์
```

**Python ฝั่ง GS ไม่ถอด KISS หรือ AX.25** แต่รับ application record ที่ Arduino ถอดแล้ว จากนั้นแปลง payload แบบ hex กลับเป็น bytes และประกอบไฟล์

### 3. ความหมายของ KISS และ AX.25 ในโครงการนี้

โครงการนี้ใช้ HC-12 เป็น transparent UART radio เพื่อส่ง byte stream รูปแบบต่อไปนี้:

```text
KISS frame
└── KISS command: 0x00
    └── AX.25 UI frame
        ├── Destination: GROUND-0
        ├── Source: CUBSAT-0
        ├── Control: 0x03
        ├── PID: 0xF0
        └── Application packet + CRC32
```

การใช้งานนี้มีขอบเขตดังนี้:
- ใช้ KISS port 0 และ data command 0
- ใช้ AX.25 UI frame แบบไม่มี digipeater
- ใช้ AX.25 header แบบกำหนดตายตัวสำหรับชุดทดลอง
- ไม่สร้าง HDLC flags, bit stuffing, NRZI หรือ AX.25 FCS ที่ Arduino
- ใช้ application CRC32 ตรวจความถูกต้องของ packet
- HC-12 ไม่ได้ทำหน้าที่เป็น AX.25 TNC

**จึงไม่ใช่การส่ง AX.25 over-the-air แบบมาตรฐาน และไม่สามารถสื่อสารกับสถานี AX.25/APRS ทั่วไปได้โดยตรง**

`GROUND` และ `CUBSAT` เป็นชื่อสำหรับชุดทดลอง ไม่ใช่การจัดสรร callsign สำหรับออกอากาศจริง

### 4. โครงสร้าง Repository

จัดไฟล์โปรแกรมตามโครงสร้างนี้:

```text
.
├── README.md
├── send.py
├── receive.py
├── firmware/
│   ├── PayloadUNO/
│   │   ├── PayloadUNO.ino
│   │   └── LinkProtocol.h
│   ├── COMMMega/
│   │   ├── COMMMega.ino
│   │   └── LinkProtocol.h
│   └── GSMega/
│       ├── GSMega.ino
│       └── LinkProtocol.h
└── logs/
    └── สร้างอัตโนมัติเมื่อเริ่มรับ transfer
```

| ไฟล์ | หน้าที่ |
|---|---|
| `send.py` | อ่านข้อความ/ไฟล์ สร้าง packet และส่งเข้า UNO |
| `receive.py` | รับข้อมูลที่ GS Arduino ถอดแล้ว บันทึก log และประกอบไฟล์ |
| `PayloadUNO.ino` | รับข้อมูลจาก Python และส่งต่อไป COMM |
| `COMMMega.ino` | หุ้ม AX.25/KISS และส่งเข้า HC-12 |
| `GSMega.ino` | รับข้อมูลผ่าน HC-12 ถอด protocol และส่ง record เข้า Laptop |
| `LinkProtocol.h` | นิยาม packet, CRC32, KISS parser และ AX.25 header ร่วมกัน |

ไฟล์ `LinkProtocol.h` ทั้งสามตำแหน่งต้องมีเนื้อหาเหมือนกัน หากแก้ไข protocol ต้องอัปเดตให้ตรงกันทั้งหมด

เอกสารนี้อธิบายการใช้งานโปรแกรมตามชื่อข้างต้น ไม่ได้รวม source code ของโปรแกรมเหล่านั้นไว้ภายใน README

### 5. อุปกรณ์และซอฟต์แวร์

| รายการ | จำนวน/รายละเอียด |
|---|---|
| Arduino Mega 2560 | 2 ตัว: COMM และ Ground Station |
| Arduino UNO R3 | 1 ตัว: Payload/OBC จำลอง |
| HC-12 | 2 ตัว พร้อมเสาอากาศที่เหมาะสม |
| สาย USB | สำหรับอัปโหลดโปรแกรม สื่อสาร และจ่ายไฟตามการจัดระบบ |
| สายสัญญาณ | สำหรับ UART และ GND |
| แหล่งจ่ายไฟ | ต้องรองรับกระแสของ Arduino และ HC-12 |
| วงจรปรับระดับแรงดัน | ใช้ตามข้อกำหนดลอจิกของ HC-12 รุ่นจริง |
| Capacitor decoupling | แนะนำติดตั้งใกล้ HC-12 |
| Laptop/Computer | ใช้ 1 เครื่องเปิดสอง terminal หรือใช้ 2 เครื่องแยกฝั่ง |
| Arduino IDE | สำหรับคอมไพล์และอัปโหลด sketch |
| Python | แนะนำ Python 3.10 ขึ้นไป |
| Python dependency | `pyserial` |

หากใช้ Laptop เครื่องเดียว ต้องเลือก USB serial port ของ UNO และ GS Mega ให้ต่างกัน ส่วน COMM Mega ต้องได้รับไฟเลี้ยงด้วย แม้ไม่ได้ใช้ USB สื่อสารกับ Python

### 6. การต่อวงจร

**การต่อ GND อย่างเดียวไม่สามารถส่งข้อมูลได้** ต้องมีสาย TX → RX และมี GND ร่วมกันระหว่างอุปกรณ์ที่ต่อ UART

**UNO ↔ COMM Mega**

| UNO R3 | COMM Mega 2560 | หน้าที่ |
|---|---|---|
| D11 — SoftwareSerial TX | D17 — RX2 | ส่งข้อมูลจาก UNO ไป COMM |
| D10 — SoftwareSerial RX | D16 — TX2 | รับ local ACK จาก COMM |
| GND | GND | แรงดันอ้างอิงร่วมกัน |
| USB | Laptop ฝั่ง CubeSat | รับข้อมูลจาก `send.py` |

UNO ใช้ D10/D11 เพื่อหลีกเลี่ยงการใช้ D0/D1 ร่วมกับ USB serial

**COMM Mega ↔ HC-12 ฝั่ง CubeSat**

| COMM Mega | HC-12 | หมายเหตุ |
|---|---|---|
| D18 — TX1 | RXD | ผ่านวงจรปรับระดับแรงดันตามความจำเป็น |
| GND | GND | ต้องต่อร่วมกัน |
| แหล่งจ่ายไฟที่เหมาะสม | VCC | ตรวจสอบสเปกโมดูลจริง |
| — | SET | อยู่ในโหมดทำงานปกติ ไม่ใช่ AT mode |

ไม่จำเป็นต้องต่อ HC-12 TXD กลับเข้า COMM Mega สำหรับ sketch ส่งข้อมูลนี้

**GS Mega ↔ HC-12 ฝั่ง Ground Station**

| GS Mega | HC-12 | หมายเหตุ |
|---|---|---|
| D19 — RX1 | TXD | รับข้อมูลจากวิทยุ |
| GND | GND | ต้องต่อร่วมกัน |
| แหล่งจ่ายไฟที่เหมาะสม | VCC | ตรวจสอบสเปกโมดูลจริง |
| USB | Laptop ฝั่ง GS | ส่ง record ที่ถอดแล้วเข้า Python |
| — | SET | อยู่ในโหมดทำงานปกติ |

ไม่ต้องต่อ GS Mega D18/TX1 ไปยัง HC-12 RXD ระหว่างทดลองรับอย่างเดียว

**ข้อควรระวัง**
- ตรวจสอบแรงดัน VCC และระดับลอจิกของ HC-12 รุ่นที่ใช้งานจริง โดยเฉพาะโมดูล clone
- อย่าถือว่าขา RXD ของ HC-12 รับสัญญาณ 5V ได้โดยอัตโนมัติ
- ตรวจสอบความสามารถในการจ่ายกระแสของแหล่งจ่าย ไม่ควรเลือกขาจ่ายไฟจากแรงดันเพียงอย่างเดียว
- แนะนำ capacitor 100 nF และ 47–100 µF ใกล้ VCC/GND ของ HC-12
- หาก UNO และ COMM ใช้แหล่งจ่ายแยกกัน ให้เชื่อม GND สำหรับ UART แต่ไม่ควรต่อขา 5V ของแหล่งจ่ายต่างตัวเข้าหากันโดยไม่มีการออกแบบ
- ฝั่ง CubeSat และ Ground Station ไม่ต้องเชื่อม GND ข้ามกันเมื่อสื่อสารผ่านวิทยุ
- ใช้ความถี่ ช่องสัญญาณ กำลังส่ง และระยะเวลาส่งตามข้อกำหนดที่ใช้กับสถานที่ทดลอง
- ไม่ถอดเสาอากาศขณะโมดูลกำลังส่ง

### 7. ค่าการสื่อสารและการตั้ง HC-12

| รายการ | ค่า |
|---|---|
| Python → UNO USB serial | 115200 baud, 8N1 |
| UNO ↔ COMM | 9600 baud, 8N1 |
| COMM → HC-12 | 9600 baud, 8N1 |
| HC-12 → GS Mega | 9600 baud, 8N1 |
| GS Mega → Python | 115200 baud, 8N1 |
| HC-12 mode | FU3 ทั้งสองตัว |
| HC-12 channel | ต้องตรงกัน และเลือกให้เหมาะสมตามข้อกำหนด |
| DATA payload | สูงสุด 128 bytes ต่อ packet |
| ขนาดไฟล์สูงสุด | 4 MiB หรือ 4194304 bytes |
| ชื่อไฟล์ใน metadata | สูงสุด 48 bytes แบบ UTF-8 |
| RF gap ใน COMM | 250 ms หลังส่งแต่ละ packet เข้า UART |
| จำนวนรอบส่งเริ่มต้น | 3 รอบ |

ตั้งค่า HC-12 ทั้งสองตัวก่อนเริ่มทดลอง โดยใช้ AT mode ตามคู่มือของโมดูลจริง

**โปรแกรม Python และ firmware ในชุดนี้ไม่ได้ตั้งค่า HC-12 ผ่าน AT command ให้อัตโนมัติ**

หากใช้ sketch ชั่วคราวตั้งค่า HC-12 ต้องอัปโหลด sketch COMM/GS กลับก่อนเริ่มทดลอง และนำ SET กลับสู่โหมดทำงานปกติ

### 8. เตรียม Python

รันคำสั่งจากโฟลเดอร์หลักของ repository

ตรวจสอบ Python:

```bash
python --version
```

หากเครื่องใช้คำสั่ง `python3` ให้ใช้ `python3` แทน `python` ตามสภาพแวดล้อมของเครื่อง

แนะนำสร้าง virtual environment:

```bash
python -m venv .venv
```

เปิดใช้งานบน Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

เปิดใช้งานบน Linux/macOS:

```bash
source .venv/bin/activate
```

ติดตั้ง dependency:

```bash
python -m pip install pyserial
```

ตรวจสอบ serial ports ที่พบ:

```bash
python -m serial.tools.list_ports
```

ตัวอย่างการกำหนดพอร์ต:

| หน้าที่ | ตัวอย่าง Windows | ตัวอย่าง Linux |
|---|---|---|
| UNO สำหรับ Python ผู้ส่ง | `COM5` | `/dev/ttyACM1` |
| GS Mega สำหรับ Python ผู้รับ | `COM8` | `/dev/ttyACM0` |

ค่าดังกล่าวเป็นเพียงตัวอย่าง ต้องตรวจสอบพอร์ตจริงทุกครั้ง โดยเฉพาะเมื่อถอดเสียบ USB ใหม่

### 9. อัปโหลด Arduino Firmware

1. เปิด `firmware/PayloadUNO/PayloadUNO.ino` ใน Arduino IDE
2. เลือกบอร์ด Arduino UNO และพอร์ตของ UNO แล้วอัปโหลด
3. เปิด `firmware/COMMMega/COMMMega.ino`
4. เลือกบอร์ด Arduino Mega 2560 และพอร์ตของ COMM แล้วอัปโหลด
5. เปิด `firmware/GSMega/GSMega.ino`
6. เลือกบอร์ด Arduino Mega 2560 และพอร์ตของ GS แล้วอัปโหลด
7. ตรวจสอบว่า `LinkProtocol.h` อยู่ในโฟลเดอร์เดียวกับ sketch แต่ละตัว
8. ปิด Serial Monitor ที่ใช้พอร์ตเดียวกับ Python ก่อนเริ่มทดลอง

UNO ใช้ `SoftwareSerial` ส่วน Mega ใช้ hardware serial ตามการต่อวงจรที่ระบุ

### 10. เริ่มทดลองส่งข้อความ

**ขั้นตอนที่ 1: เปิด receiver ก่อน**

บน Laptop ฝั่ง GS:

```bash
python receive.py --port COM8 --out logs
```

รอให้แสดง:

```text
[READY] GS USB port=COM8
[READY] Start the CubeSat sender now.
```

การเปิด USB serial อาจทำให้ Arduino reset โปรแกรมจึงรอประมาณ 2.5 วินาทีก่อนเริ่มใช้งาน

**ขั้นตอนที่ 2: เปิด sender อีก terminal**

บน Laptop ฝั่ง CubeSat:

```bash
python send.py --port COM5 --text "TEMP=25.3,VOLT=4.12,MODE=NORMAL" --passes 3
```

พอร์ตที่ระบุใน `send.py` ต้องเป็นพอร์ตของ **UNO** ไม่ใช่ COMM Mega

ตัวอย่างข้อความภาษาไทย:

```bash
python send.py --port COM5 --text "อุณหภูมิ=25.3,แรงดัน=4.12,สถานะ=ปกติ" --passes 3
```

ข้อความจะถูกเข้ารหัสเป็น UTF-8 และใช้ชื่อเริ่มต้น `telemetry.txt`

**ขั้นตอนที่ 3: ตรวจผลที่ GS**

การรับสมบูรณ์ต้องมีข้อความ:

```text
[COMPLETE 0x1234ABCD] CRC32 OK=........, ... bytes
```

Transfer ID, CRC32 และขนาดจริงจะเปลี่ยนไปตามข้อมูลที่ส่ง

**อย่าใช้ข้อความจบการส่งของ sender เป็นหลักฐานว่าฝั่ง GS ได้รับครบ** ให้ตรวจ `COMPLETE` และ `CRC32 OK` ฝั่ง GS

### 11. ส่งไฟล์ข้อความและรูปภาพ

สร้างหรือเตรียมไฟล์ที่จะส่งก่อนรันคำสั่ง

ส่งไฟล์ข้อความ:

```bash
python send.py --port COM5 --file telemetry.txt --passes 3
```

ส่งภาพ JPEG:

```bash
python send.py --port COM5 --file photo.jpg --passes 3
```

ส่งภาพ PNG:

```bash
python send.py --port COM5 --file image.png --passes 3
```

หาก path มีช่องว่าง ให้ครอบด้วยเครื่องหมายคำพูด:

```bash
python send.py --port COM5 --file "test data/photo 01.jpg" --passes 3
```

กำหนดชื่อไฟล์ที่ส่งใน metadata:

```bash
python send.py --port COM5 --file photo.jpg --name camera_001.jpg --passes 3
```

Arduino ไม่ได้เปิดหรือถอดรหัสภาพ แต่ส่ง bytes ของไฟล์ตามเดิม จึงไม่ต้องใช้ image library บน Arduino

**ข้อควรทราบเกี่ยวกับชื่อไฟล์**
- ชื่อใน metadata ถูกจำกัดที่ 48 bytes แบบ UTF-8 ไม่ใช่ 48 ตัวอักษร
- ชื่อยาวอาจถูกตัด รวมถึงนามสกุลไฟล์
- GS ปรับชื่อเพื่อไม่ให้ข้อมูลที่รับมาสร้าง path นอกโฟลเดอร์ปลายทาง
- ไฟล์ปลายทางมี prefix `payload_`
- อักขระที่ไม่อยู่ในชุด ASCII ที่อนุญาตจะถูกแทนด้วย `_`
- แนะนำชื่อสั้น เช่น `photo_001.jpg` หรือ `telemetry.txt`

### 12. ตัวเลือกของ Python

**`send.py`**

| ตัวเลือก | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `--port` | ต้องระบุ | USB serial port ของ UNO |
| `--file` | ไม่กำหนด | Path ของไฟล์ที่จะส่ง |
| `--text` | ไม่กำหนด | ข้อความที่จะส่งแบบ UTF-8 |
| `--name` | ชื่อไฟล์ต้นฉบับ หรือ `telemetry.txt` | ชื่อไฟล์ใน metadata |
| `--passes` | `3` | จำนวนรอบส่งทั้งไฟล์ ต้อง ≥1 |
| `--id` | สุ่มเลขที่ไม่ใช่ 0 | Transfer ID ตั้งแต่ 1 ถึง `0xFFFFFFFF` |
| `--meta-every` | `32` | ส่ง META เพิ่มทุกจำนวน DATA packets ที่กำหนด ต้อง ≥1 |

ต้องเลือก `--file` หรือ `--text` อย่างใดอย่างหนึ่งเท่านั้น

ดูคำอธิบายจากโปรแกรม:

```bash
python send.py --help
```

**`receive.py`**

| ตัวเลือก | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `--port` | ต้องระบุ | USB serial port ของ GS Mega |
| `--out` | `logs` | โฟลเดอร์หลักสำหรับเก็บผล |
| `--idle` | `30` | เวลาว่างเป็นวินาทีก่อนแจ้งว่าการรับยังไม่ครบ ต้อง >0 |

ตัวอย่าง:

```bash
python receive.py --port COM8 --out experiment_01 --idle 60
```

`--idle` ใช้แจ้งสถานะเท่านั้น ไม่ได้หยุดโปรแกรม ไม่ได้ลบ `.part` และไม่ได้ส่งคำขอ retransmission ผ่านวิทยุ

ดูคำอธิบายจากโปรแกรม:

```bash
python receive.py --help
```

### 13. Application Packet และการตรวจข้อมูล

ทุก packet มี header ระบุชนิดข้อมูล, transfer ID, sequence, จำนวน DATA packets และ payload length ตามด้วย payload และ CRC32

จำนวนเต็มหลาย bytes ใช้ little-endian

| ชนิด | Sequence | Payload |
|---|---|---|
| `META` | `0` | ขนาดไฟล์, CRC32 ทั้งไฟล์, chunk size และชื่อไฟล์ |
| `DATA` | `0` ถึง `total - 1` | ข้อมูลไฟล์สูงสุด 128 bytes |
| `END` | `total` | ไม่มี payload |

มีการตรวจ CRC32 สองระดับ:
- **Packet CRC32:** ตรวจ application header และ payload โดย Arduino
- **File CRC32:** ตรวจไฟล์ที่ประกอบเสร็จแล้วโดย Python ฝั่ง GS

CRC32 ใช้ตรวจความเสียหายของข้อมูล ไม่ใช่การเข้ารหัสหรือการยืนยันตัวตน

**การส่งซ้ำ**
- แต่ละรอบส่ง META เริ่มต้น 3 ครั้ง
- ระหว่างส่ง DATA มี META แทรกตาม `--meta-every`
- จบรอบส่ง END 3 ครั้ง
- ทุกรอบของไฟล์เดียวกันใช้ transfer ID เดิม
- GS ไม่เพิ่มจำนวน unique chunks เมื่อรับ DATA ซ้ำ
- GS สามารถวาง DATA ตาม sequence ได้ แม้รับไม่เรียงลำดับ
- END ไม่ใช่หลักฐานว่ารับครบ
- หากข้อมูลครบและ File CRC32 ผ่าน จะปิดงานได้แม้ END สูญหาย
- หาก DATA มาถึงก่อน META ของ transfer นั้น จะถูกแจ้งเป็น `ORPHAN` และไม่ได้เก็บไว้รอประกอบ

### 14. ความหมายของ ACK

ACK มีเฉพาะในเส้นทางภายใน:

```text
COMM → UNO → Python ผู้ส่ง
```

ACK นี้หมายความว่า:
- COMM รับและตรวจ application packet ผ่าน
- COMM ส่ง bytes ของ packet ไปยัง HC-12 ผ่าน UART แล้ว
- COMM ผ่านช่วงเว้นระยะที่กำหนดก่อนตอบกลับ

ACK นี้ **ไม่ได้หมายความว่า**:
- HC-12 ส่งผ่าน RF สำเร็จทุก byte
- Ground Station รับ packet ได้
- Ground Station ประกอบไฟล์ครบแล้ว

หาก local ACK ไม่มา Python จะลองส่ง packet เดิมใหม่ได้สูงสุด 3 attempts ก่อนยุติด้วยข้อผิดพลาด

### 15. Log และไฟล์ที่รับได้

โครงสร้างผลลัพธ์:

```text
logs/
└── YYYY-MM-DD/
    ├── RX_000001/
    │   ├── RX_000001_1234ABCD.txt
    │   └── payload_telemetry.txt
    └── RX_000002/
        ├── RX_000002_5678EF90.txt
        └── payload_photo.jpg.part
```

**การนับครั้งรับ**
- เริ่มนับเมื่อรับ META ที่ถูกต้องของ transfer ใหม่
- ครั้งแรกของวันใช้ `RX_000001`
- ครั้งถัดไปใช้เลขที่ยังไม่ถูกใช้งานในวันนั้น
- Packet ซ้ำและ META ซ้ำของ transfer ปัจจุบันไม่เพิ่มเลขครั้ง
- การรับที่ไม่ครบก็นับเป็นหนึ่งครั้ง เพราะเริ่ม session ไปแล้ว
- หากปิด receiver แล้วเปิดใหม่ แม้รับ ID เดิม ก็เริ่ม session ใหม่

วันเวลาใช้เวลาท้องถิ่นและ time zone ของ Laptop ฝั่ง GS โดยโฟลเดอร์วันที่ยึดวันที่เริ่ม session

หาก transfer ข้ามเที่ยงคืน log ยังคงอยู่ในโฟลเดอร์วันที่เริ่มรับ แต่ timestamp ของแต่ละ record เป็นเวลาที่บันทึกจริง

**สิ่งที่อยู่ใน `.txt` log**
- เวลาเริ่มรับ
- เลขครั้งรับประจำวัน
- Transfer ID
- ชื่อและขนาดไฟล์
- CRC32 ของไฟล์ที่คาดหวัง
- META, DATA และ END ที่รับและผูกกับ session ได้
- DATA payload แบบ hex
- สถานะข้อมูลขาดหรือข้อผิดพลาด
- ผลตรวจ CRC32 ทั้งไฟล์
- สถานะเมื่อปิด session
- ข้อความ UTF-8 ที่ประกอบสมบูรณ์ สำหรับไฟล์ขนาดไม่เกิน 64 KiB ที่ถอด UTF-8 ได้

**ความหมายของ `.part`**
- เป็นไฟล์ที่ยังไม่ยืนยันความสมบูรณ์
- จะเปลี่ยนเป็นชื่อไฟล์ปกติเมื่อรับ DATA ครบและ File CRC32 ผ่านเท่านั้น
- ไม่ควรนำไปใช้เป็นไฟล์สมบูรณ์ แม้โปรแกรมเปิดไฟล์นั้นได้
- โปรแกรมเตรียมขนาด `.part` เท่าขนาดไฟล์ที่คาดหวังตั้งแต่เริ่ม ดังนั้นขนาดไฟล์บนดิสก์ไม่ใช่ตัวบอกความคืบหน้า

### 16. การอ่านสถานะบน Terminal

| สถานะ | ความหมาย |
|---|---|
| `[READY]` | โปรแกรมพร้อมทำงาน |
| `[START]` | เริ่มรับ transfer ใหม่ |
| `[TX LOCAL]` | ผู้ส่งได้รับ local ACK สำหรับ DATA ที่ส่ง |
| `[RX ...]` | ความคืบหน้าจาก unique chunks ที่ GS รับได้ |
| `[GS] accepted=...` | จำนวน application packets ที่ GS Arduino ตรวจผ่าน |
| `rejected_packet=...` | จำนวนเฟรมที่ถูกปฏิเสธจากการตรวจ command/header/application |
| `rejected_kiss=...` | จำนวนความผิดปกติของ KISS ที่ parser ตรวจพบ |
| `[ORPHAN]` | DATA มาถึงโดยยังไม่มี META ของ transfer นั้น |
| `[INCOMPLETE ...]` | ข้อมูลยังไม่ครบ พร้อมตัวอย่าง sequence ที่ขาด |
| `[COMPLETE ...]` | ข้อมูลครบและ File CRC32 ผ่าน |
| `[FAILED ...]` | พบความขัดแย้งของข้อมูลหรือ File CRC32 ไม่ผ่าน |
| `[RETRY LOCAL]` | ผู้ส่งกำลังลอง packet เดิมใหม่ เพราะไม่ได้ local ACK |

ตัวอย่างเมื่อข้อมูลขาด:

```text
[INCOMPLETE 0x1234ABCD] END_OF_PASS received=6/8 missing=2 first_missing=[2, 5]
```

`first_missing` แสดง sequence ที่ขาดสูงสุด 20 รายการ ไม่ใช่รายการทั้งหมดหากขาดมากกว่านั้น

จำนวน rejected ไม่ใช่จำนวน packet ที่สูญหายทั้งหมด เพราะเฟรมที่หายไปทั้งเฟรมอาจไม่มีข้อมูลให้ parser ตรวจพบ ต้องพิจารณา sequence ร่วมด้วย

### 17. ส่งซ้ำเพื่อเติมข้อมูลที่ขาด

หาก GS ยังเปิดโปรแกรมอยู่และยังรับ transfer เดิม สามารถส่งไฟล์เดิมซ้ำด้วย transfer ID เดิมได้

สมมติ ID เดิมคือ `0x1234ABCD`:

```bash
python send.py --port COM5 --file photo.jpg --passes 1 --id 0x1234ABCD
```

หากรอบแรกใช้ `--name` ต้องใช้ค่าเดิมด้วย:

```bash
python send.py --port COM5 --file photo.jpg --name camera_001.jpg --passes 1 --id 0x1234ABCD
```

สิ่งที่ต้องตรงกับการส่งเดิม:
- Transfer ID
- เนื้อหาไฟล์ทุก byte
- ชื่อไฟล์ใน metadata
- ขนาดไฟล์และรูปแบบการแบ่ง chunk

หากเปลี่ยนข้อมูลหรือชื่อไฟล์ ให้ใช้ transfer ID ใหม่

**ข้อจำกัดของ receiver**
- รองรับ transfer ปัจจุบันครั้งละหนึ่งงาน
- เมื่อพบ META ของ ID ใหม่ จะปิด session เดิม
- หาก session เดิมยังไม่ครบ จะเก็บ `.part` ไว้
- ยังไม่รองรับ resume จาก `.part` หลังปิดโปรแกรม ไฟดับ หรือเปลี่ยนไปอีก transfer
- หากเกิดสถานะ `FAILED` ให้ตรวจสอบสาเหตุและเริ่มรับใหม่ด้วย transfer ID ใหม่

### 18. การทดสอบความถูกต้อง

**ทดสอบที่ 1: ข้อความสั้น**

```bash
python send.py --port COM5 --text "HELLO CUBESAT" --passes 1
```

เกณฑ์ผ่าน:
- GS แสดง `COMPLETE`
- CRC32 ผ่าน
- ไฟล์ปลายทางมีข้อความตรงกับต้นฉบับ

**ทดสอบที่ 2: ข้อมูล binary ครบทุกค่า byte**

สร้างไฟล์ทดสอบ:

```bash
python -c "from pathlib import Path; Path('all_bytes.bin').write_bytes(bytes(range(256))*4)"
```

ไฟล์นี้มีขนาด 1024 bytes และมีค่า `0x00`, `0xC0` และ `0xDB` เพื่อทดสอบข้อมูล binary และ KISS escaping

ส่งไฟล์:

```bash
python send.py --port COM5 --file all_bytes.bin --passes 1
```

หลัง GS แสดง `COMPLETE` ให้เปรียบเทียบไฟล์แบบ byte-for-byte

ตัวอย่าง Python โดยเปลี่ยน path ให้ตรงกับผลการรับจริง:

```python
from pathlib import Path

source = Path("all_bytes.bin").read_bytes()
received = Path(
    "logs/YYYY-MM-DD/RX_000001/payload_all_bytes.bin"
).read_bytes()

assert source == received
print("PASS: BYTE-FOR-BYTE MATCH")
```

**ทดสอบที่ 3: ขนาดบริเวณขอบ chunk**

| ขนาดไฟล์ | จำนวน DATA packets ที่ควรได้ |
|---:|---:|
| 0 bytes | 0 |
| 1 byte | 1 |
| 127 bytes | 1 |
| 128 bytes | 1 |
| 129 bytes | 2 |
| 1024 bytes | 8 |

ไฟล์ว่างต้องประกอบสำเร็จได้จาก META โดยไม่ต้องมี DATA

**ทดสอบที่ 4: การส่งซ้ำ**

```bash
python send.py --port COM5 --file all_bytes.bin --passes 3
```

เกณฑ์ผ่าน:
- จำนวน unique chunks ไม่เกินจำนวนที่คาดหวัง
- ไม่สร้าง session ใหม่จาก META ซ้ำของงานเดิม
- ไฟล์ปลายทางไม่โตขึ้นจาก packet ซ้ำ
- ไฟล์ที่ประกอบแล้วตรงกับต้นฉบับ

**ทดสอบที่ 5: ข้อมูลสูญหาย**

จำลองการละเว้น DATA บาง sequence ในซอฟต์แวร์ทดสอบ หรือสร้างช่วงขาดการรับอย่างควบคุมได้

โปรแกรมที่ให้มายังไม่มีตัวเลือก fault injection โดยตรง

เกณฑ์ผ่าน:
- GS แจ้ง `INCOMPLETE`
- ไฟล์ยังเป็น `.part`
- ส่งซ้ำด้วย ID เดิมขณะ receiver ยังอยู่กับ transfer นั้นแล้วเติมส่วนที่ขาดได้
- เปลี่ยนเป็นไฟล์สมบูรณ์เมื่อข้อมูลครบและ CRC32 ผ่านเท่านั้น

ห้ามใช้การถอดเสาอากาศขณะส่งเป็นวิธีจำลอง packet loss

**ทดสอบที่ 6: รูปภาพ**

เริ่มจากภาพขนาดเล็ก แล้วตรวจสอบ:
- GS แสดง `COMPLETE`
- File CRC32 ผ่าน
- ไฟล์ตรงกับต้นฉบับแบบ byte-for-byte
- โปรแกรมดูภาพเปิดไฟล์ได้ตามปกติ

การเปิดภาพได้อย่างเดียวไม่ใช่หลักฐานว่า bytes ตรงกับต้นฉบับทุกตำแหน่ง

### 19. การเก็บผลการทดลอง

แนะนำบันทึกข้อมูลต่อไปนี้สำหรับแต่ละเงื่อนไขทดลอง:

| รายการ | สิ่งที่ควรบันทึก |
|---|---|
| ไฟล์ต้นฉบับ | ชื่อ ขนาด และ CRC32 |
| Transfer ID | ID ที่ใช้ในการทดลอง |
| การส่งซ้ำ | จำนวน `--passes` |
| HC-12 | Mode, channel และกำลังส่งที่ตั้งไว้ |
| ระยะและสภาพแวดล้อม | ระยะห่าง สิ่งกีดขวาง และตำแหน่งเสาอากาศ |
| ผลการรับ | COMPLETE, INCOMPLETE หรือ FAILED |
| ข้อมูลขาด | จำนวน unique chunks ที่ยังขาด |
| ข้อมูลซ้ำ | จำนวน duplicates ที่ receiver นับได้ |
| ความผิดปกติ | rejected packet และ rejected KISS |
| เวลา | เวลาเริ่ม เวลาเสร็จ และวิธีจับเวลาที่ใช้ |

ไม่ควรใช้จำนวน rejected เพียงอย่างเดียวคำนวณ packet loss เพราะไม่ได้ครอบคลุมเฟรมที่สูญหายไปทั้งหมด

หากต้องการเปรียบเทียบผลระหว่างการทดลอง ให้กำหนดวิธีจับเวลาและจุดเริ่ม/จบเหมือนกันทุกครั้ง

### 20. Troubleshooting

| อาการ | สาเหตุที่ควรตรวจสอบ | แนวทางแก้ไข |
|---|---|---|
| Python เปิดพอร์ตไม่ได้ | พอร์ตไม่ถูก ใช้งานอยู่ หรือไม่มีสิทธิ์ | ตรวจพอร์ต ปิด Serial Monitor และตรวจสิทธิ์ระบบ |
| ไม่พบ `serial` module | ยังไม่ได้ติดตั้งใน Python environment ที่ใช้งาน | รัน `python -m pip install pyserial` |
| UNO แจ้ง `ERR LOCAL_TIMEOUT` | ไม่ได้รับ ACK จาก COMM | ตรวจ TX/RX, GND, ไฟเลี้ยง, baud rate และ sketch |
| `No local ACK from COMM` | Local ACK ล้มเหลวจนครบ attempts | ตรวจเส้นทาง UNO ↔ COMM ไม่ใช่เฉพาะ RF |
| UNO แจ้ง `ERR BAD_APP` | Application packet ไม่ผ่านการตรวจ | ตรวจว่า Python และ `LinkProtocol.h` เป็นชุดเดียวกัน |
| Sender ส่งได้แต่ GS ไม่มีข้อมูล | HC-12 ตั้งค่าไม่ตรง ต่อสายผิด หรือยังอยู่ AT mode | ตรวจ mode/channel/baud, SET และสาย UART |
| มี `ORPHAN` | META สูญหายหรือเริ่ม receiver ช้า | เปิด GS ก่อน sender และส่งซ้ำด้วย ID เดิม |
| มี `INCOMPLETE` | DATA บาง sequence สูญหาย | ตรวจภาคไฟและ RF แล้วส่งซ้ำด้วย ID เดิม |
| File CRC32 ไม่ผ่าน | ข้อมูลที่ประกอบไม่ตรงกับ metadata | เก็บ log ตรวจสาเหตุ แล้วเริ่มใหม่ด้วย ID ใหม่ |
| Same transfer ID has different metadata | ใช้ ID เดิมกับไฟล์หรือชื่อใหม่ | ใช้ ID ใหม่เมื่อข้อมูลหรือชื่อเปลี่ยน |
| ภาพเปิดไม่ได้ | ไฟล์ยังไม่ครบ นามสกุลถูกตัด หรือไฟล์ต้นฉบับมีปัญหา | ตรวจ `COMPLETE`, CRC32, ชื่อไฟล์ และต้นฉบับ |
| ส่งภาพช้า | UART ช้า มี overhead และส่งซ้ำหลายรอบ | เริ่มด้วยภาพเล็กและวัดผลก่อนปรับค่าระบบ |
| `.part` มีขนาดเต็มแต่ยังไม่ COMPLETE | โปรแกรมเตรียมขนาดไฟล์ไว้ล่วงหน้า | ดู unique chunks และ CRC32 ไม่ใช่ขนาดไฟล์บนดิสก์ |

บน Linux ชื่อ serial device และกลุ่มสิทธิ์อาจแตกต่างกัน ให้ตรวจตามระบบที่ใช้งาน ไม่ควรรันด้วยสิทธิ์ผู้ดูแลโดยไม่จำเป็น

### 21. ข้อจำกัดของระบบ

- ไม่มี ACK/NACK ผ่านวิทยุ จึงไม่รับประกันการส่งถึงปลายทาง
- การส่งหลายรอบช่วยให้มีโอกาสรับครบมากขึ้น แต่ยังอาจมีข้อมูลขาด
- ไม่รองรับการขอส่งซ้ำเฉพาะ sequence ที่หายผ่าน RF
- Receiver จัดการ transfer ปัจจุบันครั้งละหนึ่งงาน
- ยังไม่มี persistent checkpoint สำหรับ resume หลังปิดโปรแกรมหรือไฟดับ
- ยังไม่มีระบบ reconnect serial อัตโนมัติ
- CRC32 ไม่ใช่การป้องกันการปลอมแปลงหรือการยืนยันผู้ส่ง
- ยังไม่มี encryption หรือ message authentication
- AX.25 parser รองรับเฉพาะ header ของชุดทดลองนี้
- UNO ใช้ SoftwareSerial จึงต้องส่งแบบทีละ packet และรอ local ACK
- จำกัดไฟล์ไม่เกิน 4 MiB
- รูปภาพขนาดใหญ่ใช้เวลานาน เพราะมี UART overhead, protocol overhead, ช่วงเว้น packet และการส่งซ้ำ
- ยังไม่ได้รับการยืนยันด้วยการทดสอบฮาร์ดแวร์จริงหรือการทดสอบสำหรับภารกิจอวกาศ

### 22. แนวทางพัฒนาต่อ

- เพิ่ม RF ACK/NACK หากเปลี่ยนข้อกำหนดให้ Ground Station ส่งกลับได้
- ส่งซ้ำเฉพาะ sequence ที่ขาด
- เพิ่ม checkpoint ของ metadata และ received bitmap
- เพิ่มระบบ reconnect เมื่อ USB serial หลุด
- เปลี่ยน UNO เป็นบอร์ดที่มี hardware UART หลายชุด
- เพิ่มการบีบอัดหรือเลือกความละเอียดภาพให้เหมาะกับ bandwidth
- เพิ่ม timestamp จาก Payload/OBC ภายใน telemetry
- เพิ่ม message authentication หากต้องตรวจสอบผู้ส่ง
- เพิ่ม automated tests สำหรับ CRC32, KISS escaping และ packet parser
- เพิ่มการวัด throughput และ packet loss แบบมีนิยามชัดเจน

### 23. Checklist ก่อนเริ่มทดลอง

- [ ] อัปโหลด sketch ถูกบอร์ดทั้งสามตัว
- [ ] `LinkProtocol.h` ทั้งสามชุดตรงกัน
- [ ] UNO TX/RX ต่อไขว้กับ COMM RX/TX ถูกต้อง
- [ ] UNO และ COMM มี GND ร่วมกัน
- [ ] HC-12 ทั้งสองตัวมีไฟเลี้ยงและระดับลอจิกที่เหมาะสม
- [ ] HC-12 ใช้ baud rate, mode และ channel ตรงกัน
- [ ] HC-12 ออกจาก AT mode แล้ว
- [ ] ต่อเสาอากาศเรียบร้อย
- [ ] ใช้การตั้งค่าวิทยุที่เหมาะสมตามข้อกำหนดของสถานที่ทดลอง
- [ ] ปิด Serial Monitor ที่ใช้พอร์ตเดียวกับ Python
- [ ] เลือกพอร์ต UNO ให้ sender และพอร์ต GS Mega ให้ receiver
- [ ] เปิด receiver และรอ READY ก่อนเริ่ม sender
- [ ] ทดสอบข้อความและ binary ขนาดเล็กก่อนส่งภาพ
- [ ] ยืนยันผลด้วย COMPLETE และ CRC32 OK ฝั่ง GS