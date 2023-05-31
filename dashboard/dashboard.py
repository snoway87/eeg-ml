import os
import sys
import queue
import json
import time
import numpy as np
import dashboard_window
from events import *
from dispatchers import *
from recorder import *
from PyQt5 import QtCore, QtWidgets



class DashboardWindow(QtWidgets.QMainWindow, dashboard_window.Ui_DashboardWindow):
    # AD7606 direction
    ADC_CHANNEL_FCZ_CPZ = 2
    ADC_CHANNEL_FP1_F7  = 3
    ADC_CHANNEL_FP2_F8  = 1
    ADC_CHANNEL_F3_C3   = 4
    ADC_CHANNEL_F4_C4   = 0

    def __init__(self, config, *args, **kwargs):
        super(DashboardWindow, self).__init__(*args, **kwargs)
        self.config = config

        self.setupUi(self)
        self.adc_channels = {
            self.ADC_CHANNEL_FCZ_CPZ    : self.widget_fcz_cpz,
            self.ADC_CHANNEL_FP1_F7     : self.widget_fp1_f7,
            self.ADC_CHANNEL_FP2_F8     : self.widget_fp2_f8,
            self.ADC_CHANNEL_F3_C3      : self.widget_f3_c3,
            self.ADC_CHANNEL_F4_C4      : self.widget_f4_c4
        }

        for idx_ch, widget_ch in self.adc_channels.items():
            widget_ch.set_id(idx_ch)
            widget_ch.set_title(self.adc_channel.itemText(idx_ch))
            widget_ch.updatedData.connect(self.on_adc_channel_data_updated)
            widget_ch.updatedEvent.connect(self.on_adc_channel_event_updated)
            self.present_signal.currentIndexChanged.connect(widget_ch.on_change_present_signal)

        self.widget_spectrum.set_title(self.adc_channel.currentText())
        self.game_start_btn.clicked.connect(self.on_start_pressed)
        self.game_disable_btn.clicked.connect(self.on_disable_pressed)
        self.adc_channel.currentTextChanged.connect(self.on_adc_channel_changed)

        self.lost_packet_time = int((int(self.config['adc']['sampling_rate']) * int(self.config['dataset']['sampling_time'])) / int(self.config['dataset']['batch_samples']))
        self.lost_packet_iter = 0
        self.sample_iter = 0
        self.recorder = None
        self.recorder_queue = None
        self.abonent_queues = {}
        for abonent in self.config['network']['tcp_dispatcher']['abonents']:
            abonent_ip = str(abonent['ip'])
            self.abonent_queues[abonent_ip] = queue.Queue()

        self.udp_dispatcher = UDPDispatcher(self)
        self.tcp_dispatcher = TCPDispatcher(self, queues = self.abonent_queues, type = ExchangeProtocol.TCP_SERVER)
        self.tcp_dispatcher.setObjectName('TCPDispatcherThread')
        self.udp_dispatcher.setObjectName('UDPDispatcherThread')
        self.tcp_dispatcher.start()
        self.udp_dispatcher.start()


    #
    # Recorder methods
    # --------------------------------------------------------------
    def start_recorder(self):
        self.recorder_queue = queue.Queue()
        self.recorder = Recorder(self, queue=self.recorder_queue)
        self.recorder.setObjectName('RecorderThread')
        self.recorder.start_session()

    def stop_recorder(self):
        if self.recorder:
            self.recorder_queue = None
            self.recorder.stop()
            self.recorder.wait()

    def record(self, channel_id: int, event_id: int, iter: int, data: list):
        if self.recorder_queue:
            self.recorder_queue.put((channel_id, event_id, iter, data))


    #
    # Thread sending
    # --------------------------------------------------------------
    def send_event(self, abonent_name: str, event_code: int, event_iter: int, event_bits: int, data_size: int, data: list ):
        for abonent in self.config['network']['tcp_dispatcher']['abonents']:
            if str(abonent['name']).lower() == abonent_name:
                abonent_ip = str(abonent['ip'])
                self.abonent_queues[abonent_ip].put((event_code, event_iter, event_bits, data_size, data))
                return


    #
    # Thread events
    # --------------------------------------------------------------
    def customEvent(self, event):
        if event.EVENT_TYPE == UDPDispatcherEvent.EVENT_TYPE:
            # Update lost packets
            lost_packets = int(self.lost_packets.text())
            if lost_packets == 0:
                self.lost_packet_iter = 0
            lost_packets += event.lost_packets
            self.lost_packets.setText(str(lost_packets))
            for idx_ch, widget_ch in self.adc_channels.items():
                widget_ch.update_lost_packets(event.lost_packets)
            # Update ADC values
            fcut = int(self.iir_cutoff.currentText())
            for idx_ch, widget_ch in self.adc_channels.items():
                widget_ch.update_data(fcut, event.adc_values[idx_ch])
            # Reset lost_packets counter
            self.lost_packet_iter = (self.lost_packet_iter + 1) % self.lost_packet_time
            if self.lost_packet_iter == 0:
                self.lost_packets.setText('0')


        if event.EVENT_TYPE == TCPDispatcherEvent.EVENT_TYPE:
            if event.code == ExchangeProtocol.DISPATCHER_EVENT_NEW_CLIENT or \
               event.code == ExchangeProtocol.DISPATCHER_EVENT_DEL_CLIENT:
                ip_address = str(event.data[0])
                for abonent in self.config['network']['tcp_dispatcher']['abonents']:
                    if ip_address == str(abonent['ip']) and str(abonent['name']).lower() == 'game':
                        self.game_ip_client.setText(ip_address if event.code == ExchangeProtocol.DISPATCHER_EVENT_NEW_CLIENT else '-')
                        self.game_start_btn.setEnabled(True if event.code == ExchangeProtocol.DISPATCHER_EVENT_NEW_CLIENT else False)
                    if ip_address == str(abonent['ip']) and str(abonent['name']).lower() == 'net':
                        pass

            # if event.code == ExchangeProtocol.GAME_EVENT_GAMEOVER:
            #     msg = QtWidgets.QMessageBox()
            #     msg.setIcon(QtWidgets.QMessageBox.Information)
            #     msg.setWindowTitle("Game Over!")
            #     msg.setInformativeText('No more space left for the new cell')
            #     msg.exec_()

            if event.code == ExchangeProtocol.GAME_EVENT_UP   or \
               event.code == ExchangeProtocol.GAME_EVENT_DOWN or \
               event.code == ExchangeProtocol.GAME_EVENT_LEFT or \
               event.code == ExchangeProtocol.GAME_EVENT_RIGHT:
                if event.data[0]:
                    self.game_score.setText(str(event.data[0]))
                for idx_ch, widget_ch in self.adc_channels.items():
                    widget_ch.update_event(event.code, self.sample_iter)
                self.sample_iter = (self.sample_iter + 1) % 32

        if event.EVENT_TYPE == RecorderEvent.EVENT_TYPE:
            queue_size = event.queue_size
            if event.queue_size:
                self.game_start_btn.setEnabled(False)
                self.game_start_btn.setText("Awaiting for stop recroder... (" + str(event.queue_size) + ")")
            else:
                self.game_start_btn.setEnabled(True)
                self.game_start_btn.setText("Stop")

    #
    # UI Events
    # --------------------------------------------------------------
    def closeEvent(self, event):
        self.udp_dispatcher.stop()
        self.tcp_dispatcher.stop()
        self.udp_dispatcher.wait()
        self.tcp_dispatcher.wait()
        self.stop_recorder()
        return super().closeEvent(event)

    def on_start_pressed(self):
        if self.game_start_btn.text() == "Start":
            if self.record_wav.isChecked():
                self.start_recorder()
            lock_delay = int(self.game_lock_delay.currentText())
            self.send_event('game', ExchangeProtocol.GAME_EVENT_START, 0, 8, 1, [lock_delay])
            self.game_lock_delay.setEnabled(False)
            self.game_disable_btn.setEnabled(True)
            self.game_start_btn.setText("Stop")

        elif self.game_start_btn.text() == "Stop":
            self.send_event('game', ExchangeProtocol.GAME_EVENT_STOP, 0, 8, 0, [])
            self.game_score.setText('0')
            self.game_lock_delay.setEnabled(True)
            self.game_disable_btn.setEnabled(False)
            self.game_start_btn.setText("Start")
            if self.record_wav.isChecked():
                self.stop_recorder()

    def on_disable_pressed(self):
        pass

    def on_adc_channel_data_updated(self, channel_id: int, data: object):
        if channel_id == self.adc_channel.currentIndex():
            ch = self.adc_channels.get(channel_id, None)
            if ch:
                self.widget_spectrum.update_data(list(data))

    def on_adc_channel_event_updated(self, channel_id: int, event_id: int, iter: int, data: object):
        if self.record_wav.isChecked():
            self.record(channel_id=channel_id, event_id=event_id, iter=iter, data=list(data))

    def on_adc_channel_changed(self, value):
        self.widget_spectrum.set_title(str(value))


if __name__ == '__main__':
    with open('config.json', 'r') as config:
        config = json.loads(config.read())


    assert config['adc']['sampling_rate']
    assert config['adc']['resolution']
    assert config['adc']['channels']
    assert config['adc']['range']
    assert config['adc']['vref']

    assert config['dataset']['sampling_time']
    assert config['dataset']['update_delay']
    assert config['dataset']['batch_delay']
    assert config['dataset']['batch_samples']
    assert config['dataset']['dest_path']

    assert config['network']['tcp_dispatcher']['server_ip']
    assert config['network']['tcp_dispatcher']['server_port']
    assert config['network']['tcp_dispatcher']['abonents']
    assert type(config['network']['tcp_dispatcher']['abonents']) is list
    for abonent in config['network']['tcp_dispatcher']['abonents']:
        assert 'name' in abonent
        assert 'ip' in abonent
        assert 'port' in abonent


    app = QtWidgets.QApplication(sys.argv)
    dashboard = DashboardWindow(config = config)
    dashboard.show()
    sys.exit(app.exec_())


