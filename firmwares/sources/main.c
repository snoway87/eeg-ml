#ifndef __AVR_ATmega32__
#define __AVR_ATmega32__
#endif

#include <stdio.h>
#include <inttypes.h>
#include <string.h>
#include <util/delay.h>
#include <util/atomic.h>

#include <avr/io.h>
#include <avr/interrupt.h>


#define ESP8266_OK        0
#define ESP8266_ERROR     1
#define ESP8266_TIMEOUT   2

#define LED_GREEN         (1 << PD6)
#define LED_RED           (1 << PD7)

#define PIN_CONVSTA       (1 << PB4)
#define PIN_CONVSTB       (1 << PB3)
#define PIN_RESET         (1 << PB2)
#define PIN_RD            (1 << PB1)
#define PIN_CS            (1 << PB0)
#define PIN_BUSY          (1 << PD2)
#define PIN_FIRST         (1 << PD3)

volatile uint8_t samples_iter, batches_iter, packet_counter;
volatile uint16_t tx_iter, rx_iter;
volatile uint32_t tx_len;

#define BATCH_PACKET_SIZE       805
#define BATCH_PACKET_SAMPLES    80
#define TOTAL_ADC_CHANNELS      5

#pragma pack(push)
#pragma pack(1)
struct batch_packet_t {
  uint8_t   sync[2];                                                /* 0xAABB */
  uint8_t   counter;                                                /* packet counter */
  int16_t   adc_values[TOTAL_ADC_CHANNELS * BATCH_PACKET_SAMPLES];
  uint16_t  crc16;
};
#pragma pack(pop)

#define TX_BUFFER_SIZE BATCH_PACKET_SIZE * 2                        /* 1608 bytes */
#define RX_BUFFER_SIZE 64
volatile char tx_buffer[TX_BUFFER_SIZE];
volatile char rx_buffer[RX_BUFFER_SIZE];


//
// CRC16 implementation
// -----------------------------------------------------
uint16_t
crc16(uint8_t * buffer, uint16_t value, uint16_t offset, uint16_t length) {
  uint16_t crc = value;
  for(uint16_t i = offset; i < length; i ++ ) {
    crc ^= *( buffer + i );
    for (uint8_t j = 0; j < 8; j++) {
      if (crc & 1)
        crc = (crc >> 1) ^ 0xA001;
      else
        crc = (crc >> 1);
    }
  }
  return crc & 0xffff;
}


//
// AD7606
// -----------------------------------------------------
void
ad7606_reset() {
  PORTB |= PIN_RESET;
  _delay_ms(1);
  PORTB &= ~PIN_RESET;
}

void
ad7606_start() {
  PORTB &= ~(PIN_CONVSTA | PIN_CONVSTB);
  _delay_us(1);
  PORTB |= (PIN_CONVSTA | PIN_CONVSTB);
}

void
ad7606_read(int16_t * values, uint8_t channels) {
  int8_t * l_value, * h_value;

  PORTB &= ~PIN_CS;
  for(int i = 0; i < channels; i ++ ) {
    PORTB &= ~PIN_RD;
    l_value = (int8_t *) &values[i];
    h_value = l_value + 1;
    *l_value = PINA;
    *h_value = PINC;
    PORTB |= PIN_RD;
    /* Revers bits for high byte! See the electrical scheme */
    *h_value = (*h_value & 0xf0) >> 4 | (*h_value & 0x0f) << 4;
    *h_value = (*h_value & 0xcc) >> 2 | (*h_value & 0x33) << 2;
    *h_value = (*h_value & 0xaa) >> 1 | (*h_value & 0x55) << 1;
  }
  PORTB |= PIN_CS;
}


//
// Interrupts
// -----------------------------------------------------
ISR(TIMER1_COMPA_vect) {
  ad7606_start();
  /* Enable INT0 Interrupt */
  GICR  |= (1 << INT0);
}

ISR(USART_RXC_vect) {
  rx_buffer[rx_iter++] = UDR;
}

ISR(USART_UDRE_vect) {
  if(tx_iter >= tx_len) {
      // PORTD &= ~LED_RED;
      UCSRB &= ~( 1 << UDRIE );
      return;
  }
  UDR = tx_buffer[tx_iter++];
}

ISR(INT0_vect) {
  /*
   * ESP8266 has 20ms interval between 2 packets in the transparent transmission mode.
   * Send every 80 measurements (1 batch) to ESP8266:
   * 1. 2000Hz -> ~0.5ms
   * 2. 1 btach = 80 measurements -> 40ms = 804 bytes total
   * 3. 1000000 baud -> 1000000/(8+1+1)/1000 = ~100 bytes/ms (real = ~75 bytes/ms)
   * 4. UART transfer delay = 804 / 75 = ~10.7 ms (real = ~11.2ms)
   * 5. WiFi transfer interval = 40ms - 11.2ms = ~29ms total (20ms transmission mode interval + ~9ms data transfer):
   * 6. Theoretically, 25 batches per 1 second for the reciever side
   *
   */


  static uint16_t crc16_offset, crc16_length;
  static uint16_t crc16_value  = 0xffff;
  struct batch_packet_t * packet = (struct batch_packet_t *) &tx_buffer[batches_iter * BATCH_PACKET_SIZE];

  /* First init */
  if(!samples_iter) {
    packet->sync[0]   = 0xAA;
    packet->sync[1]   = 0xBB;
    packet->counter   = packet_counter;
    crc16_offset      = 0;
    crc16_length      = 3;
  }

  /* Filling ADC values */
  ad7606_read(&packet->adc_values[samples_iter * TOTAL_ADC_CHANNELS], TOTAL_ADC_CHANNELS);

  /* CRC16 */
  crc16_length += 2 * TOTAL_ADC_CHANNELS;
  crc16_value  = crc16((uint8_t *) packet, crc16_value, crc16_offset, crc16_length);
  crc16_offset = crc16_length;

  /* Current batch packet is full */
  samples_iter = (samples_iter + 1) % BATCH_PACKET_SAMPLES;
  if(!samples_iter) {
    packet->crc16   = 0;
    packet->crc16   = crc16((uint8_t *) packet, crc16_value, crc16_offset, crc16_length + 2);
    crc16_value     = 0xffff;

    tx_iter = (!batches_iter)? 0 : BATCH_PACKET_SIZE;
    tx_len  = (!batches_iter)? BATCH_PACKET_SIZE : BATCH_PACKET_SIZE * 2;

    batches_iter = (batches_iter + 1) % 2;
    packet_counter++;

    /* Start sending process */
    // PORTD |= LED_RED;
    UDR = tx_buffer[tx_iter++];
    UCSRB |= ( 1 << UDRIE );
  }

  /* Disable INT0 Interrupt */
  GICR  &= ~(1 << INT0);
}

//
// Entry point
// -----------------------------------------------------
int main( void ) {
  uint8_t result;

  /* Directions */
  DDRA = DDRC = 0;
  DDRD |= (LED_GREEN | LED_RED);
  DDRD &= ~(PIN_BUSY | PIN_FIRST);
  DDRB |= (PIN_CONVSTA | PIN_CONVSTB | PIN_RESET | PIN_RD | PIN_CS);
  /* Default states */
  PORTB |= (PIN_CONVSTA | PIN_CONVSTB | PIN_RD | PIN_CS);
  PORTD &= ~(LED_GREEN | LED_RED);

  /* INT0 */
  PORTD |= (1 << PIN_BUSY);                                     /* Pull-up INT0 */
  MCUCR |= ((0 << ISC01) | (0 << ISC00));                       /* The low level of INT0 generates an interrupt request */

  /* UART */
  UCSRA  = ( 1 << U2X  );                                       /* Double bps */
  UCSRB |= ( 1 << TXEN ) | ( 1 << RXEN ) | ( 1 << RXCIE );      /* Enable Interrupts: TXEN, RXEN, RXCIE */
  UCSRC |= ( 1 << UCSZ1 ) | ( 1 << UCSZ0 );                     /* 8-bit data, 1 stop bit, None parity */
  uint16_t ubrr = 1;                                            /* Baudrate 10000000 (See the Table 20-12, page 171) */
  UBRRH  = ubrr >> 8;
  UBRRL  = ubrr;

  sei();
  /* Awaiting for ESP8266 */
  _delay_ms(2000);

  PORTD |= (LED_GREEN);
  ad7606_reset();

  /* Timer1 (16 bit) - ADC Conversion - 2000Hz */
  TCCR1B |= (1 << WGM12) | (1 << CS11) | (1 << CS10);           /* 16Mhz/64 */
  OCR1A = 124;                                                  /* Match overflow value (16Mhz/64/2000Hz ~ 125 - 1 = 124!) */
  TIMSK |= ( 1 << OCIE1A );                                     /* Enable Interrupt */

  while(1) {};
  return 0;
}