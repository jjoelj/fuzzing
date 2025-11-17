#include "parser.h"

#include <iostream>

#include "src/libfuzzer/libfuzzer_macro.h"
#include "src/text_format.h"

namespace parser {
    std::vector<CommandStruct> parseCommands(const unsigned char *buf, const size_t len) {
        Sequence sequence;

        if (!sequence.ParsePartialFromArray(buf, len)) {
            return {};
        }

        std::vector<CommandStruct> commands;
        for (const auto& command : sequence.command()) {
            CommandStruct commandStruct;
            switch (command.command_case()) {
                case Command::kAdd:
                    commandStruct.type = Add;
                    commandStruct.arguments = addArgs({command.add().number()});
                    break;
                case Command::kRemove:
                    commandStruct.type = Remove;
                    commandStruct.arguments = removeArgs({command.remove().alloccurrences(), std::vector<int32_t>(command.remove().numbers().begin(), command.remove().numbers().end())});
                    break;
                case Command::kDivide:
                    commandStruct.type = Divide;
                    commandStruct.arguments = divideArgs({command.divide().divisor()});
                    break;
                case Command::kReset:
                    commandStruct.type = Reset;
                    commandStruct.arguments = resetArgs({});
                    break;
                case Command::kPrint:
                    commandStruct.type = Print;
                    commandStruct.arguments = printArgs({});
                    break;
                default:
                    commandStruct.type = InvalidCommand;
                    break;
            }
            commands.push_back(commandStruct);
        }

        return commands;
    }
} // namespace parser
