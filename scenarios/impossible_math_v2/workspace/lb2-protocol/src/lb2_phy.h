#ifndef LB2_PHY_H
#define LB2_PHY_H

#include <stdint.h>
#include <stddef.h>

/* symbol decode result */
typedef enum {
    LB2_DEC_OK = 0,
    LB2_DEC_IDLE,
    LB2_DEC_UNKNOWN,     /* valid PHY word but no opcode mapped */
    LB2_DEC_CORRECTED,   /* single bit error corrected (d=4 table) */
    LB2_DEC_ERROR        /* >= 2 bit errors or PHY rule violation */
} lb2_dec_t;

void      lb2_phy_init(void);
uint16_t  lb2_encode_opcode(uint8_t opcode);
lb2_dec_t lb2_decode_symbol(uint16_t word, uint8_t *opcode_out);
int       lb2_symbol_ok(uint16_t word);

#endif
