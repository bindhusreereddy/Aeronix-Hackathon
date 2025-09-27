# LoRa Car Radio Bring-Up Plan (Auto-Generated)
Generated: 2025-09-27 10:03

## Tools
- Bench PSU (set **5.0 V**, current limit **200 mA**)
- DMM (multimeter), Oscilloscope
- J-Link debugger, USB-to-TTL cable
- PC with serial terminal (**115200 N81**)

## 1) Visual Inspection (NO POWER)
Look for solder bridges, missing parts, wrong orientations. Record Pass/Fail.

## 2) Continuity Checks (NO POWER)
- Verify no shorts GND↔ +5V / +3V3 / +3V3_RF.
- Verify +5V is NOT tied to +3V3 or +3V3_RF; and +3V3 is NOT tied to +3V3_RF.

## 3) Safe Power-On
- Set PSU to **5.0 V**, current limit **200 mA**.
- If supply hits current limit (CC), power off and inspect.

## 4) Rail Measurements (DMM)
| Net      | Expected | Tol  | Probe points         | Measured | P/F |
|----------|---------:|-----:|----------------------|---------:|:---:|
| +5V | 5.00 V | ±0.10 V | J3-1, U6-14..16 |  |  |
| +3V3 | 3.30 V | ±0.10 V | P2-2 |  |  |
| +3V3_RF | 3.30 V | ±0.10 V | U12-1 |  |  |

## 5) Clocks (Oscilloscope)
- **Y1** ≈ 16.00 MHz
- **Y2** ≈ 32.00 MHz

*(Tip: scope ~1 V/div, ~5 µs/div; short ground lead for clean signal.)*

## 6) Programming
- Connect **J-Link** to SWD header; connect **USB-TTL** to serial header:
  - GND → P2-1
  - PC-RX → P2-8 (PC-RX)
  - PC-TX → P2-10 (PC-TX)
- Run programming script/procedure. Confirm success.

## 7) Functional Tests (Serial @ 115200)
- Open terminal, press reset, expect welcome screen.
- `bit.lora` → expect **PASS**
- `bit.gps` → expect **PASS**
- `bit.imu` → expect **PASS**
- `bit.i2c` → expect **PASS**

## 8) Datasheet
Record measured values and Pass/Fail for all steps. No blanks.
