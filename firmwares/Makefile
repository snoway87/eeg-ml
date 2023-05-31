include .env
docker_bin := $(shell command -v docker 2> /dev/null)
docker_compose_bin := $(shell command -v docker-compose 2> /dev/null)
export $(shell sed 's/=.*//' .env)


context:
	$(docker_bin) context use $(DOCKER_CONTEXT)


# Container instance
# ----------------------------------------------------------------

up: context
	$(docker_compose_bin) build
	$(docker_compose_bin) up --no-recreate -d
down: context
	$(docker_compose_bin) down -v
restart: context
	$(docker_compose_bin) restart
ps: context
	$(docker_compose_bin) ps
sh: context
	$(docker_bin) exec -it avr_tools /bin/bash


# Specific project targets
# ----------------------------------------------------------------

build: up
	$(docker_bin) exec -it avr_tools /bin/bash -c 'make clean'
	$(docker_bin) exec -it -e MCU=$(MCU) -e CLK=$(CLK) avr_tools /bin/bash -c 'make'

flash: build
	$(docker_bin) exec -it avr_tools /bin/bash -c ' \
	avrdude -c linuxgpio -p $(MCU) -v -U lfuse:w:$(LFUSE):m -U hfuse:w:$(HFUSE):m && \
	avrdude -c linuxgpio -p $(MCU) -v -U flash:w:$(MCU).hex'

test: up
	$(docker_bin) exec -it avr_tools /bin/bash -c 'avrdude -c linuxgpio -p $(MCU) -v -U signature:r:-:i -U hfuse:r:-:h -U lfuse:r:-:h'
