#include <cstddef>

typedef struct custom_mutator {
unsigned seed;
unsigned char *buf;
size_t buf_size;
} custom_mutator_t;

extern "C" custom_mutator_t *afl_custom_init(void *afl, unsigned int seed);
extern "C" size_t afl_custom_fuzz(custom_mutator_t *data, unsigned char *buf, size_t buf_size, unsigned char **out_buf, unsigned char *add_buf, size_t add_buf_size, size_t max_size);
extern "C" void afl_custom_deinit(custom_mutator_t *data);