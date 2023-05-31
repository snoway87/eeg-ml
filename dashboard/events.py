import time
from PyQt5 import QtCore



class UDPDispatcherEvent(QtCore.QEvent):
    EVENT_TYPE = QtCore.QEvent.Type(QtCore.QEvent.registerEventType())
    def __init__(self, adc_values: list, lost_packets: int):
        QtCore.QEvent.__init__(self, UDPDispatcherEvent.EVENT_TYPE)
        self.time          = round(time.time() * 1000)
        self.adc_values     = adc_values
        self.lost_packets   = lost_packets


class TCPDispatcherEvent(QtCore.QEvent):
    EVENT_TYPE = QtCore.QEvent.Type(QtCore.QEvent.registerEventType())
    def __init__(self, data: list, event_code: int = 0, event_iter: int = 0, event_bits: int = 8, data_size: int = 0):
        QtCore.QEvent.__init__(self, TCPDispatcherEvent.EVENT_TYPE)
        self.time       = round(time.time() * 1000)
        self.code       = event_code
        self.iter       = event_iter
        self.bits       = event_bits
        self.data       = data


class RecorderEvent(QtCore.QEvent):
    EVENT_TYPE = QtCore.QEvent.Type(QtCore.QEvent.registerEventType())
    def __init__(self, queue_size):
        QtCore.QEvent.__init__(self, RecorderEvent.EVENT_TYPE)
        self.time  = round(time.time() * 1000)
        self.queue_size  = queue_size