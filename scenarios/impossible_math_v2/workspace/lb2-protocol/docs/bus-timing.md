# LB2 bus timing

Measured on the TX-40 rev B dev board + 120 m Belden 3105A, 1 Mbit/s.

| item | min | typ | max | note |
|---|---|---|---|---|
| bit time | 997 ns | 1000 ns | 1003 ns | +-2500 ppm tolerated by the receiver |
| turnaround (master -> head) | 12 us | 14 us | - | head needs 12 us to switch the driver |
| head response start | - | 35 us | 80 us | after last CRC symbol |
| inter-frame gap | 2 symbols | - | - | IDLE fill |
| resync | - | - | 4 equal bits | receiver PLL loses lock after ~5 equal bits on long cables (FW-902) |

The 4-bit resync limit is the reason for `max_edge_run: 2` in the spec: two
symbols back to back can join their edge runs (2 + 2 = 4). Inside a symbol the
limit is 3.

## Long cable runs

Above 80 m drop to 500 kbit/s. At Wendt (180 m, shared tray with VFD cables)
we needed 250k, see the field report in the HW wiki.

## Open

- rev D: 2 Mbit/s trials, needs new transformer (TX-44 only)
- measure turnaround with the new LDO on TX-44 rev 1.2 boards
