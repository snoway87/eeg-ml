import sys
import queue
import json
import time
from events import *
from dispatchers import *
from random import choice, choices
from PyQt5 import QtWidgets, QtCore, QtGui

class GameWindow(QtWidgets.QMainWindow):
    def __init__(self, config, *args, **kwargs):
        super(GameWindow, self).__init__(*args, **kwargs)

        self.config = config
        self.start_dispatcher()

        self.setWindowTitle('EEG. 2048 Game')
        widget = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout()
        # Net status label
        self.netStatus = QtWidgets.QLabel()
        self.netStatus.setAlignment(QtCore.Qt.AlignCenter)
        self.netStatus.setStyleSheet('QLabel{font-size: 12pt; background-color: red}')
        self.netStatus.setFixedSize(100,20)
        self.netStatus.setText('Disconnect')
        # Game score label
        self.gameScore = QtWidgets.QLabel()
        self.gameScore.setStyleSheet('QLabel{font-size: 18pt}')
        self.gameScore.setFixedSize(100,20)
        self.gameScore.setAlignment(QtCore.Qt.AlignLeft)
        self.gameScore.setText('Score: 0')
        # Game timer label
        self.gameTimer = QtWidgets.QLabel()
        self.gameTimer.setStyleSheet('QLabel{font-size: 18pt}')
        self.gameTimer.setFixedSize(100,20)
        self.gameTimer.setAlignment(QtCore.Qt.AlignLeft)
        self.gameTimer.setText('00:00')
        # Game lock label
        self.gameLock = QtWidgets.QLabel()
        self.gameLock.setStyleSheet('QLabel{font-size: 18pt}')
        self.gameLock.setFixedSize(100,20)
        self.gameLock.setAlignment(QtCore.Qt.AlignLeft)
        self.gameLock.setText('Lock: 0')

        vbox.addWidget(self.netStatus)
        vbox.addWidget(self.gameTimer)
        vbox.addWidget(self.gameLock)
        vbox.addWidget(self.gameScore)

        self.game = Game(self)
        hbox = QtWidgets.QHBoxLayout()
        hbox.addLayout(vbox)
        hbox.addWidget(self.game)
        widget.setLayout(hbox)
        self.setCentralWidget(widget)

    def stop_dispatcher(self):
        self.dispatcher.stop()
        self.dispatcher.wait()

    def start_dispatcher(self):
        self.dispatcher_queues = { self.config['network']['tcp_dispatcher']['server_ip'] : queue.Queue() }
        self.dispatcher = TCPDispatcher(self,
            queues      = self.dispatcher_queues,
            bind_ip     = str(self.config['network']['tcp_dispatcher']['abonent']['ip']),
            bind_port   = int(self.config['network']['tcp_dispatcher']['abonent']['port']))
        self.dispatcher.start()

    def customEvent(self, event):
        if event.EVENT_TYPE == TCPDispatcherEvent.EVENT_TYPE:
            if event.code == ExchangeProtocol.DISPATCHER_EVENT_NEW_CLIENT:
                self.netStatus.setStyleSheet('QLabel{background-color: green}')
                self.netStatus.setText('Connected')
            if event.code == ExchangeProtocol.DISPATCHER_EVENT_DEL_CLIENT:
                self.netStatus.setStyleSheet('QLabel{background-color: red}')
                self.netStatus.setText('Disconnected')
                self.game.stop()
                self.stop_dispatcher()
                self.start_dispatcher()

            if event.code == ExchangeProtocol.GAME_EVENT_START:
                self.game.start(int(event.data[0]))
            if event.code == ExchangeProtocol.GAME_EVENT_STOP:
                self.game.stop()

    def closeEvent(self, event):
        self.game.stop()
        self.stop_dispatcher()
        return super().closeEvent(event)

class Game(QtWidgets.QFrame):
    WIDGET_W = 385
    WIDGET_H = 385

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.setStyleSheet('background-color: #B2BABB;')
        self.setFixedSize(self.WIDGET_W, self.WIDGET_H)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)


        self.default_sets()
        self.timer = QtCore.QTimer()
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.timerEvent)
        # self.start()

    def start(self, lock_delay=0):
        self.default_sets()
        self.new_cell()
        self.new_cell()
        self.update()
        self.timer.start()

    def default_sets(self):
        self.time = 0
        self.score = 0
        self.old_field = []
        self.new_field = []
        for i in range(4):
            self.old_field.append([0] * 4)
            self.new_field.append([0] * 4)
        # self.new_field = [
        #     [32, 64, 128, 512],
        #     [2, 4, 8, 16],
        #     [0, 0, 2048, 1024],
        #     [64, 0, 0, 0]
        # ]

    def stop(self):
        self.timer.stop()
        self.default_sets()
        self.parent.gameTimer.setText('00:00')
        self.update()

    def update_score(self, value):
        self.score += value
        self.parent.gameScore.setText('Score: ' + str(self.score))

    def new_cell(self):
        free_cells = self.get_free_cells()
        if len(free_cells):
            # Game rules: 2 - 90%, 4 - 10%
            value = choices([2, 4], weights=[90, 10])[0]
            coords = choice(free_cells)
            self.new_field[coords[0]][coords[1]] = value

    def get_free_cells(self) -> list:
        cells = []
        for i, row in enumerate(self.new_field):
            for j, elem in enumerate(row):
                if not elem:
                    cells.append((i, j))
        return cells

    def shift_cells(self) -> bool:
        field = []
        changed = False
        for i, row in enumerate(self.new_field):
            offset = 0
            field.append([0] * 4)
            for j, cell in enumerate(row):
                if cell:
                    field[i][offset] = cell
                    if j != offset:
                        changed = True
                    offset += 1
        self.new_field = field
        return changed

    def merge_cells(self) -> bool:
        changed = False
        for i, row in enumerate(self.new_field):
            for j, cell in enumerate(row):
                if j == 3:
                    break
                if cell and cell == row[j + 1]:
                    self.new_field[i][j] = cell * 2
                    self.new_field[i][j + 1] = 0
                    self.update_score(self.new_field[i][j])
                    changed = True
        return changed

    def reverse_cells(self):
        field = []
        for i, row in enumerate(self.new_field):
            field.append([])
            for j, cell in enumerate(row):
                field[i].append(row[3 - j])
        self.new_field = field

    def transpose_cells(self):
        field = []
        for i, row in enumerate(self.new_field):
            field.append([])
            for j, cell in enumerate(row):
                field[i].append(self.new_field[j][i])
        self.new_field = field

    def get_cell_styles(self, cell_value: int) -> tuple:
        styles = {
            2    : (QtGui.QColor(213, 219, 219), QtGui.QColor(77, 86, 86)),
            4    : (QtGui.QColor(202, 207, 210), QtGui.QColor(77, 86, 86)),
            8    : (QtGui.QColor(184, 134, 11), QtGui.QColor(255, 255, 255)),
            16   : (QtGui.QColor(205, 133, 63), QtGui.QColor(255, 255, 255)),
            32   : (QtGui.QColor(210, 105, 30), QtGui.QColor(255, 255, 255)),
            64   : (QtGui.QColor(139, 69, 19), QtGui.QColor(255, 255, 255)),
            128  : (QtGui.QColor(160, 82, 45), QtGui.QColor(255, 255, 255)),
            512  : (QtGui.QColor(165, 42, 42), QtGui.QColor(255, 255, 255)),
        }
        style = styles.get(cell_value,(QtGui.QColor(128, 0, 0), QtGui.QColor(255, 255, 255)))
        if cell_value > 512:
            style += (QtGui.QFont('Helvetica', 32),)
        else:
            style += (QtGui.QFont('Helvetica', 48),)
        return style

    def move_left(self) -> bool:
        res1 = self.shift_cells()
        res2 = self.merge_cells()
        changed = res1 or res2
        self.shift_cells()
        return changed

    def move_right(self) -> bool:
        self.reverse_cells()
        changed = self.move_left()
        self.reverse_cells()
        return changed

    def move_up(self) -> bool:
        self.transpose_cells()
        changed = self.move_left()
        self.transpose_cells()
        return changed

    def move_down(self) -> bool:
        self.transpose_cells()
        changed = self.move_right()
        self.transpose_cells()
        return changed


    def send_event(self, event_code: int, game_score: int):
        server_ip = self.parent.config['network']['tcp_dispatcher']['server_ip']
        self.parent.dispatcher_queues[server_ip].put(
            (event_code, 0, 32, 4, [game_score]))

    def keyPressEvent(self, event):
        if not self.timer.isActive():
            return

        key = event.key()
        send_event = None
        changed = False
        if key == QtCore.Qt.Key_Left:
            changed = self.move_left()
            send_event = ExchangeProtocol.GAME_EVENT_LEFT
        elif key == QtCore.Qt.Key_Right:
            changed = self.move_right()
            send_event = ExchangeProtocol.GAME_EVENT_RIGHT
        elif key == QtCore.Qt.Key_Up:
            changed = self.move_up()
            send_event = ExchangeProtocol.GAME_EVENT_UP
        elif key == QtCore.Qt.Key_Down:
            changed = self.move_down()
            send_event = ExchangeProtocol.GAME_EVENT_DOWN

        if send_event:
            score = self.score if changed else 0
            self.send_event(send_event, score)

        if changed:
            self.new_cell()
            self.update()


    def paintEvent(self, event):
        qp = QtGui.QPainter(self)
        pen = QtGui.QPen(QtCore.Qt.black, 1, QtCore.Qt.SolidLine)
        qp.setPen(pen)
        # Top line
        qp.drawLine(0, 0, self.WIDGET_W, 0)
        # Left line
        qp.drawLine(0, 0, 0, self.WIDGET_H)
        # Right line
        qp.drawLine(self.WIDGET_W, 0, self.WIDGET_W, self.WIDGET_H)
        # Bottom line
        qp.drawLine(0, self.WIDGET_H, self.WIDGET_W, self.WIDGET_H)

        # Draw field (360x360)
        borderMargin = 5
        for i in range(4):
            for j in range(4):
                x = borderMargin + j * 90 + j * borderMargin
                y = borderMargin + i * 90 + i * borderMargin
                w = 90
                h = 90
                color = QtGui.QColor(112, 123, 124)
                pen = QtGui.QPen(color, 1, QtCore.Qt.SolidLine)
                qp.setBrush(color)
                qp.setPen(pen)
                qp.drawRect(x, y, w, h)


        for i, row in enumerate(self.new_field):
            for j, cell in enumerate(row):
                x = borderMargin + j * 90 + j * borderMargin
                y = borderMargin + i * 90 + i * borderMargin
                w = h = 90

                if cell:
                    bg_color, txt_color, txt_font = self.get_cell_styles(cell)
                    # Draw cell
                    pen = QtGui.QPen(bg_color, 1, QtCore.Qt.SolidLine)
                    qp.setPen(pen)
                    qp.setBrush(bg_color)
                    qp.drawRect(x, y, w, h)
                    # Draw Text
                    flags = QtCore.Qt.AlignVCenter|QtCore.Qt.AlignHCenter|QtCore.Qt.TextSingleLine
                    qp.setPen(txt_color)
                    qp.setFont(txt_font)
                    qp.drawText(x, y, w, h, flags, str(cell))

        return super().paintEvent(event)

    def timerEvent(self):
        self.time += 1
        min = self.time // 60
        sec = self.time % 60
        min = str(min) if min >= 10 else "0" + str(min)
        sec = str(sec) if sec >= 10 else "0" + str(sec)
        self.parent.gameTimer.setText(min + ":" + sec)


if __name__ == '__main__':
    with open('config.json', 'r') as config:
        config = json.loads(config.read())

    assert config['network']['tcp_dispatcher']['server_ip']
    assert config['network']['tcp_dispatcher']['server_port']
    assert config['network']['tcp_dispatcher']['abonents']
    assert type(config['network']['tcp_dispatcher']['abonents']) is list

    found = False
    for abonent in config['network']['tcp_dispatcher']['abonents']:
        if 'name' in abonent and str(abonent['name']).lower() == 'game':
            if 'ip' in abonent and 'port' in abonent:
                config['network']['tcp_dispatcher']['abonent'] = abonent
                found = True
    assert found == True

    app = QtWidgets.QApplication(sys.argv)
    game = GameWindow(config = config)
    game.show()
    sys.exit(app.exec_())