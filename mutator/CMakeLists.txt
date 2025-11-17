cmake_minimum_required(VERSION 3.16)

project(mutator)

find_package(Protobuf CONFIG REQUIRED)
find_package(libprotobuf-mutator CONFIG REQUIRED)

file(GLOB PROTO_FILES ${CMAKE_CURRENT_SOURCE_DIR}/proto/*.proto)

set(GENERATED_DIR ${CMAKE_BINARY_DIR}/generated)
file(MAKE_DIRECTORY ${GENERATED_DIR})

add_library(proto_lib)
protobuf_generate(
        TARGET proto_lib
        LANGUAGE cpp
        PROTOC_OUT_DIR ${GENERATED_DIR}
        PROTOS ${PROTO_FILES}
        IMPORT_DIRS ${CMAKE_SOURCE_DIR}/proto
)


target_include_directories(proto_lib PUBLIC
        $<BUILD_INTERFACE:${GENERATED_DIR}>
        $<INSTALL_INTERFACE:include/generated>
)


target_link_libraries(proto_lib PRIVATE protobuf::libprotobuf)
target_compile_options(proto_lib PRIVATE -fPIC)

add_library(mutator SHARED mutator.cpp mutator.h)
target_link_libraries(mutator PUBLIC proto_lib libprotobuf-mutator::protobuf-mutator-libfuzzer)
target_compile_options(mutator PRIVATE -fPIC)
target_include_directories(mutator PRIVATE ~/AFLplusplus/include)

install(
        DIRECTORY ${GENERATED_DIR}
        DESTINATION include
        FILES_MATCHING PATTERN "*.h"
)

install(TARGETS proto_lib
        EXPORT proto_libTarget
        ARCHIVE DESTINATION lib
        LIBRARY DESTINATION lib
        RUNTIME DESTINATION bin
)

install(EXPORT proto_libTarget FILE proto_libTarget.cmake NAMESPACE proto_lib:: DESTINATION lib/cmake/proto_lib)

include(CMakePackageConfigHelpers)
configure_package_config_file(
        proto_libConfig.cmake.in
        ${CMAKE_CURRENT_BINARY_DIR}/proto_libConfig.cmake
        INSTALL_DESTINATION lib/cmake/proto_lib
)

install(FILES ${CMAKE_CURRENT_BINARY_DIR}/proto_libConfig.cmake DESTINATION lib/cmake/proto_lib)