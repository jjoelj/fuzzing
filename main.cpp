#include <fstream>
#include <vector>
#include <unistd.h>
#include <iostream>
#include <numeric>
#include <unordered_map>

#include "parser.h"

#ifdef FUZZING_BUILD
__AFL_FUZZ_INIT();
#endif

const std::unordered_map<CommandType, std::string> command_names = {
    {InvalidCommand, "InvalidCommand"},
    {Add, "Add"},
    {Remove, "Remove"},
    {Divide, "Divide"},
    {Reset, "Reset"},
    {Print, "Print"}
};

std::vector<int32_t> values;

void run_command(const CommandStruct &command) {
    removeArgs remove_args;
    switch (command.type) {
        case Add:
            // Simulate addition
            values.push_back(std::get<addArgs>(command.arguments).number);
            break;
        case Remove:
            remove_args = std::get<removeArgs>(command.arguments);
            if (remove_args.allOccurrences) {
                for (const auto &val: remove_args.numbers) {
                    values.erase(std::remove(values.begin(), values.end(), val), values.end());
                }
            } else {
                for (const auto &val: remove_args.numbers) {
                    auto it = std::find(values.begin(), values.end(), val);
                    if (it != values.end()) {
                        values.erase(it);
                    }
                }
            }
            break;
        case Divide:
            if (std::get<divideArgs>(command.arguments).divisor == 0) {
                break;
            }
            for (auto val: values) {
                val = static_cast<int>(1.0 * val / std::get<divideArgs>(command.arguments).divisor);
            }
            break;
        case Reset:
            values.clear();
            break;
        case Print:
            for (const auto &val: values) {
                std::cout << val << " ";
            }
            std::cout << std::endl;
            break;
        case InvalidCommand:
            break;
    }
}

void simulate(const unsigned char *buf, const size_t len) {
    std::vector<CommandStruct> sequence = parser::parseCommands(buf, len);
    for (const auto &command: sequence) {
#ifndef FUZZING_BUILD
        std::cout << "Simulating command: " << command_names.at(command.type) << std::endl;
#endif
        run_command(command);
        if (std::accumulate(values.begin(), values.end(), 0) == 42) {
            std::cerr << "Abort triggered: sum equals 42" << std::endl;
            abort();
        }
        if (std::accumulate(values.begin(), values.end(), 0, [](const int acc, const int val) {
            return acc + val % 27;
        }) == 133) {
            std::cerr << "Abort triggered: sum equals 133" << std::endl;
            abort();
        }
    }
}

int main(int argc, char *argv[]) {
#ifndef FUZZING_BUILD
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <inputfile>" << std::endl;
        return 1;
    }
    std::ifstream f(argv[1], std::ios::binary);
    std::vector<unsigned char> filebuf(
        (std::istreambuf_iterator(f)),
        std::istreambuf_iterator<char>()
    );
    simulate(filebuf.data(), filebuf.size());
#else
    ssize_t len;
    unsigned char *buf;

    __AFL_INIT();

    buf = __AFL_FUZZ_TESTCASE_BUF;
    len = __AFL_FUZZ_TESTCASE_LEN;
    simulate(buf, len);
#endif

    return 0;
}
