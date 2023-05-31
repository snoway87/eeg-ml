FROM alpine:edge

COPY keep-alive.sh /keep-alive.sh
COPY avrdude.conf /etc/avrdude.conf

RUN apk add --no-cache \
  ca-certificates wget make cmake avrdude avr-libc gcc-avr bash \
  && mkdir -p /sources && chmod +x /keep-alive.sh

WORKDIR /sources
ENTRYPOINT []
CMD [ "/keep-alive.sh" ]