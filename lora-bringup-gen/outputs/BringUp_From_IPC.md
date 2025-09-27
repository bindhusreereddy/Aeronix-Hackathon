# Factory Bring-Up Plan for Car Radio - Timestamp: 2023-10-01

## 1. Visual Inspection
- Inspect the board for any visible damage or missing components.
- Ensure all connectors are properly seated.
- Check for solder bridges or cold solder joints.
- Verify that all components are oriented correctly (polarity for capacitors, diodes, etc.).
- Confirm that no components are missing according to the schematic.

## 2. Shorts Check
- Use a multimeter to check for shorts between power and ground on all power rails.
- Inspect critical signal lines for shorts.
- Verify that no unintended connections exist between adjacent pins or traces.

## 3. Safe Power Application
- Set the power supply to 5.0 V with a current limit of 200 mA.
- Connect the power supply to the board.
- Gradually increase the voltage while monitoring the current draw.
- Ensure that the current does not exceed the set limit.

## 4. Rail Measurements
- Measure the following power rails and document the results:

| Net          | Expected | Tolerance | Probe Points                                                                 | Measured | P/F |
|--------------|----------|-----------|------------------------------------------------------------------------------|----------|-----|
| 327+5V      | 5.00 V   | ±0.10 V   | C47-1, C48-1, C49-1, C72-1, C74-1, R17-2, R23-2, U12-4, U12-6, U6-14, U6-15, U6-16, U7-10, U7-2, U7-9, U8-5 |          |     |
| 327+3V3     | 3.30 V   | ±0.10 V   | C1-1, C2-1, C3-1, C4-1, C5-1, C50-2, C51-2, C52-2, C53-1, C54-1, C58-2, C59-2, C6-2, C68-1, C69-1, C7-2, C70-2, C71-1, C8-2, L10-2, R1-2, R19-2, R3-2, R33-1, R5-2, R6-2, R7-2, R9-2, U1-1, U1-13, U1-19, U1-32, U1-48, U1-64, U10-5, U10-8, U11-7, U11-8, U13-15, U13-2, U5-3, U5-8 |          |     |
| 317+3V3     | 3.30 V   | ±0.10 V   | P1-1, P2-2, P2-4                                                           |          |     |
| 327+3V3_RF  | 3.30 V   | ±0.10 V   | C12-1, C25-1, C26-1, C27-1, C28-1, C34-1, C73-2, U12-1, U12-2, U2-14, U2-24, U2-3, U3-6, U4-6 |          |     |

## 5. Bus Checks
- Verify I2C bus functionality (SCL and SDA).
- Check SPI bus signals (MOSI, MISO, SCK).
- Test UART communication (TX and RX).
- Ensure that all bus connections are intact and functioning.

## 6. Optional PPS/RF Checks
- Check the status of the RF ANT nets (327ANT_OFF_N, 327ANT_SHORT_N).
- Verify that the RF components are functioning as expected.

## 7. Connections Appendix
- **317+3V3**: P1-1, P2-2, P2-4
- **317GND**: J4-10, J4-11, P1-10, P1-12, P1-14, P1-16, P1-18, P1-20, P1-4, P1-6, P1-8, P2-1, P2-11, P2-13, P2-15, P2-17, P2-19, P2-21, P2-23, P2-25, P2-27, P2-29, P2-3, P2-31, P2-33, P2-35, P2-37, P2-39, P2-41, P2-5, P2-7, P2-9, SW1-1
- **327+5V**: C47-1, C48-1, C49-1, C72-1, C74-1, R17-2, R23-2, U12-4, U12-6, U6-14, U6-15, U6-16, U7-10, U7-2, U7-9, U8-5
- **327+3V3**: C1-1, C2-1, C3-1, C4-1, C5-1, C50-2, C51-2, C52-2, C53-1, C54-1, C58-2, C59-2, C6-2, C68-1, C69-1, C7-2, C70-2, C71-1, C8-2, L10-2, R1-2, R19-2, R3-2, R33-1, R5-2, R6-2, R7-2, R9-2, U1-1, U1-13, U1-19, U1-32, U1-48, U1-64, U10-5, U10-8, U11-7, U11-8, U13-15, U13-2, U5-3, U5-8
- **327+3V3_RF**: C12-1, C25-1, C26-1, C27-1, C28-1, C34-1, C73-2, U12-1, U12-2, U2-14, U2-24, U2-3, U3-6, U4-6

## Operator Checklist
- [ ] Complete visual inspection.
- [ ] Verify shorts between power and ground.
- [ ] Apply safe power with current limit.
- [ ] Measure all power rails.
- [ ] Check bus functionality (I2C/SPI/UART).
- [ ] Perform optional PPS/RF checks.
- [ ] Document all measurements and observations.
- [ ] Ensure all connections are secure and correct.