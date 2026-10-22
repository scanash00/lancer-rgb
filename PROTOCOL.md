# Protocol evidence

Captured from working XPG PRIME 1.7.0.0 with ENE HAL 1.0.4.16 on the supported
hardware. Successful red, green and blue static sequences are included as test
fixtures. Captures are userspace API observations, not physical logic-analyzer data.

Each controller (`0x71`, `0x73`, seven-bit addresses) receives:

| Register | Data |
| --- | --- |
| 0x8160 | R, B, G repeated eight times |
| 0x8020 | 00 01 00 00 |
| 0x8029 | 09 |
| 0x802F | 01 |

Register selection is SMBus write-word-data command 0, with byte-swapped register
value to transmit the high register byte first. Each data byte is a separate
write-byte-data command 1. The sequence has 34 transactions per controller.
Brightness scales channels using positive integer rounding matching JavaScript
Math.round. Never substitute SMBus block transactions without new evidence.

Readback selects individual registers then uses read-byte-data command 0x81,
following OpenRGB's ENE interface. Reads are limited to mode bytes 0x8020/0x8021
and 24 static color bytes 0x8160..0x8177. A pointer-selection write is required;
no RGB data, SPD, persistence or remapping command is sent by readback.
Mode/direct values 1/0 identify the captured static configuration. Other modes
are reported as unsupported. Physical chip identity and cold-boot initialization
have not been established.

References:
- https://github.com/CalcProgrammer1/OpenRGB/blob/master/Controllers/ENESMBusController/ENESMBusInterface/ENESMBusInterface_i2c_smbus.cpp
- https://docs.kernel.org/i2c/dev-interface.html
- https://docs.kernel.org/i2c/smbus-protocol.html
