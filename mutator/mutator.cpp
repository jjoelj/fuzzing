#include "mutator.h"

#include <algorithm>
#include <cstdlib>
#include <cstring>

#include "src/libfuzzer/libfuzzer_macro.h"
#include "port/protobuf.h"
#include "proto/sequence.pb.h"

extern "C" custom_mutator_t *afl_custom_init(void *, const unsigned int seed) {
    auto *data = static_cast<custom_mutator_t *>(malloc(sizeof(custom_mutator_t)));
    data->seed = seed;
    data->buf = static_cast<unsigned char *>(calloc(1, 100));
    data->buf_size = 100;
    return data;
}

extern "C" size_t afl_custom_fuzz(
    custom_mutator_t *data,
    unsigned char *buf, size_t buf_size,
    unsigned char **out_buf,
    unsigned char *add_buf, size_t add_buf_size,
    size_t max_size)
{
    using protobuf_mutator::libfuzzer::CustomProtoMutator;
    using protobuf_mutator::libfuzzer::CustomProtoCrossOver;

    Sequence input1;

    data->buf_size = std::max(max_size, buf_size);
    data->buf = static_cast<unsigned char *>(realloc(data->buf, data->buf_size));
    memcpy(data->buf, buf, buf_size);
    data->buf_size = CustomProtoMutator(true, data->buf, buf_size, max_size, data->seed, &input1);

    *out_buf = data->buf;
    return data->buf_size;
}



extern "C" void afl_custom_deinit(custom_mutator_t *data) {
    free(data->buf);
    free(data);
}
