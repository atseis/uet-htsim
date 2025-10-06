cmake_minimum_required(VERSION 3.16)
include(FetchContent)

project(htsim_project LANGUAGES CXX)
option(ENABLE_TESTS "enable the test suite" OFF)

# Set C++ standard and compiler flags
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF) # Ensures GNU extensions are disabled
set(CMAKE_CXX_FLAGS_RELEASE -O3) # Prevent -DNDEBUG, htsim requires
# asserts to be enabled.
# Set compiler flags
add_compile_options(
    -Wall
    -g
    -Wsign-compare
    -Wuninitialized
    -fPIE
    -O3
)
if(CMAKE_BUILD_TYPE STREQUAL "Debug")
    add_compile_options(-O0 -g -ggdb3 -fno-omit-frame-pointer -fno-inline)
endif()

# Optionally enable sanitizers
# -fsanitize=address -fno-omit-frame-pointer -fsanitize=undefined"

if ( ENABLE_TESTS )
    # Fetch GoogleTest
    FetchContent_Declare(
    googletest
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG v1.15.2
    )
    FetchContent_MakeAvailable(googletest)
    include(GoogleTest)
    enable_testing()
endif()

# Function to add a symlink creation step for an executable.
# Used to create a symlink in the source directory to the executable
# in the build directory for easier access and backward compatibility.
function(add_symlink_target EXECUTABLE TARGET_DIR)
    add_custom_command(
        TARGET ${EXECUTABLE}
        POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E remove ${TARGET_DIR}/${EXECUTABLE} # Remove existing symlink
        COMMAND ${CMAKE_COMMAND} -E create_symlink
            $<TARGET_FILE:${EXECUTABLE}>  # Path to the executable
            ${TARGET_DIR}/${EXECUTABLE}  # Path for the symlink
        COMMENT "Removing and recreating symlink for ${EXECUTABLE} in ${TARGET_DIR}"
    )
endfunction()

file(GLOB SOURCE_FILES
    RELATIVE ${CMAKE_CURRENT_SOURCE_DIR}
    src/**/*.cpp
    src/*.cpp
)

# Create static library
add_library(htsim STATIC ${SOURCE_FILES})
target_include_directories(htsim PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/src/core
    ${CMAKE_CURRENT_SOURCE_DIR}/src/components
    ${CMAKE_CURRENT_SOURCE_DIR}/src/protocols
    ${CMAKE_CURRENT_SOURCE_DIR}/src/logging
    ${CMAKE_CURRENT_SOURCE_DIR}/src/packets
    ${CMAKE_CURRENT_SOURCE_DIR}/src/utils
    ${CMAKE_CURRENT_SOURCE_DIR}/src/models
) # Needed for header-only libraries (e.g., loggertypes.h).

# Add subdirectories
add_subdirectory(datacenter)

# Define executables and link with htsim library
add_executable(parse_output parse_output.cpp)
target_link_libraries(parse_output PRIVATE htsim)

if ( ENABLE_TESTS )
    # Unit tests.
    set(UNIT_TEST_FILES
        pipe_test
    )

    foreach(UNIT_TEST_FILE ${UNIT_TEST_FILES})
        add_executable(${UNIT_TEST_FILE} ${UNIT_TEST_FILE}.cpp)
        target_link_libraries(${UNIT_TEST_FILE} PRIVATE htsim gtest_main gmock_main)
        gtest_discover_tests(${UNIT_TEST_FILE}
            PROPERTIES LABELS "unit"
            PROPERTIES TIMEOUT 60
        )
    endforeach()
endif()

# Always print ENABLE_TESTS status, so folks don't miss it.
add_custom_target(
  always_run ALL
  COMMAND ${CMAKE_COMMAND} -E echo "ENABLE_TESTS=${ENABLE_TESTS}"
)


# -------------------------------
# Executable Definitions
# -------------------------------
# List of Executables and Their Main Source Files.
set(ALL_EXECUTABLES)
set(MAIN_DIR "${CMAKE_CURRENT_SOURCE_DIR}/main")
file(GLOB MAIN_SOURCES RELATIVE ${CMAKE_CURRENT_SOURCE_DIR} "${MAIN_DIR}/*.cpp")
foreach(MAIN_SRC ${MAIN_SOURCES})
    # 获取文件名（不含路径和扩展名），用作可执行文件名
    get_filename_component(EXEC_NAME ${MAIN_SRC} NAME_WE)
    string(REPLACE "main_" "htsim_" TARGET_NAME ${EXEC_NAME})
    # set(TARGET_NAME "htsim_${TARGET_NAME}")
    # 添加可执行文件
    # message(STATUS "===========${MAIN_SRC}============")
    add_executable(${TARGET_NAME} ${MAIN_SRC})

    if(NOT TARGET_NAME STREQUAL "htsim_uec")
        # 如果不是 uec，就设置 EXCLUDE_FROM_ALL
        set_property(TARGET ${TARGET_NAME} PROPERTY EXCLUDE_FROM_ALL TRUE)
    endif()
    list(APPEND ALL_EXECUTABLES ${TARGET_NAME})
endforeach()

foreach(EXECUTABLE ${ALL_EXECUTABLES})
    # Link each executable with the 'htsim' library defined in the parent directory.
    target_link_libraries(${EXECUTABLE} PRIVATE htsim_dc)
    target_link_libraries(${EXECUTABLE} PRIVATE htsim)
    # Add a post-build command to explicitly remove and recreate the symlink for all previous executables.
    add_symlink_target(${EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/bin)
endforeach()

