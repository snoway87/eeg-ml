from concurrent.futures import thread
import time
import socket
import errno
import queue
import select
import os
import threading
import numpy as np
from bits import *
from events import *
from PyQt5 import QtCore, QtWidgets


#
# UDP Dispatcher
# ----------------------------------------------------------------------------------
class UDPDispatcher(QtCore.QThread):
    def __init__(self, parent=None):
        super(UDPDispatcher, self).__init__(parent=parent)
        self.parent = parent
        self.config = self.parent.config

        self.adc_range      = int(self.config['adc']['range'])
        self.adc_vref       = float(self.config['adc']['vref'])
        self.adc_channels   = int(self.config['adc']['channels'])
        self.batch_samples  = int(self.config['dataset']['batch_samples'])

        self.prev_crc16 = 0
        self.packet_counter = 0
        self.lost_packets = 0
        self.since = time.perf_counter()
        self.thread_stop = False
        self.buffer = bytearray()

        self.socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        self.socket.bind((
            str(self.config['network']['udp_dispatcher']['ip']),
            int(self.config['network']['udp_dispatcher']['port'])))
        self.socket.setblocking(False)

    def stop(self):
        self.thread_stop = True

    def calc_lost_packets(self, packet_counter: int):
        # The accumulate counter is byte: 0..0xff
        if self.packet_counter >= packet_counter:
            lost_packets = 255 - self.packet_counter + packet_counter
        else:
            lost_packets = packet_counter - self.packet_counter - 1
        self.packet_counter = packet_counter
        return lost_packets

    def ad7606_parse(self, offset, packet_size):
        found_packet = False
        if self.buffer[ offset ] == 0xAA and self.buffer[ offset + 1 ] == 0xBB:
            packet = Bits(bytes(self.buffer[offset:offset + packet_size]))
            # Check CRC16
            crc16 = packet.get_ubits(803 * 8, 16)
            raw_packet = self.buffer[offset:offset + packet_size]
            raw_packet[803] = raw_packet[804] = 0
            rem_crc16 = Bits.crc16_update(raw_packet, packet_size)
            # Fix ESP8266 bug!!!
            # Skip dublicate neighboring packets
            if crc16 == rem_crc16 and self.prev_crc16 != crc16:
                self.prev_crc16 = crc16
                found_packet = True
                lost_packets = self.calc_lost_packets(packet.get_ubits(2 * 8, 8))
                adc_values = [[0] * self.batch_samples ] * self.adc_channels
                for idx_channel, channel in enumerate(adc_values):
                    samples = []
                    for idx_sample, sample in enumerate(channel):
                        value = int(packet.get_sbits((3 + idx_sample * 10) * 8 + idx_channel * 16, 16))
                        value = (self.adc_range * value) / ((32768 * self.adc_vref) / 2.5)
                        samples.append(value)
                    adc_values[idx_channel] = samples
                QtWidgets.QApplication.postEvent(self.parent, UDPDispatcherEvent(adc_values, lost_packets))
        return found_packet

    # def ad7739_parse(self, offset):
    #     RANGE = 5               # +-2.5V
    #     RESOLUTION = 0xffff     # 16 bit
    #     PACKET_SIZE = 13
    #     result = lost_packets = 0
    #     adc_values = [0] * 5
    #     if self.buffer[ offset ] == 0xAB:
    #         packet = Bits(bytes(self.buffer[offset:offset + PACKET_SIZE]))
    #         crc8 = packet.get_ubits(96, 8)
    #         raw_packet = self.buffer[offset:offset + PACKET_SIZE]
    #         raw_packet[12] = 0
    #         if crc8 == Bits.crc8_update(raw_packet, PACKET_SIZE):
    #             result = PACKET_SIZE
    #             packet_counter = packet.get_ubits(8, 8)
    #             lost_packets = self.get_lost_packets(packet_counter)
    #             for i in range(0, 5):
    #                 adc_value_b1 = (packet.get_ubits(16 + (16 * i + 0), 8) << 8)  & 0xffff
    #                 adc_value_b2 = (packet.get_ubits(16 + (16 * i + 8), 8) << 0)  & 0xff
    #                 adc_value =  adc_value_b1 + adc_value_b2
    #                 adc_values[i] = ((adc_value * RANGE)/RESOLUTION) - RANGE/2
    #     return result, adc_values, lost_packets

    def run(self):
        BATCH_PACKET_SIZE = 805
        threading.current_thread().name = QtCore.QThread.currentThread().objectName()

        while not self.thread_stop:
            ready = select.select([self.socket], [], [], 0.1)
            if ready[0]:
                data = self.socket.recv(2048)
                self.buffer += bytearray(data)
                while len(self.buffer) >= BATCH_PACKET_SIZE:
                    for offset in range(0, len(self.buffer)):
                        # Parse batch packet
                        if self.ad7606_parse(offset, BATCH_PACKET_SIZE):
                            del self.buffer[offset:offset + BATCH_PACKET_SIZE]
                            break
                        # Move buffer
                        self.buffer = self.buffer[1:]
                        break
        self.socket.close()


#
# TCP Dispatcher
#
# Packet (9 bytes):
# uint8_t   sync[2]             - offset 0; 0xAA,0xCC
# uint8_t   event_code          - offset 2;
# uint8_t   event_iter          - offset 3; presents same data of current event code
# uint8_t   event_bits          - offset 4; resolution: 8, 16, 32
# uint16_t  data_size           - offset 5; total data bytes
# uint16_t  crc16               - offset 7;
# uint8_t   * data...           - offset 9;
# ----------------------------------------------------------------------------------
class ExchangeProtocol():
    TCP_SERVER                      = 1
    TCP_CLIENT                      = 2
    PACKET_HEADER_SIZE              = 9

    GAME_EVENT_UP                   = 1
    GAME_EVENT_DOWN                 = 2
    GAME_EVENT_LEFT                 = 3
    GAME_EVENT_RIGHT                = 4
    GAME_EVENT_START                = 5
    GAME_EVENT_STOP                 = 6
    GAME_EVENT_GAMEOVER             = 7

    DISPATCHER_EVENT_NEW_CLIENT     = 12
    DISPATCHER_EVENT_DEL_CLIENT     = 13

    DISPATCHER_EVENT_PING           = 14

    def __init__(self, config, bind_ip, bind_port, type):
        super(ExchangeProtocol, self).__init__()
        self.config             = config
        self.type               = type
        self.server_ip          = str(self.config['network']['tcp_dispatcher']['server_ip'])
        self.server_port        = int(self.config['network']['tcp_dispatcher']['server_port'])
        self.bind_ip            = bind_ip
        self.bind_port          = bind_port
        self.abonents           = len(self.config['network']['tcp_dispatcher']['abonents'])
        self.read_sockets       = []
        self.write_sockets      = []
        self.socket_addresses   = []
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def setup(self):
        # Client
        if self.type == ExchangeProtocol.TCP_CLIENT:
            self.socket.setblocking(True)
            try:
                self.socket.bind((self.bind_ip, self.bind_port))
                self.socket.connect((self.server_ip, self.server_port))
            except socket.error as error:
                self.socket.close()
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                print("Error: socket.connect = {:d}, {:s}".format(error.errno, os.strerror(error.errno)))
                return False
            else:
                self.socket.setblocking(False)
                self.write_sockets.append(self.socket)
                self.socket_addresses.append(self.server_ip)
                self.on_new_client(self.server_ip)
        # Server
        else:
            self.socket.setblocking(False)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.server_ip, self.server_port))
            self.socket.listen(self.abonents)

        self.read_sockets.append(self.socket)
        return True

    def loop(self):
        # Check client sockets
        if len(self.write_sockets): #and self.type == ExchangeProtocol.TCP_SERVER:
            for sock in self.write_sockets[:]:
                self.ping(sock)

        # Recv/Send packets
        r_list, w_list, e_list = select.select(self.read_sockets, self.write_sockets, self.read_sockets, 0.01)
        for sock in r_list:
            if sock is self.socket and self.type == ExchangeProtocol.TCP_SERVER:
                # Accept new connection
                client_socket, client_address = self.socket.accept()
                client_ip, client_port = client_address
                client_socket.setblocking(False)
                self.read_sockets.append(client_socket)
                self.write_sockets.append(client_socket)
                self.socket_addresses.append(client_ip)
                self.on_new_client(client_ip)
            else:
                data = sock.recv(4096)
                if data:
                    idx = self.write_sockets.index(sock)
                    self.on_recv(data, self.socket_addresses[idx])
        for sock in w_list:
            idx = self.write_sockets.index(sock)
            self.on_send(sock, self.socket_addresses[idx])

    def shutdown(self):
        for sock in self.write_sockets:
            sock.close()
        for sock in self.read_sockets:
            sock.close()

    def on_new_client(self, ip: str):
        raise NotImplementedError()

    def on_del_client(self, ip: str):
        raise NotImplementedError()

    def on_recv(self, data, ip_address):
        raise NotImplementedError()

    def on_send(self, sock, ip_address):
        raise NotImplementedError()

    def on_packet(self, data: list, event_code: int = 0, event_iter: int = 0, event_bits: int = 8):
        raise NotImplementedError()

    def pack_packet(self, data: list, event_code: int = 0, event_iter: int = 0, event_bits: int = 8, data_size: int  = 0) -> Bits:
        packet_size = self.PACKET_HEADER_SIZE + data_size
        packet = Bits(bytes(bytearray(packet_size)))

        packet.set_bits(0 * 8, 0xAA, 8)
        packet.set_bits(1 * 8, 0xCC, 8)
        packet.set_bits(2 * 8, event_code, 8)
        packet.set_bits(3 * 8, event_iter, 8)
        packet.set_bits(4 * 8, event_bits, 8)
        packet.set_bits(5 * 8, data_size, 16)
        packet.set_bits(7 * 8, 0, 16)

        if data_size:
            for idx, sample in enumerate(data):
                packet.set_bits(int((9 + idx * 2) * 8), sample, event_bits)

        crc16 = Bits.crc16_update(packet.get_barray(), packet_size)
        packet.set_bits(7 * 8, crc16, 16)
        return packet

    def ping(self, sock):
        packet = self.pack_packet(data = [], event_code = self.DISPATCHER_EVENT_PING, event_iter = 0, event_bits = 8, data_size = 0)
        try:
            sock.sendall(packet.get_barray())
        except socket.error as error:
            sock.close()
            idx = self.write_sockets.index(sock)
            self.on_del_client(self.socket_addresses[idx])
            self.write_sockets.remove(sock)
            self.read_sockets.remove(sock)
            del self.socket_addresses[idx]
            print("Error: ping: socket.sendall = {:d}, {:s}".format(error.errno, os.strerror(error.errno)))

    def send(self, sock, data: list, event_code: int = 0, event_iter: int = 0, event_bits: int = 8, data_size: int  = 0):
        packet = self.pack_packet(data = data, event_code = event_code, event_iter = event_iter, event_bits = event_bits, data_size = data_size)
        try:
            sock.send(packet.get_barray())
        except socket.error as error:
            print("Error: socket.send = {:d}, {:s}".format(error.errno, os.strerror(error.errno)))

    RECV_RESULT_NOT_FOUND       = 0
    RECV_RESULT_AWAITING_DATA   = 1
    RECV_RESULT_BAD_CRC16       = 2
    RECV_RESULT_FOUND           = 3

    def recv(self, data: bytearray):
        result = (self.RECV_RESULT_NOT_FOUND, 0)
        while 1:
            if data[0] != 0xAA:
                break
            if data[1] != 0xCC:
                break

            packet      = Bits(bytes(data))
            data_size   = packet.get_ubits(5 * 8, 16)
            if (len(data) - self.PACKET_HEADER_SIZE) < data_size:
                result = (self.RECV_RESULT_AWAITING_DATA, data_size)
                break

            packet_size = self.PACKET_HEADER_SIZE + data_size
            crc16       = packet.get_ubits(7 * 8, 16)

            data[7] = data[8] = 0
            if crc16 != Bits.crc16_update(data, packet_size):
                result = (self.RECV_RESULT_BAD_CRC16, data_size)
            else:
                event_code = packet.get_ubits(2 * 8, 8)
                event_iter = packet.get_ubits(3 * 8, 8)
                event_bits = packet.get_ubits(4 * 8, 8)
                data = []
                for idx in range(0, data_size, int(event_bits / 8)):
                    value = int(packet.get_ubits((self.PACKET_HEADER_SIZE + idx) * 8, event_bits))
                    data.append(value)
                self.on_packet( data = data, event_code = event_code, event_iter = event_iter, event_bits = event_bits)
                result = (self.RECV_RESULT_FOUND, data_size)
            break
        return result

class TCPDispatcher(QtCore.QThread, ExchangeProtocol):
    def __init__(self, parent, queues, bind_ip = "127.0.0.1", bind_port = 45000, type = ExchangeProtocol.TCP_CLIENT):
        super(TCPDispatcher, self).__init__(parent, config = parent.config, bind_ip = bind_ip, bind_port = bind_port, type = type)
        self.parent = parent
        self.thread_stop = False
        self.queues  = queues
        self.buffers = {}
        for ip_abonent in self.queues.keys():
            self.buffers[ip_abonent] = bytearray()

    def stop(self):
        self.thread_stop = True

    def run(self):
        threading.current_thread().name = QtCore.QThread.currentThread().objectName()
        # Waiting for conenction
        while self.setup() == False and self.thread_stop == False:
            time.sleep(1)
        while self.thread_stop == False:
            self.loop()
            time.sleep(0.01)
        # Close all sockets
        self.shutdown()

    def on_new_client(self, ip: str):
        self.on_packet(
            data        = [ ip ],
            event_code  = ExchangeProtocol.DISPATCHER_EVENT_NEW_CLIENT,
            event_iter  = 0,
            event_bits  = 8)

    def on_del_client(self, ip: str):
        self.on_packet(
            data        = [ ip ],
            event_code  = ExchangeProtocol.DISPATCHER_EVENT_DEL_CLIENT,
            event_iter  = 0,
            event_bits  = 8)

    def on_recv(self, data, ip_address):
        self.buffers[ip_address] += bytearray(data)
        while len(self.buffers[ip_address]) >= ExchangeProtocol.PACKET_HEADER_SIZE:
            awaiting_data = False
            for offset in range(0, len(self.buffers[ip_address])):

                result, data_size = self.recv(self.buffers[ip_address][offset:])
                if result == self.RECV_RESULT_FOUND:
                    del self.buffers[ip_address][offset:offset + ExchangeProtocol.PACKET_HEADER_SIZE + data_size]
                    break
                if result == self.RECV_RESULT_BAD_CRC16:
                    del self.buffers[ip_address][offset:offset + ExchangeProtocol.PACKET_HEADER_SIZE + data_size]
                    break
                if result == self.RECV_RESULT_AWAITING_DATA:
                    awaiting_data = True
                    break
                if result == self.RECV_RESULT_NOT_FOUND:
                    self.buffers[ip_address] = self.buffers[ip_address][1:]
                    break
            if awaiting_data:
                break

    def on_send(self, sock, ip_address):
        try:
            payload = None
            if ip_address in self.queues:
                payload = self.queues[ip_address].get_nowait()
        except queue.Empty:
            # print("Error: queue = nothing to send")
            pass
        else:
            if payload:
                event_code, event_iter, event_bits, data_size, data = payload
                self.send(sock, data=data, event_code=event_code, event_iter=event_iter, event_bits=event_bits, data_size=data_size)

    def on_packet(self, data: list, event_code: int = 0, event_iter: int = 0, event_bits: int = 8):
        QtWidgets.QApplication.postEvent(self.parent, TCPDispatcherEvent(
            data        = data[:],
            event_code  = event_code,
            event_iter  = event_iter,
            event_bits  = event_bits))