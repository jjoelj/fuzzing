include(ExternalProject)
cmake_minimum_required(VERSION 3.16)
project(fuzzing)

find_package(absl CONFIG REQUIRED)
find_package(Protobuf CONFIG REQUIRED)
find_package(libprotobuf-mutator CONFIG REQUIRED)

set(PROTO_LIB_INSTALL_DIR "${CMAKE_BINARY_DIR}/proto_lib_install")

ExternalProject_Add(proto_lib_ep
        SOURCE_DIR ${CMAKE_SOURCE_DIR}/mutator
        BINARY_DIR ${CMAKE_BINARY_DIR}/mutator

        CMAKE_ARGS
        -DCMAKE_C_COMPILER=gcc
        -DCMAKE_CXX_COMPILER=g++
        -DCMAKE_INSTALL_PREFIX=<INSTALL_DIR>
        -DCMAKE_BUILD_TYPE=${CMAKE_BUILD_TYPE}

        INSTALL_DIR ${PROTO_LIB_INSTALL_DIR}
        BUILD_ALWAYS 1
)

set(PROTO_LIB_CONFIG_FILE
        "${PROTO_LIB_INSTALL_DIR}/lib/cmake/proto_lib/proto_libConfig.cmake"
)

if(NOT EXISTS "${PROTO_LIB_CONFIG_FILE}")
    message(WARNING
            "\nproto_lib is not built yet.\n"
            "Run:   cmake --build . --target proto_lib_ep -- -j$(nproc)\n"
            "Then re-run cmake ..\n"
    )
endif()

if(EXISTS "${PROTO_LIB_CONFIG_FILE}")
    list(APPEND CMAKE_PREFIX_PATH "${PROTO_LIB_INSTALL_DIR}")
    find_package(proto_lib CONFIG REQUIRED)
endif()

add_library(parser_lib parser.cpp)
add_dependencies(parser_lib proto_lib_ep)

if(TARGET proto_lib::proto_lib)
    target_link_libraries(parser_lib PUBLIC
            proto_lib::proto_lib
            libprotobuf-mutator::protobuf-mutator-libfuzzer
    )
    target_include_directories(parser_lib PUBLIC ${PROTO_LIB_INSTALL_DIR}/include/generated)
endif()

add_executable(test_parser test_parser.cpp)
if(TARGET proto_lib::proto_lib)
    target_link_libraries(test_parser PRIVATE proto_lib::proto_lib parser_lib)
endif()

add_executable(main main.cpp)
if(TARGET proto_lib::proto_lib)
    target_link_libraries(main PRIVATE proto_lib::proto_lib parser_lib)
endif()

add_executable(fuzz_main main.cpp)
if (TARGET proto_lib::proto_lib)
    target_link_libraries(fuzz_main PRIVATE
            proto_lib::proto_lib
            parser_lib
    )
    target_compile_definitions(fuzz_main PRIVATE FUZZING_BUILD=1)
endif()