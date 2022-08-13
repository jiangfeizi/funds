import re
from datetime import datetime, time, timedelta
import pickle
import os
from collections import OrderedDict
from tkinter.messagebox import NO

import schedule
import requests
from requests.adapters import HTTPAdapter
import yaml
from email.mime.text import MIMEText
import smtplib
import pandas as pd
pd.set_option('display.unicode.ambiguous_as_wide', True)
pd.set_option('display.unicode.east_asian_width', True)
pd.set_option('display.width', 180)     

from advise import *


session = requests.Session()
session.mount('http://', HTTPAdapter(max_retries=3))
session.mount('https://', HTTPAdapter(max_retries=3))

def update_proxies(socks):
    proxies = {"http": f"socks5://{socks}", "https": f"socks5://{socks}"}
    session.proxies.update(proxies)

class Fund:
    date_pattern = re.compile(r'/\*([0-9]{4}-.*?)\*/')
    info_pattern = re.compile(r'var[\t ](.*?)[\t ]?=[\t ]?(.*?);')
    gz_pattern = re.compile(r'"(.*?)":"(.*?)"')

    @staticmethod
    def date_lastday():
        one = Fund('006624')
        return one.jz_lastday()[0]

    @staticmethod
    def is_trading():
        one = Fund('006624')
        if datetime.strptime(one.gz_data['gztime'], '%Y-%m-%d %H:%M').date() == datetime.now().date():
            return True
        else:
            return False

    def __init__(self, fS_code) -> None:
        self.fS_code = fS_code
        self._info = {}
        self.info_time = None
        self._gz_data = {}

    @property
    def info(self):
        try:
            r = session.get(f'https://fund.eastmoney.com/pingzhongdata/{self.fS_code}.js', timeout=(1, 1))
            if r.status_code == requests.codes.ok:
                match_obj = Fund.date_pattern.search(r.text)
                if match_obj:
                    info_time = datetime.strptime(match_obj.group(1), '%Y-%m-%d %H:%M:%S')
                    if not self.info_time or self.info_time != info_time:
                        self.info_time = info_time
                        self._info = dict(Fund.info_pattern.findall(r.text))
            else:
                print(f'Status_code is {r.status_code} in connection of {self.fS_code}.')
        except requests.exceptions.RequestException as e:
            print(f'Timeout in connection of {self.fS_code}.')

        return self._info

    @property
    def gz_data(self):
        try:
            r = session.get(f'http://fundgz.1234567.com.cn/js/{self.fS_code}.js', timeout=(1, 1))
            if r.status_code == requests.codes.ok:
                self._gz_data = dict(Fund.gz_pattern.findall(r.text))
            else:
                print(f'Status_code is {r.status_code} in connection of {self.fS_code}.')
        except requests.exceptions.RequestException as e:
            print(f'Timeout in connection of {self.fS_code}.')

        return self._gz_data

    def fS_name(self):
        return self.gz_data['name']

    def fund_Rate(self):
        return float(eval(self.info['fund_Rate']))

    def jz_lastday(self):
        yestearday_date = (datetime.now() - timedelta(1)).date()
        Data_netWorthTrend = eval(self.info['Data_netWorthTrend'])
        for item in Data_netWorthTrend[::-1]:
            date = datetime.fromtimestamp(item['x'] / 1000).date()
            if date <= yestearday_date:
                return (date.strftime('%m-%d'), item['y'], item['equityReturn'])

    def gz_day(self):
        date = datetime.strptime(self.gz_data['gztime'], '%Y-%m-%d %H:%M')
        if date.date() == datetime.now().date():
            return (float(self.gz_data['gsz']), float(self.gz_data['gszzl']))
        else:
            return None

    def get_price(self, op_date):
        op_date = datetime.strptime(op_date, '%Y-%m-%d')
        Data_netWorthTrend = eval(self.info['Data_netWorthTrend'])
        if op_date > datetime.fromtimestamp(Data_netWorthTrend[-1]['x'] / 1000):
            return None
        else:
            for item in Data_netWorthTrend[::-1]:
                time = datetime.fromtimestamp(item['x'] / 1000)
                if op_date == time:
                    return item['y']


class HeldFund(Fund):
    def __init__(self, fS_code, date, asset) -> None:
        super(HeldFund, self).__init__(fS_code)
        self._cost = asset 
        self._share = asset / self.get_price(date) if asset else 0
        self.op = []
        self.remain_op = []
        self.update_date = None

    @property
    def cost(self):
        self.update()
        return self._cost

    @property
    def share(self):
        self.update()
        return self._share

    def asset(self):
        return self.share * self.jz_lastday()[1]

    def update(self):
        update_date = datetime.now().date()
        if self.update_date != update_date and self.remain_op:
            self.update_date = update_date

            remain_op = []
            for date, num in self.remain_op:
                op_date = datetime.strptime(date, '%Y-%m-%d')
                if op_date.date() >= update_date:
                    remain_op.append([date, num])
                    continue
                
                price = self.get_price(date)
                if price:
                    self._cost += num
                    self._share += num / price * (1 - self.fund_Rate() * 0.01)
                    self.op.append([date, num])
                else:
                    remain_op.append([date, num])

            self.remain_op = remain_op

    def add_op(self, op):
        if self.remain_op:
            for index, (date, _) in enumerate(self.remain_op):
                if date == op[0]:
                    self.remain_op[index] = op
                    break
            else:
                self.remain_op.append(op)
        else:
            self.remain_op.append(op)

    def jz_ratio_lastday(self):
        return (self.share * self.jz_lastday()[1] - self.cost) / self.cost if self.cost else None

    def gz_ratio_day(self):
        return (self.share * self.gz_day()[0] - self.cost) / self.cost if self.gz_day() and self.cost else None

    def gz_profit_day(self):
        return self.share * (self.gz_day()[0] - self.jz_lastday()[1]) if self.gz_day() else None


class HeldFundManager:
    def __init__(self) -> None:
        self.database = OrderedDict()

    def __iter__(self):
        return iter(self.database)

    def __getitem__(self, item):
        return self.database[item]

    def parse(self, path):
        for line in open(path, encoding='utf8'):
            args = line.split()
            if args:
                if args[0] == 'remove':
                    self.remove(args[1])
                elif args[0] == 'add_from_op':
                    self.add_from_op(args[1], [args[2], float(args[3])])
                elif args[0] == 'add_from_asset':
                    self.add_from_asset(args[1], args[2], float(args[3]))
        open(path, 'w')

    def remove(self, fS_code):
        if fS_code in self.database:
            self.database.pop(fS_code)

    def add_from_op(self, fS_code, op):
        self.database[fS_code] = HeldFund(fS_code, 0, 0)
        self.database[fS_code].add_op(op)

    def add_from_asset(self, fS_code, date, asset):
        self.database[fS_code] = HeldFund(fS_code, date, asset)


class Market:
    info_pattern = re.compile(r'var.*?"(.*?),(.*?),(.*?),(.*?),.*?";')
    def __init__(self, fS_code) -> None:
        self.fS_code = fS_code
        self.headers = {'Referer': 'https://finance.sina.com.cn',}
        self._info = []

    def info(self):
        try:
            r = session.get(url=f'http://hq.sinajs.cn/list={self.fS_code}', timeout=(1, 1), headers=self.headers)
            if r.status_code == requests.codes.ok:
                match_obj = Market.info_pattern.search(r.text)
                if match_obj:
                    self._info = [match_obj.group(1), match_obj.group(2), match_obj.group(3), match_obj.group(4)]
            else:
                print(f'Status_code is {r.status_code} in connection of market.')
        except requests.exceptions.RequestException as e:
            print(f'Timeout in connection of stock.')
        
        return self._info


class Manager:
    def __init__(self, path) -> None:
        self.path = path
        self.config = yaml.safe_load(open(self.path, encoding='utf8'))
        if self.config['socks']:
            update_proxies(self.config['socks'])

        self.market = Market('s_sh000001')
        self.watch_funds = [Fund(item) for item in self.config['watch']]
        self.held_funds = pickle.load(open(self.config['database'], 'rb')) if os.path.exists(self.config['database']) else HeldFundManager()
        self.held_funds.parse(self.config['op'])

        schedule.every().day.at("14:45").do(self.request_advise)   

    def monitor(self):
        schedule.run_pending()
        msg = self.log_msg()
        print(msg)
        self.save()

    def sendmail(self, msg):
        msg = MIMEText(msg)
        msg['Subject'] = '今日战报'
        msg['From'] = self.config['email']
        msg['To'] = self.config['email']
        try:
            s = smtplib.SMTP_SSL("smtp.qq.com", 465)
            s.login(self.config['email'], self.config['passwd'])
            s.sendmail(self.config['email'], self.config['email'], msg.as_string())
            print("发送成功")
        except s.SMTPExceptione:
            print("发送失败")
        finally:
            s.quit()

    def log_msg(self):
        d = []
        for fS_code in self.held_funds:
            fund = self.held_funds[fS_code]
            d.append([fS_code, fund.fS_name(), fund.asset(), fund.gz_day()[1] if fund.gz_day() else None, fund.remain_op])

        df = pd.DataFrame(d, columns = ['ID', '名称', '资产', '估值', '操作'])
        return df

    def request_advise(self):
        if Fund.is_trading():
            msg = ''
            for fS_code in self.held_funds:
                fund = self.held_funds[fS_code]
                try:
                    op = eval(f'advise{fS_code}(fund)')
                    if op:
                        line = f'{fS_code}\t{fund.fS_name}\t{op[1]}\n'
                        msg += line
                    fund.add_op([datetime.now().strftime('%Y-%m-%d'), op])
                except Exception as e:
                    print(e)
                    continue

            msg += '\n' * 3
            msg += self.log_msg()
            self.sendmail(msg)

    def total_profit(self):
        profit = 0
        for fS_code in self.held_funds:
            fund = self.held_funds[fS_code]
            single_profit = fund.gz_profit_day()
            if not single_profit is None:
                profit += single_profit
            else:
                return None
        
        return profit

    def save(self):
        pickle.dump(self.held_funds, open(self.config['database'], 'wb'))


if __name__ == '__main__':
    Fund.is_trading()
    


