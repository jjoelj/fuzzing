#pragma once

#include <cstddef>
#include <cstdint>

// Mutation operators (indices into weights[])
// 0=ADD  1=MODIFY  2=DELETE  3=SWAP  4=SPLICE
static constexpr int NUM_OPS = 5;

typedef struct custom_mutator {
    unsigned int   seed;
    unsigned char *buf;
    size_t         buf_size;

    // BO controller writes these via theta file; mutator reloads every 256 calls
    double         weights[NUM_OPS];
    unsigned int   energy;        // returned by afl_custom_fuzz_count

    uint64_t       call_count;
    char           theta_path[512];
} custom_mutator_t;

extern "C" custom_mutator_t *afl_custom_init(void *afl, unsigned int seed);
extern "C" uint32_t          afl_custom_fuzz_count(custom_mutator_t *data,
                                                    const uint8_t *buf,
                                                    size_t buf_size);
extern "C" size_t            afl_custom_fuzz(custom_mutator_t *data,
                                              uint8_t *buf, size_t buf_size,
                                              uint8_t **out_buf,
                                              uint8_t *add_buf, size_t add_buf_size,
                                              size_t max_size);
extern "C" void              afl_custom_deinit(custom_mutator_t *data);
