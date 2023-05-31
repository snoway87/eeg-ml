OBJCOPY = avr-objcopy
OBJDUMP = avr-objdump
SIZE    = avr-size --format=avr --mcu=$(MCU)
CC      = avr-gcc

SRCs			= main.c
OBJs      = $(SRCs:.c=.o)

EXT =
INCLUDE := $(foreach dir, $(EXT), -I$(dir))

CFLAGS = -mmcu=atmega32a -Wall -Os -Wno-misspelled-isr -lm -mcall-prologues -std=gnu99 --param=min-pagesize=0 -DF_CPU=$(CLK) $(INCLUDE)
LDFLAGS = -mmcu=atmega32a  -Wall -g -Os -Wno-misspelled-isr -Werror

all: $(MCU)

$(MCU): $(OBJs)
	$(CC) $(LDFLAGS) -o $@.elf $(OBJs) -lm
	$(OBJCOPY) -O binary -R .eeprom -R .nwram  $@.elf $@.bin
	$(OBJCOPY) -O ihex -R .eeprom -R .nwram  $@.elf $@.hex

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f *.elf *.bin *.hex $(OBJs) *.map
