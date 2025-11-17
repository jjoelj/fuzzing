FROM ubuntu:latest

RUN apt update && apt install -y \
    git \
    cmake \
    ninja-build \
    build-essential \
    python3 \
    python3-pip \
    clang \
    lld \
    llvm \
    libtool \
    automake \
    autoconf \
    sudo \
    wget \
    pkg-config \
    build-essential \
    python3-dev \
    flex \
    bison \
    libglib2.0-dev \
    libpixman-1-dev \
    python3-setuptools \
    libgtk-3-dev

RUN useradd -m user && usermod -aG sudo user

RUN echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers

USER user
ENV PATH="/usr/local/bin:${PATH}"

WORKDIR /home/user

RUN git clone https://github.com/AFLplusplus/AFLplusplus.git --recursive -b v4.31c && \
    cd AFLplusplus && \
    make source-only NO_NYX=1 PERFORMANCE=1 -j$(nproc) && \
    sudo make install

RUN git clone https://github.com/abseil/abseil-cpp.git --recursive -b 20240116.0 && \
    cd abseil-cpp && \
    mkdir build && cd build && \
    cmake .. \
    -GNinja \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr/local && \
    ninja && \
    sudo ninja install

RUN git clone https://github.com/protocolbuffers/protobuf.git --recursive -b v29.3 && \
    cd protobuf && \
    mkdir build && cd build && \
    cmake .. \
    -GNinja \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    -Dprotobuf_BUILD_TESTS=OFF \
    -Dprotobuf_LOCAL_DEPENDENCIES_ONLY=ON && \
    ninja && \
    sudo ninja install

RUN git clone https://github.com/google/libprotobuf-mutator.git --recursive -b v1.5 && \
    cd libprotobuf-mutator && \
    mkdir build && cd build && \
    cmake .. \
    -GNinja \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    -DLIB_PROTO_MUTATOR_DOWNLOAD_PROTOBUF=OFF \
    -DLIB_PROTO_MUTATOR_TESTING=OFF && \
    ninja && \
    sudo ninja install

ENV CC=afl-clang-lto
ENV CXX=afl-clang-lto++

CMD ["bash"]
