file(GLOB SOURCES
    RELATIVE ${CMAKE_CURRENT_SOURCE_DIR}
    topologies/*.cpp
    traffic/*.cpp
    control/*.cpp
)


# Create static library
# add_library(htsim_dc STATIC ${LIB_SOURCES})
add_library(htsim_dc STATIC ${SOURCES})
target_include_directories(htsim_dc PUBLIC
    ${PROJECT_SOURCE_DIR}
    ${PROJECT_SOURCE_DIR}/src
    ${PROJECT_SOURCE_DIR}/src/components
    ${PROJECT_SOURCE_DIR}/src/core
    ${PROJECT_SOURCE_DIR}/src/logging
    ${PROJECT_SOURCE_DIR}/src/models
    ${PROJECT_SOURCE_DIR}/src/packets
    ${PROJECT_SOURCE_DIR}/src/protocols
    ${PROJECT_SOURCE_DIR}/src/utils
)
target_include_directories(htsim_dc PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/control
    ${CMAKE_CURRENT_SOURCE_DIR}/main
    ${CMAKE_CURRENT_SOURCE_DIR}/topologies
    ${CMAKE_CURRENT_SOURCE_DIR}/traffic

)

