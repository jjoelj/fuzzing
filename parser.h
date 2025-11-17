#ifndef FUZZING_PARSER_H
#define FUZZING_PARSER_H

#include <vector>
#include <string>
#include <variant>

#include "proto/sequence.pb.h"

enum CommandType {
    InvalidCommand,
    Add,
    Remove,
    Divide,
    Reset,
    Print
};

struct addArgs {
    int32_t number;
};
struct removeArgs {
    bool allOccurrences;
    std::vector<int32_t> numbers;
};
struct divideArgs {
    double divisor;
};
struct resetArgs {};
struct printArgs {};

struct CommandStruct {
    CommandType type;
    std::variant<addArgs, removeArgs, divideArgs, resetArgs, printArgs> arguments;
};

namespace parser {
    std::vector<CommandStruct> parseCommands(const unsigned char *, size_t);
}

#endif //FUZZING_PARSER_H
