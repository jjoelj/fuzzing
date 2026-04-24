FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    git cmake ninja-build build-essential \
    python3 python3-pip python3-venv python3-dev python3-setuptools \
    clang lld llvm llvm-dev libclang-dev \
    libtool automake autoconf \
    sudo wget curl pkg-config \
    flex bison \
    libglib2.0-dev libpixman-1-dev \
    && rm -rf /var/lib/apt/lists/*

# BO controller deps — CPU-only torch to keep the image manageable
RUN python3 -m venv /opt/bo_venv && \
    /opt/bo_venv/bin/pip install --upgrade pip && \
    /opt/bo_venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu && \
    /opt/bo_venv/bin/pip install botorch gpytorch scipy numpy matplotlib pandas

RUN useradd -m user && usermod -aG sudo user && \
    echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers

USER user

ENV PATH="/opt/bo_venv/bin:/usr/local/bin:${PATH}"
# Both expected limitations of rootless Docker — neither affects crash detection
ENV AFL_SKIP_CPUFREQ=1
ENV AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES=1

WORKDIR /home/user

RUN git clone https://github.com/AFLplusplus/AFLplusplus.git --recursive -b v4.31c && \
    cd AFLplusplus && \
    make source-only NO_NYX=1 PERFORMANCE=1 -j$(nproc) && \
    sudo make install

RUN git clone https://github.com/abseil/abseil-cpp.git --recursive -b 20240116.0 && \
    cd abseil-cpp && mkdir build && cd build && \
    cmake .. -GNinja \
        -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/usr/local && \
    ninja && sudo ninja install

RUN git clone https://github.com/protocolbuffers/protobuf.git --recursive -b v29.3 && \
    cd protobuf && mkdir build && cd build && \
    cmake .. -GNinja \
        -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        -Dprotobuf_BUILD_TESTS=OFF \
        -Dprotobuf_LOCAL_DEPENDENCIES_ONLY=ON && \
    ninja && sudo ninja install

RUN git clone https://github.com/google/libprotobuf-mutator.git --recursive -b v1.5 && \
    cd libprotobuf-mutator && mkdir build && cd build && \
    cmake .. -GNinja \
        -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        -DLIB_PROTO_MUTATOR_DOWNLOAD_PROTOBUF=OFF \
        -DLIB_PROTO_MUTATOR_TESTING=OFF && \
    ninja && sudo ninja install

ENV CC=afl-clang-lto
ENV CXX=afl-clang-lto++

CMD ["bash"]
