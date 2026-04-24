#include "mutator.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <string>

#include "src/libfuzzer/libfuzzer_macro.h"
#include "port/protobuf.h"
#include "proto/sequence.pb.h"

static void load_theta(custom_mutator_t *data) {
    FILE *f = fopen(data->theta_path, "r");
    if (!f) return;

    double w[NUM_OPS];
    unsigned int e;
    if (fscanf(f, "%lf %lf %lf %lf %lf %u",
               &w[0], &w[1], &w[2], &w[3], &w[4], &e) == NUM_OPS + 1) {
        double sum = 0;
        for (int i = 0; i < NUM_OPS; i++) sum += w[i];
        if (sum > 0)
            for (int i = 0; i < NUM_OPS; i++) data->weights[i] = w[i] / sum;
        data->energy = (e >= 1) ? e : 1;
    }
    fclose(f);
}

static int sample_operator(const custom_mutator_t *data, std::mt19937 &rng) {
    double total = 0;
    for (int i = 0; i < NUM_OPS; i++) total += data->weights[i];
    double r = std::uniform_real_distribution<double>(0.0, total)(rng);
    double cum = 0;
    for (int i = 0; i < NUM_OPS - 1; i++) {
        cum += data->weights[i];
        if (r < cum) return i;
    }
    return NUM_OPS - 1;
}

static Command random_command(std::mt19937 &rng) {
    Command cmd;
    std::uniform_int_distribution<int32_t> int_dist(-50, 50);
    std::uniform_real_distribution<double> dbl_dist(0.5, 10.0);

    switch (std::uniform_int_distribution<int>(0, 4)(rng)) {
        case 0:
            cmd.mutable_add()->set_number(int_dist(rng));
            break;
        case 1: {
            auto *r = cmd.mutable_remove();
            r->set_all_occurrences(std::bernoulli_distribution(0.5)(rng));
            int n = std::uniform_int_distribution<int>(1, 3)(rng);
            for (int i = 0; i < n; i++) r->add_numbers(int_dist(rng));
            break;
        }
        case 2: {
            double d;
            do { d = dbl_dist(rng); } while (d < 0.01);
            cmd.mutable_divide()->set_divisor(d);
            break;
        }
        case 3:
            cmd.mutable_reset();
            break;
        default:
            cmd.mutable_print();
            break;
    }
    return cmd;
}

static void op_add(Sequence &seq, std::mt19937 &rng) {
    int n = seq.command_size();
    int pos = (n == 0) ? 0 : std::uniform_int_distribution<int>(0, n)(rng);
    *seq.add_command() = random_command(rng);
    // rotate new tail element to pos
    for (int i = seq.command_size() - 1; i > pos; i--)
        seq.mutable_command()->SwapElements(i, i - 1);
}

static void op_modify(Sequence &seq, std::mt19937 &rng) {
    int n = seq.command_size();
    if (n == 0) { op_add(seq, rng); return; }

    int pos = std::uniform_int_distribution<int>(0, n - 1)(rng);
    Command &cmd = *seq.mutable_command(pos);
    std::uniform_int_distribution<int32_t> int_dist(-50, 50);
    std::uniform_real_distribution<double> dbl_dist(0.5, 10.0);

    switch (cmd.command_case()) {
        case Command::kAdd:
            cmd.mutable_add()->set_number(int_dist(rng));
            break;
        case Command::kRemove: {
            auto *r = cmd.mutable_remove();
            if (r->numbers_size() > 0 && std::bernoulli_distribution(0.5)(rng)) {
                int idx = std::uniform_int_distribution<int>(0, r->numbers_size() - 1)(rng);
                r->set_numbers(idx, int_dist(rng));
            } else {
                r->set_all_occurrences(!r->all_occurrences());
            }
            break;
        }
        case Command::kDivide: {
            double d;
            do { d = dbl_dist(rng); } while (d < 0.01);
            cmd.mutable_divide()->set_divisor(d);
            break;
        }
        default:
            // Reset/Print have no parameters - replace entirely
            *seq.mutable_command(pos) = random_command(rng);
            break;
    }
}

static void op_delete(Sequence &seq, std::mt19937 &rng) {
    int n = seq.command_size();
    if (n == 0) { op_add(seq, rng); return; }
    int pos = std::uniform_int_distribution<int>(0, n - 1)(rng);
    seq.mutable_command()->DeleteSubrange(pos, 1);
}

static void op_swap(Sequence &seq, std::mt19937 &rng) {
    int n = seq.command_size();
    if (n < 2) { op_add(seq, rng); return; }
    int a = std::uniform_int_distribution<int>(0, n - 1)(rng);
    int b;
    do { b = std::uniform_int_distribution<int>(0, n - 1)(rng); } while (b == a);
    seq.mutable_command()->SwapElements(a, b);
}

static void op_splice(Sequence &seq, const Sequence &add_seq, std::mt19937 &rng) {
    int add_n = add_seq.command_size();
    if (add_n == 0) { op_add(seq, rng); return; }
    int start = std::uniform_int_distribution<int>(0, add_n - 1)(rng);
    int len   = std::uniform_int_distribution<int>(1, std::min(3, add_n - start))(rng);
    for (int i = start; i < start + len; i++)
        *seq.add_command() = add_seq.command(i);
}

extern "C" custom_mutator_t *afl_custom_init(void *, unsigned int seed) {
    auto *data = static_cast<custom_mutator_t *>(calloc(1, sizeof(custom_mutator_t)));
    data->seed = seed;
    data->buf  = static_cast<unsigned char *>(calloc(1, 4096));
    data->buf_size = 4096;

    // Uniform defaults until BO controller writes the first theta
    for (int i = 0; i < NUM_OPS; i++) data->weights[i] = 1.0 / NUM_OPS;
    data->energy = 128;

    const char *env = getenv("BO_THETA_PATH");
    if (env && strlen(env) < sizeof(data->theta_path) - 1)
        strncpy(data->theta_path, env, sizeof(data->theta_path) - 1);
    else
        strncpy(data->theta_path, "./bo_state/theta.txt", sizeof(data->theta_path) - 1);

    load_theta(data);
    return data;
}

extern "C" uint32_t afl_custom_fuzz_count(custom_mutator_t *data,
                                           const uint8_t *, size_t) {
    return data->energy;
}

extern "C" size_t afl_custom_fuzz(
    custom_mutator_t *data,
    uint8_t *buf, size_t buf_size,
    uint8_t **out_buf,
    uint8_t *add_buf, size_t add_buf_size,
    size_t max_size)
{
    // Reload theta from disk periodically (every 256 calls, roughly once per round)
    if ((data->call_count++ & 0xFF) == 0) load_theta(data);

    std::mt19937 rng(data->seed++);

    // Grow internal buffer if needed
    if (max_size > data->buf_size) {
        data->buf = static_cast<uint8_t *>(realloc(data->buf, max_size));
        data->buf_size = max_size;
    }

    // Deserialise input
    Sequence seq;
    if (!seq.ParseFromArray(buf, static_cast<int>(buf_size))) {
        // Unparseable - hand off to CustomProtoMutator as fallback
        memcpy(data->buf, buf, buf_size);
        Sequence tmp;
        using protobuf_mutator::libfuzzer::CustomProtoMutator;
        size_t out_len = CustomProtoMutator(true, data->buf, buf_size, max_size,
                                             data->seed, &tmp);
        *out_buf = data->buf;
        return out_len;
    }

    int op = sample_operator(data, rng);
    switch (op) {
        case 0: op_add(seq, rng);    break;
        case 1: op_modify(seq, rng); break;
        case 2: op_delete(seq, rng); break;
        case 3: op_swap(seq, rng);   break;
        case 4: {
            Sequence add_seq;
            if (add_buf && add_buf_size > 0 &&
                add_seq.ParseFromArray(add_buf, static_cast<int>(add_buf_size)))
                op_splice(seq, add_seq, rng);
            else
                op_add(seq, rng);
            break;
        }
    }

    std::string out;
    if (!seq.SerializeToString(&out) || out.size() > max_size) {
        // Serialisation failed or too large - return original
        memcpy(data->buf, buf, buf_size);
        *out_buf = data->buf;
        return buf_size;
    }

    memcpy(data->buf, out.data(), out.size());
    *out_buf = data->buf;
    return out.size();
}

extern "C" void afl_custom_deinit(custom_mutator_t *data) {
    free(data->buf);
    free(data);
}
