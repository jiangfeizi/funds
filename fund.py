import re
from datetime import datetime, time, timedelta
import pickle
import os
from collections import OrderedDict

import schedule
import numpy as np
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

update_proxies('127.0.0.1:2121')


class Fund:
    jz_pattern = re.compile(r'var[\t ](.*?)[\t ]?=[\t ]?(.*?);')
    gz_pattern = re.compile(r'"(.*?)":"(.*?)"')
    split_pattern = re.compile(r'\d+\.?\d*')
    def __init__(self, fS_code) -> None:
        self.fS_code = fS_code

        self._jz_update_date = None
        self.fS_name = None
        self.fund_Rate = None
        self._Data_netWorthTrend = None

        self.gsz = None
        self.gszzl = None
        self.gztime = None

    def update_fund(self):
        date_day = datetime.now().date()
        if not self._jz_update_date or self._jz_update_date != date_day:
            self._jz_update_date = date_day
            try:
                r = session.get(f'https://fund.eastmoney.com/pingzhongdata/{self.fS_code}.js', timeout=(1, 1))
                if r.status_code == requests.codes.ok:
                    jz_info = dict(self.jz_pattern.findall(r.text))

                    self.fS_name = eval(jz_info['fS_name'])
                    self.fund_Rate = float(eval(jz_info['fund_Rate']))
                    self._Data_netWorthTrend = eval(jz_info['Data_netWorthTrend'])
                else:
                    print(f'Status_code is {r.status_code} in connection of {self.fS_code}.')
            except requests.exceptions.RequestException as e:
                print(f'Timeout in connection of {self.fS_code}.')

        try:
            r = session.get(f'http://fundgz.1234567.com.cn/js/{self.fS_code}.js', timeout=(1, 1))
            if r.status_code == requests.codes.ok:
                gz_info = dict(Fund.gz_pattern.findall(r.text))

                self.gsz = float(gz_info['gsz'])
                self.gszzl = float(gz_info['gszzl'])
                self.gztime = datetime.strptime(gz_info['gztime'], '%Y-%m-%d %H:%M')
            else:
                print(f'Status_code is {r.status_code} in connection of {self.fS_code}.')
        except requests.exceptions.RequestException as e:
            print(f'Timeout in connection of {self.fS_code}.')

    def get_jz_data(self, date):
        if date > datetime.fromtimestamp(self._Data_netWorthTrend[-1]['x'] / 1000).date():
            return None
        else:
            for item in self._Data_netWorthTrend[::-1]:
                if datetime.fromtimestamp(item['x'] / 1000).date() == date:
                    split = float(self.split_pattern.search(item['unitMoney']).group(0)) if item['unitMoney'] else 1
                    return item['y'], item['equityReturn'], split
                if datetime.fromtimestamp(item['x'] / 1000).date() < date:
                    return None

    def get_last_trade_date(self):
        yestearday_date = (datetime.now() - timedelta(1)).date()
        for item in self._Data_netWorthTrend[::-1]:
            date = datetime.fromtimestamp(item['x'] / 1000).date()
            if date <= yestearday_date:
                return date

    def get_jz_last(self):
        return self.get_jz_data(self.get_last_trade_date())

    def get_gz_now(self):
        return self.gsz, self.gszzl


class HeldFund(Fund):
    def __init__(self, fS_code, date, asset, dividend=False) -> None:
        super(HeldFund, self).__init__(fS_code)
        self.update_fund()

        self._op_update_date = date
        self.cost = asset 
        self.share = asset / self.get_jz_data(date)[0]
        self.op = []
        self.remain_op = None
        self.dividend = dividend

    def update_op(self):
        self.update_fund()

        yestearday_date = (datetime.now() - timedelta(1)).date()
        while self._op_update_date < yestearday_date:
            self._op_update_date += timedelta(1)
            jz_data = self.get_jz_data(self._op_update_date)
            if jz_data:
                price, ratio, split = jz_data
                if self.dividend:
                    self.cost /= split
                else:
                    self.share *= split
                    
                if self.remain_op and self.remain_op[0] == self._op_update_date:
                    self.cost += self.remain_op[1]
                    self.share += self.remain_op[1] / price * (1 - self.fund_Rate * 0.01)
                    self.op.append(self.remain_op)
                    self.remain_op = None

    def asset(self):
        return self.share * self.get_jz_last()[0]

    def add_op(self, op):
        self.remain_op = op

    def gz_profit_day(self):
        gsz, _ = self.get_gz_now()
        return self.share * (gsz - self.get_jz_last()[0])

class FundCenter:
    def __init__(self) -> None:
        self.watch_funds = OrderedDict()
        self.held_funds = OrderedDict()
        self._example_fund = Fund('161121')

    def parse(self, path):
        for line in open(path, encoding='utf8'):
            command = line.split()
            if command:
                if command[0] == 'add_watch':
                    self.watch_funds[command[1]] = Fund(command[1])
                elif command[0] == 'remove_watch':
                    self.watch_funds.pop(command[1])
                elif command[0] == 'init_held':
                    fS_code, date, asset = command[1], datetime.strptime(command[2], '%Y-%m-%d'), float(command[3])
                    self.held_funds[fS_code] = HeldFund(fS_code, date, asset)
                elif command[0] == 'remove_held':
                    self.held_funds.pop(command[1])
                elif command[0] == 'op_held':
                    fS_code, date, num = command[1], datetime.strptime(command[2], '%Y-%m-%d'), float(command[3])
                    self.held_funds[fS_code].add_op([date, num])
                else:
                    print(f'Cann\'t parse line:{line}')
        open(path, 'w')

    def trading(self):
        return True if self._example_fund.gztime.date() == datetime.now().date() else False

    def get_last_trade_date(self):
        return self._example_fund.get_last_trade_date()

    def update(self):
        for fS_code in self.watch_funds:
            fund = self.watch_funds[fS_code]
            fund.update_fund()

        for fS_code in self.held_funds:
            fund = self.held_funds[fS_code]
            fund.update_op()

        self._example_fund.update_fund()


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
        self.fund_center = pickle.load(open(self.config['database'], 'rb')) if os.path.exists(self.config['database']) else FundCenter()
        self.fund_center.parse(self.config['op'])
        self.fund_center.update()

        schedule.every().day.at("14:45").do(self.request_advise)

    def monitor(self):
        self.fund_center.update()
        schedule.run_pending()

        print(self.get_log())
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

    def get_log(self):
        d = []
        for fS_code in self.fund_center.held_funds:
            fund = self.fund_center.held_funds[fS_code]
            d.append([fS_code, fund.fS_name, f'{fund.asset():.2f}', f'{fund.gszzl}%' if self.fund_center.trading() else None, fund.remain_op])

        df = pd.DataFrame(d, columns = ['ID', '名称', '资产', '估值', '操作'])
        return df

    def request_advise(self):
        if self.fund_center.trading():
            msg = ''
            for fS_code in self.fund_center.held_funds:
                fund = self.fund_center.held_funds[fS_code]
                try:
                    num = eval(f'advise{fS_code}(fund)')
                    if num:
                        line = f'{fS_code}\t{fund.fS_name}\t{num}\n'
                        msg += line
                    fund.add_op([datetime.now().strftime('%Y-%m-%d'), num])
                except Exception as e:
                    print(e)
                    continue

            msg += '\n' * 3
            msg += self.get_log()
            self.sendmail(msg)

    def total_profit(self):
        profit = 0
        for fS_code in self.fund_center.held_funds:
            fund = self.fund_center.held_funds[fS_code]
            profit += fund.gz_profit_day()
        return profit
            
    def save(self):
        pickle.dump(self.fund_center, open(self.config['database'], 'wb'))


if __name__ == '__main__':
    one = Market('s_sh000001')
    one.info
    one = HeldFund('161121', (datetime.now() - timedelta(1)).date(), 1000)
    one.update_jz()
    a = one.update()
    print()
    


