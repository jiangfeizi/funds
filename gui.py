import sys
import time
from datetime import datetime
import time

from qtpy.QtWidgets import QMainWindow, QWidget, QApplication, QStatusBar, QLabel, QVBoxLayout, \
    QTableWidget, QHeaderView, QTabWidget, QTableWidgetItem
from qtpy.QtCore import Signal, QMetaObject, QObject, QThread, Qt

from fund import Manager

class Updater(QObject):
    market_update_singal = Signal(str, str, str, str)
    profit_update_singal = Signal(str)
    watch_update_singal = Signal(str, str, str, str, str)
    held_update_singal = Signal(str, str, str, str, str)
    def __init__(self, manager):
        super().__init__()
        self.manager = manager

    def run(self):
        while True:
            start = time.time()
            self.manager.monitor()

            name, val, change, ratio = self.manager.market.info()
            self.market_update_singal.emit(name, val, change, ratio)

            for fS_code in self.manager.fund_center.watch_funds:
                fund = self.manager.fund_center.watch_funds[fS_code]
                jz_val, jz_ratio, _ = fund.get_jz_last()

                if self.manager.fund_center.trading():
                    gz_val, gz_ratio = fund.get_gz_now()
                    self.watch_update_singal.emit(fund.fS_code, str(jz_val), str(jz_ratio), str(gz_val), str(gz_ratio))
                else:
                    self.watch_update_singal.emit(fund.fS_code, str(jz_val), str(jz_ratio), '', '')

            for fS_code in self.manager.fund_center.held_funds:
                fund = self.manager.fund_center.held_funds[fS_code]
                jz_val, jz_ratio, _ = fund.get_jz_last()
                if self.manager.fund_center.trading():
                    gz_val, gz_ratio = fund.get_gz_now()
                    self.held_update_singal.emit(fund.fS_code, str(jz_val), str(jz_ratio), str(gz_val), str(gz_ratio))
                else:
                    self.held_update_singal.emit(fund.fS_code, str(jz_val), str(jz_ratio), '', '')

            if self.manager.fund_center.trading():
                profit = self.manager.total_profit()
                self.profit_update_singal.emit(f'{float(profit):+.2f}')
            else:
                self.profit_update_singal.emit('')

            end = time.time()
            remain = self.manager.config['update_interval'] - end + start
            if remain > 0:
                time.sleep(remain)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super(MainWindow, self).__init__()
        self.manager = Manager('config/config.yaml')
        self.setupUi()

        self.thread = QThread()
        self.updater = Updater(self.manager)
        self.updater.moveToThread(self.thread)
        self.thread.started.connect(self.updater.run)
        self.updater.market_update_singal.connect(self.market_update)
        self.updater.profit_update_singal.connect(self.profit_update)
        self.updater.watch_update_singal.connect(self.watch_update)
        self.updater.held_update_singal.connect(self.held_update)
        self.thread.start()

    def profit_update(self, profit):
        if profit:
            self.profit_label.setText(self.tr("??????????????????:") + f'{float(profit):+}')
        else:
            self.profit_label.setText(self.tr("??????????????????:") + f'NULL')

    def market_update(self, name, val, change, ratio):
        self.update_headers()
        self.market_label.setText(self.tr("????????????:") + f'{float(val):.2f}   {float(change):+.2f}   {float(ratio):+}%')

    def watch_update(self, fS_code, jz_val, jz_ratio, gz_val, gz_ratio):
        for index, code in enumerate(self.manager.fund_center.watch_funds):
            if fS_code == self.manager.fund_center.watch_funds[code].fS_code:
                self.tableWidget_watch.item(index, 1).setText(f'{jz_val}\n{float(jz_ratio):+}%')
                if gz_val and gz_ratio:
                    self.tableWidget_watch.item(index, 2).setText(f'{gz_val}\n{float(gz_ratio):+}%')
                else:
                    self.tableWidget_watch.item(index, 2).setText(f'NULL')
                break

    def held_update(self, fS_code, jz_val, jz_ratio, gz_val, gz_ratio):
        for index, code in enumerate(self.manager.fund_center.held_funds):
            if fS_code == self.manager.fund_center.held_funds[code].fS_code:
                self.tableWidget_held.item(index, 1).setText(f'{jz_val}\n{float(jz_ratio):+}%')
                if gz_val and gz_ratio:
                    self.tableWidget_held.item(index, 2).setText(f'{gz_val}\n{float(gz_ratio):+}%')
                else:
                    self.tableWidget_held.item(index, 2).setText(f'NULL')
                break

    def setupUi(self):
        self.setObjectName("MainWindow")

        self.centralwidget = QWidget(self)
        self.centralwidget.setObjectName("centralwidget")
        self.setCentralWidget(self.centralwidget)

        self.verticalLayout_centralwidget = QVBoxLayout(self.centralwidget)
        self.tabWidget = QTabWidget(self.centralwidget)
        self.tabWidget.setObjectName("tabWidget")
        self.verticalLayout_centralwidget.addWidget(self.tabWidget)

        self.tab_watch = QWidget()
        self.tab_watch.setObjectName("tab_watch")
        self.verticalLayout_watch = QVBoxLayout(self.tab_watch)
        self.verticalLayout_watch.setObjectName("verticalLayout_watch")
        self.tableWidget_watch = QTableWidget(self.tab_watch)
        self.tableWidget_watch.setObjectName("tableWidget_watch")
        self.tableWidget_watch.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tableWidget_watch.horizontalHeader().setStyleSheet(
        "QHeaderView::section{"
                    "border-top:0px solid #E5E5E5;"
                    "border-left:0px solid #E5E5E5;"
                    "border-right:0px solid #E5E5E5;"
                    "border-bottom: 0px solid #E5E5E5;"
                    "background-color:white;"
                    "padding:4px;"
                "}")

        self.tableWidget_watch.verticalHeader().hide()
        self.tableWidget_watch.setShowGrid(False)
        self.verticalLayout_watch.addWidget(self.tableWidget_watch)

        self.market_label = QLabel(self.tab_watch)
        self.market_label.setObjectName("market_label")
        self.verticalLayout_watch.addWidget(self.market_label)

        self.tabWidget.addTab(self.tab_watch, "")

        self.tab_held = QWidget()
        self.tab_held.setObjectName("tab_held")
        self.verticalLayout_held = QVBoxLayout(self.tab_held)
        self.verticalLayout_held.setObjectName("verticalLayout_held")
        self.tableWidget_held = QTableWidget(self.tab_held)
        self.tableWidget_held.setObjectName("tableWidget_held")
        self.tableWidget_held.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tableWidget_held.horizontalHeader().setStyleSheet(
        "QHeaderView::section{"
                    "border-top:0px solid #E5E5E5;"
                    "border-left:0px solid #E5E5E5;"
                    "border-right:0px solid #E5E5E5;"
                    "border-bottom: 0px solid #E5E5E5;"
                    "background-color:white;"
                    "padding:4px;"
                "}")

        self.tableWidget_held.verticalHeader().hide()
        self.tableWidget_held.setShowGrid(False)
        self.verticalLayout_held.addWidget(self.tableWidget_held)

        self.profit_label = QLabel(self.tab_held)
        self.profit_label.setObjectName("profit_label")
        self.verticalLayout_held.addWidget(self.profit_label)

        self.tabWidget.addTab(self.tab_held, "")
        self.tabWidget.setCurrentIndex(0)

        #?????????
        self.statusbar = QStatusBar(self)
        self.statusbar.setObjectName("statusbar")
        self.setStatusBar(self.statusbar)

        self.retranslateUi()
        QMetaObject.connectSlotsByName(self)

        for fS_code in self.manager.fund_center.watch_funds:
            fund = self.manager.fund_center.watch_funds[fS_code]
            fS_name = fund.fS_name
            self.tableWidget_watch.setRowCount(self.tableWidget_watch.rowCount()+1)
            row_index = self.tableWidget_watch.rowCount() - 1
            self.tableWidget_watch.setRowHeight(row_index, 50)

            widget_item = QTableWidgetItem(f'{fS_name}\n{fS_code}')
            widget_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.tableWidget_watch.setItem(row_index, 0, widget_item)
            widget_item = QTableWidgetItem()
            widget_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.tableWidget_watch.setItem(row_index, 1, widget_item)
            widget_item = QTableWidgetItem()
            widget_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.tableWidget_watch.setItem(row_index, 2, widget_item)

        for fS_code in self.manager.fund_center.held_funds:
            fund = self.manager.fund_center.held_funds[fS_code]
            fS_name = fund.fS_name
            self.tableWidget_held.setRowCount(self.tableWidget_held.rowCount()+1)
            row_index = self.tableWidget_held.rowCount() - 1
            self.tableWidget_held.setRowHeight(row_index, 50)

            widget_item = QTableWidgetItem(f'{fS_name}\n{fS_code}')
            widget_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.tableWidget_held.setItem(row_index, 0, widget_item)
            widget_item = QTableWidgetItem()
            widget_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.tableWidget_held.setItem(row_index, 1, widget_item)
            widget_item = QTableWidgetItem()
            widget_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.tableWidget_held.setItem(row_index, 2, widget_item)

    def retranslateUi(self):
        self.setWindowTitle(self.tr("??????"))

        self.tabWidget.setTabText(0, self.tr("??????"))
        self.tabWidget.setTabText(1, self.tr("??????"))
        self.tableWidget_watch.setColumnCount(3)
        self.tableWidget_held.setColumnCount(3)
        self.update_headers()

        self.market_label.setText(self.tr("????????????:"))
        self.profit_label.setText(self.tr("??????????????????:"))


    def update_headers(self):
        today_date = datetime.now().date().strftime('%m-%d')
        self.tableWidget_headers = [self.tr("??????"), self.tr("??????") + f'\n{self.manager.fund_center.get_last_trade_date().strftime("%m-%d")}', 
                                self.tr("??????") + f'\n{today_date}']
        self.tableWidget_watch.setHorizontalHeaderLabels(self.tableWidget_headers)
        self.tableWidget_held.setHorizontalHeaderLabels(self.tableWidget_headers)

if __name__ == "__main__":
    app = QApplication([])

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())