FROM ghcr.io/xu-cheng/texlive-full:latest

RUN apk add --no-cache \
    font-noto-cjk \
    font-noto \
    fontconfig \
    python3 \
    py3-numpy \
    py3-sympy \
    && fc-cache -fv

WORKDIR /workspace
