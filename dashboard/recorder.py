
import os
import sys
import queue
import wave
import time
import struct
import threading

from events import *
from dispatchers import *
from PyQt5 import QtCore

class Recorder(QtCore.QThread):
    def __init__(self, parent=None, queue=None):
        super(Recorder, self).__init__(parent=parent)
        self.parent = parent
        self.config = parent.config
        self.queue = queue

        self.adc_range = self.config['adc']['range']
        self.adc_power = 2 ** int(self.config['adc']['resolution'])

        self.thread_stop = False
        self.wave_file = None
        self.event_file = None

    def start_session(self):
        tm = str(int(time.time()))
        wave_file = self.parent.config['dataset']['dest_path'] + '/' + tm + '.wav'
        event_file = self.parent.config['dataset']['dest_path'] + '/' + tm + '.txt'
        try:
            self.wave_file  = wave.open(wave_file, 'w')
            self.event_file = open(event_file, 'w')

            self.wave_file.setnchannels(int(self.config['adc']['channels']))        # channels
            self.wave_file.setsampwidth(int(self.config['adc']['resolution'] / 8))  # 16 bit
            self.wave_file.setframerate(int(self.config['adc']['sampling_rate']))   # framerate = sampling rate = 2000Hz
        except wave.Error:
            print("Error: Recorder: WAV file: " + wave_file)
        except Exception as err:
            print("Error: Recorder:", err)
        else:
            self.start(priority=QtCore.QThread.LowestPriority)

    def stop(self):
        self.thread_stop = True

    def run(self):
        threading.current_thread().name = QtCore.QThread.currentThread().objectName()
        events = {
            ExchangeProtocol.GAME_EVENT_UP      : 'U',
            ExchangeProtocol.GAME_EVENT_DOWN    : 'D',
            ExchangeProtocol.GAME_EVENT_LEFT    : 'L',
            ExchangeProtocol.GAME_EVENT_RIGHT   : 'R'
        }

        current = {}
        while not self.thread_stop:
            try:
                channel_id, event_id, iter, data = self.queue.get_nowait()
            except queue.Empty:
                time.sleep(1)
            else:
                if not iter in current:
                    current[iter] = {
                        'event_id'   : events.get(event_id, 'X'),
                        'adc_values' : [0] * int(self.config['adc']['channels']) }

                # Convert voltage to ADC value (16 bit). AD7606!!!
                current[iter]['adc_values'][channel_id] = [int(((volt - self.adc_range / 2) * self.adc_power) / self.adc_range) for volt in data]

                for key in sorted(current):
                    if all([type(x) is list for x in current[key]['adc_values']]):
                        for samples in zip(*current[key]['adc_values']):
                            for sample in samples:
                                self.wave_file.writeframes(struct.pack('<h', sample))
                        self.event_file.write(current[key]['event_id'])
                        current.pop(key)
                        QtWidgets.QApplication.postEvent(self.parent, RecorderEvent(self.queue.qsize()))

        self.wave_file.close()
        self.event_file.close()