import math
import types
import numpy as np
import pyqtgraph as pg
from events import *
from dispatchers import *
from PyQt5 import QtCore, QtWidgets

# import matplotlib
# from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
# from matplotlib.figure import Figure
# from matplotlib import rc as plt_rc

class ADCChannel(pg.PlotWidget):
    updatedData  = QtCore.pyqtSignal(int, object)
    updatedEvent = QtCore.pyqtSignal(int, int, int, object)

    def __init__(self, parent=None):
        super(ADCChannel, self).__init__(parent)
        self.dashboard = self.parent().parent().parent()
        self.config = self.dashboard.config

        self.setBackground('w')
        self.setYRange(-1, 5.5, padding=0)
        self.showGrid(x=True, y=True)
        self.addLegend(
            brush=pg.mkBrush(255, 255, 255, 100),
            labelTextSize='10pt',
            labelTextColor='black')

        # Default sets
        self.present_signal     = 0 # 0 - Raw, 1 - Filtered
        self.id                 = -1
        self.delay_iter         = 0
        self.sampling_rate      = int(self.config['adc']['sampling_rate'])
        self.sampling_time      = int(self.config['dataset']['sampling_time'])
        self.batch_delay        = int(self.config['dataset']['batch_delay'])
        self.batch_samples      = int(self.config['dataset']['batch_samples'])
        self.update_delay       = int(self.config['dataset']['update_delay'])
        self.batch_delay        = int(self.update_delay / self.batch_delay)

        # Default data
        self.f_data             = [0] * self.sampling_rate * self.sampling_time
        self.y_data             = [0] * self.sampling_rate * self.sampling_time
        self.x_data             = [i / self.sampling_rate for i in range(0, int(self.sampling_time * self.sampling_rate))]
        self.e_data             = []
        self.events = {
            ExchangeProtocol.GAME_EVENT_UP      : 'U',
            ExchangeProtocol.GAME_EVENT_DOWN    : 'D',
            ExchangeProtocol.GAME_EVENT_LEFT    : 'L',
            ExchangeProtocol.GAME_EVENT_RIGHT   : 'R'
        }
        # IIR filter, Butterworth 10-order
        self.iir_al = 10
        self.iir_bl = 11
        self.iir_buffer = []
        self.iir_polynoms = {
            60: {
                'b' : [3.114845493979219e-11, 3.114845493979219e-10, 1.4016804722906485e-09, 3.737814592775063e-09, 6.54117553735636e-09, 7.849410644827632e-09, 6.54117553735636e-09, 3.737814592775063e-09, 1.4016804722906485e-09, 3.114845493979219e-10, 3.114845493979219e-11],
                'a' : [-8.795170347593166, 34.87498281940547, -82.09589684558945, 127.04294385875566, -135.03554288399235, 99.83507904006187, -50.6918184336482, 16.916722791727487, -3.3503054451435945, 0.29900547791228027]
            },
            100: {
                'b' : [3.6196950776160545e-09, 3.619695077616054e-08, 1.6288627849272245e-07, 4.3436340931392657e-07, 7.601359662993715e-07, 9.121631595592458e-07, 7.601359662993715e-07, 4.3436340931392657e-07, 1.6288627849272245e-07, 3.619695077616054e-08, 3.6196950776160545e-09],
                'a' : [-7.99229666239913, 28.912194584176586, -62.315352281547256, 88.58766325126386, -86.76706804056137, 59.28095157409917, -27.89029917249328, 8.64568213752646, -1.594239767690205, 0.13276808419292055]
            },
            160: {
                'b' : [2.44156580e-07, 2.44156580e-06, 1.09870461e-05, 2.92987896e-05, 5.12728818e-05, 6.15274581e-05, 5.12728818e-05, 2.92987896e-05, 1.09870461e-05, 2.44156580e-06, 2.44156580e-07],
                'a' : [-6.78896079e+00, 2.11186057e+01, -3.95466389e+01, 4.92807282e+01, -4.26412048e+01, 2.59155697e+01, -1.09133701e+01, 3.04505316e+00, -5.07983531e-01, 3.84514437e-02]
            },
            200: {
                'b' : [1.683581407232949e-06, 1.683581407232949e-05, 7.57611633254827e-05, 0.00020202976886795387, 0.0003535520955189193, 0.00042426251462270313, 0.0003535520955189193, 0.00020202976886795387, 7.57611633254827e-05, 1.683581407232949e-05, 1.683581407232949e-06],
                'a' : [-5.987589629816667, 16.672193323002656, -28.25878790020053, 32.15975648769458, -25.601749597053352, 14.405687426207791, -5.647074344132482, 1.473727936973908, -0.23091934586202878, 0.01647963054713087]
            }
        }
        # Draw dataset plot
        self.plt_raw = self.plot(self.x_data, self.y_data, pen=pg.mkPen(color=(255, 0, 0)), name='raw')
        self.plt_filtered = self.plot(self.x_data, self.f_data, pen=pg.mkPen(color=(0, 255, 0)), name='filtered')


    def set_id(self, id):
        self.id = id

    def set_title(self, title):
        styles = {'color':'blue', 'font-size':'10px' }
        self.setLabel('left', title + ' (V)', **styles)

    def iir_filter(self, fcut: int, x: list):
        y = self.f_data[-self.iir_al:]
        y.reverse()
        #b0 * xN + ... + bN * x0
        bcc = sum((b * x[idx]) for idx, b in enumerate(self.iir_polynoms[fcut]['b']))
        #a1 * y(N-1) + ... + aN * y0
        acc = sum((a * y[idx]) for idx, a in enumerate(self.iir_polynoms[fcut]['a']))
        self.f_data = self.f_data[1:]
        self.f_data.append(bcc - acc)

    def update_event(self, event_code: int, sample_iter: int):
        arrow = pg.ArrowItem(angle = 90)
        text  = pg.TextItem(self.events.get(event_code, 'X'), (0, 0, 255))
        arrow.setPos(self.sampling_time, 0)
        text.setPos(self.sampling_time, 0)

        self.e_data.append({
            'code'      : event_code,
            'arrow'     : arrow,
            'text'      : text,
            'x_offset'  : self.sampling_time * self.sampling_rate - 1
        })
        self.addItem(self.e_data[-1]['arrow'])
        self.addItem(self.e_data[-1]['text'])
        self.updatedEvent.emit(self.id, self.e_data[-1]['code'], sample_iter, (i for i in self.y_data[:]))

    def update_lost_packets(self, lost_packets: int):
        lost_samples = lost_packets * self.batch_samples
        if lost_samples > 0:
            lost_samples = lost_samples if lost_samples <= len(self.y_data) else len(self.y_data)
            default_value = float(self.config['adc']['vref'])
            self.y_data = self.y_data[lost_samples:]
            self.y_data = self.y_data + [default_value] * lost_samples
            # Move event's coords
            for event in self.e_data:
                event['x_offset'] -= lost_samples
            self.draw_plot()

    def update_data(self, fcut:int, points: list):
        # Add new point
        offset = len(points)
        self.y_data = self.y_data[offset:]
        self.y_data = self.y_data + points
        # Move event's coords
        for event in self.e_data:
            event['x_offset'] -= offset
        # IIR filter
        self.iir_buffer += points
        for i in range(len(self.iir_buffer)):
            x = self.iir_buffer[i:i + self.iir_bl]
            if len(x) < self.iir_bl:
                self.iir_buffer = self.iir_buffer[i:]
                break
            self.iir_filter(fcut, x)

        # Draw plots
        self.draw_plot()

    def draw_plot(self):
        # Update plot every self.batch_delay
        self.delay_iter = (self.delay_iter + 1) % self.batch_delay
        if self.delay_iter == 0:
            # Draw plot
            if self.present_signal == 0:
                self.plt_raw.setData(self.x_data, self.y_data)
            else:
                self.plt_filtered.setData(self.x_data, self.f_data)
            # Draw events
            for idx, event in enumerate(self.e_data[:]):
                if event['x_offset'] <= 0:
                    self.removeItem(event['arrow'])
                    self.removeItem(event['text'])
                    self.e_data.remove(event)
                else:
                    pos_x = self.x_data[event['x_offset']]
                    event['arrow'].setPos(pos_x, 0)
                    event['text'].setPos(pos_x, 0)

            if self.present_signal == 0:
                self.updatedData.emit(self.id, (i for i in self.y_data))
            else:
                self.updatedData.emit(self.id, (i for i in self.f_data))

    def on_change_present_signal(self, value):
        self.present_signal = int(value)
        if self.present_signal == 0:
            self.plt_filtered.clear()
        else:
            self.plt_raw.clear()





class Spectrum(pg.PlotWidget):
    def __init__(self, parent=None):
        super(Spectrum, self).__init__(parent)
        self.dashboard = self.parent().parent().parent()
        self.config = self.dashboard.config

        self.setBackground('w')
        self.showGrid(x=True, y=True)

        styles = {'color':'blue', 'font-size':'10px' }
        self.setLabel('left', "Power", **styles)
        self.setLabel('bottom', "Freq (Hz)", **styles)

        # Default sets
        self.sampling_rate = int(self.config['adc']['sampling_rate'])
        self.sampling_time = int(self.config['dataset']['sampling_time'])
        self.plt_amplitude = self.plot([], [], pen=pg.mkPen(color=(0, 0, 255)))
        self.plt_phase = self.plot([], [], pen=pg.mkPen(color=(0, 0, 0)))

    def set_title(self, title):
        self.setTitle("Frequency domain: " + title, color="black", size="12pt")

    def update_data(self, data):
        N = self.sampling_rate * self.sampling_time

        x = np.fft.rfftfreq(N, 1 / self.sampling_rate)
        y = np.fft.rfft(data)[1:]                       # Skip DC(freq = 0) -> [1:]
        power = 1/N * np.abs(y)
        # phase = np.angle(y)

        self.plt_amplitude.setData(x[1:501], power[:500])
        # self.plt_phase.setData(x[1:501], phase[:500])

        # Old...
        # N = self.sampling_rate * 1
        # power = 1/N * np.abs(np.fft.rfft(data[-N:]))
        # freqs = np.fft.rfftfreq(N,1./self.sampling_rate)
        # self.plt_raw.setData(freqs[:250], power[:250])



# plt_rc('font', size=6)
# plt_rc('lines', linewidth=0.5)
# class TrainingFigure(FigureCanvas):
#     def __init__(self, parent):
#         figure = Figure(figsize=(4, 4))
#         FigureCanvas.__init__(self, figure)
#         self.setParent(parent)

#         self.ax = figure.add_subplot(1, 1, 1)
#         self.ax.set_xlabel("Batches", fontdict={'fontsize' : 8})
#         self.ax.set_ylabel("Accuracy (%)", fontdict={'fontsize' : 8})
#         self.ax.grid(color="#d3d3d3")
#         self.ax.set_xlim([0, 1000])
#         self.ax.set_ylim([0, 100])
#         self.ax.set_title("CNN Train/Test")
#         self.plot = self.ax.plot([1,2], [1,2],'b')
#         self.plot = self.plot[0]