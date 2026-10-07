/*
 * lb2_phy.c - LB2 symbol encode / decode
 *
 * Decode is nearest-symbol with a distance limit: with min distance 4 a single
 * bit error is corrected and a double error is flagged. A symbol table with a
 * pair at distance < 4 silently breaks this (a 1-bit error can land exactly
 * between two opcodes or on the wrong one), see FW-877.
 */
#include "lb2_phy.h"
#include "lb2_cmd_table.h"

#define LB2_BITS       12u
#define LB2_WEIGHT     6u
#define LB2_MAX_RUN    3u
#define LB2_EDGE_RUN   2u
#define LB2_IDLE_A     0x555u
#define LB2_IDLE_B     0xAAAu

static uint8_t popcount12(uint16_t w)
{
    uint8_t n = 0;
    w &= 0x0FFFu;
    while (w) {
        w &= (uint16_t)(w - 1u);
        n++;
    }
    return n;
}

int lb2_symbol_ok(uint16_t w)
{
    uint8_t run = 1, first = 0, i;
    uint8_t prev = (w >> 11) & 1u;

    if (popcount12(w) != LB2_WEIGHT)
        return 0;
    for (i = 1; i < LB2_BITS; i++) {
        uint8_t b = (w >> (11u - i)) & 1u;
        if (b == prev) {
            if (++run > LB2_MAX_RUN)
                return 0;
        } else {
            if (!first) {
                first = run;
                if (first > LB2_EDGE_RUN)
                    return 0;
            }
            run = 1;
        }
        prev = b;
    }
    return run <= LB2_EDGE_RUN;
}

void lb2_phy_init(void)
{
    /* nothing yet; rev D will build a 4k lookup table here */
}

uint16_t lb2_encode_opcode(uint8_t opcode)
{
    if (opcode >= LB2_NUM_OPCODES)
        return LB2_SYM_UNASSIGNED;
    return lb2_cmd_symbol[opcode];
}

lb2_dec_t lb2_decode_symbol(uint16_t word, uint8_t *opcode_out)
{
    uint8_t best_d = 0xFF, best_op = 0xFF, ties = 0, op;

    word &= 0x0FFFu;
    if (word == LB2_IDLE_A || word == LB2_IDLE_B)
        return LB2_DEC_IDLE;

    for (op = 0; op < LB2_NUM_OPCODES; op++) {
        uint16_t s = lb2_cmd_symbol[op];
        uint8_t d;
        if (s == LB2_SYM_UNASSIGNED)
            continue;
        d = popcount12((uint16_t)(s ^ word));
        if (d < best_d) {
            best_d = d;
            best_op = op;
            ties = 0;
        } else if (d == best_d) {
            ties++;
        }
    }
    if (best_d == 0) {
        *opcode_out = best_op;
        return LB2_DEC_OK;
    }
    if (best_d == 1 && !ties) {
        *opcode_out = best_op;
        return LB2_DEC_CORRECTED;
    }
    if (lb2_symbol_ok(word))
        return LB2_DEC_UNKNOWN;
    return LB2_DEC_ERROR;
}
