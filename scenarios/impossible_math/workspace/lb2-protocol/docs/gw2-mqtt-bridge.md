# GW-2 MQTT bridge - design notes

status: draft, KY

## Goal

Expose LB2 heads behind a GW-2 as MQTT topics so customers stop writing
Modbus pollers against the gateway. One topic tree per gateway:

    ebeling/<gw-serial>/<bus-addr>/value/<ch>
    ebeling/<gw-serial>/<bus-addr>/status
    ebeling/<gw-serial>/<bus-addr>/event        (rev C heads only)
    ebeling/<gw-serial>/<bus-addr>/cmd          (write, JSON)

## Polling

Gateway polls each head with READ_VALUE / CH_READ_VALUE at the configured
rate (default 10 Hz, max 100 Hz with <= 8 heads). Rev C heads with events
enabled are polled with EVT_POLL at 2 Hz instead of reading every value.

Bus budget at 1 Mbit/s: one READ_VALUE round trip is ~12 symbols out +
~10 back + turnaround, call it 0.3 ms. 31 heads x 4 channels x 100 Hz does
not fit; we cap at 3000 reads/s and spread.

## Payload

    {"v": 12.431, "u": "bar", "t": 1712312332123, "q": 0}

q = quality flags from GET_STATUS (bit 0 overrange, bit 1 sensor fault, bit 2
cal expired).

## Commands over MQTT

Allowlist only: SET_RANGE, SET_FILTER, ZERO_OFFSET, SET_UNITS, CH_*, EVT_*.
No FWU_* or FACTORY_RESET over MQTT, ever (security review 2024).

## Open points

- TLS on the broker side: customer-provided certs, how to rotate?
- retain flag for status topic - yes?
- what happens when a head is replaced and gets the same address (serial changes)
- rate limit per topic for cmd
