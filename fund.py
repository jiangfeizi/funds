import re
from datetime import datetime, time, timedelta
import pickle
import os
from collections import OrderedDict

import schedule
import requests
from requests.adapters import HTTPAdapter
import yaml
from email.mime.text import MIMEText
import smtplib

from advise import method1

def strB2Q(ustring):
    """半角转全角"""
    rstring = ""
    for uchar in ustring:
        inside_code=ord(uchar)
        if inside_code == 32:                                 #半角空格直接转化                  
            inside_code = 12288
        elif inside_code >= 32 and inside_code <= 126:        #半角字符（除空格）根据关系转化
            inside_code += 65248

        rstring += chr(inside_code)
    return rstring

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
    @staticmethod
    def init(fS_code, init_op, init_asset, init_ratio, init_share, method, args):
        op = []
        remain_op = []
        if init_op:
            remain_op.append(init_op)
            cost = 0
            share = 0
        else:
            cost = init_asset / (1 + init_ratio * 0.01)
            share = init_share

        return HeldFund(fS_code, cost, share, op, remain_op, method, args)

    def __init__(self, fS_code, cost, share, op, remain_op, method, args) -> None:
        super(HeldFund, self).__init__(fS_code)
        self._cost = cost
        self._share = share
        self.op = op
        self.remain_op = remain_op
        self.method = method
        self.args = args
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
        return (self.share * self.jz_lastday()[1] - self.cost) / self.cost

    def gz_ratio_day(self):
        return (self.share * self.gz_day()[0] - self.cost) / self.cost if self.gz_day() else None

    def gz_profit_day(self):
        return self.share * (self.gz_day()[0] - self.jz_lastday()[1]) if self.gz_day() else None

    def get_advise_op(self):
        if self.method == 1:
            num = method1(self, *self.args)
        if num:
            op = [datetime.now().date().strftime('%Y-%m-%d'), num]
            self.add_op(op)
        else:
            op = None
        return op


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
        self.held_funds = pickle.load(open(self.config['database'], 'rb')) if os.path.exists(self.config['database']) else OrderedDict()
        self.remove_funds()
        self.add_funds()

        schedule.every().day.at("14:45").do(self.request_advise)   

    def monitor(self):
        schedule.run_pending()
        msg = self.log_msg()
        print(msg)
        self.save()

    def remove_funds(self):
        for fS_code in self.config['remove']:
            self.held_funds.pop(fS_code)
        self.config['remove'] = []

    def add_funds(self):
        for fS_code, value in self.config['add'].items():
            self.held_funds[fS_code] = HeldFund.init(fS_code, value['init_op'], value['init_asset'], 
                            value['init_ratio'], value['init_share'], value['method'], value['args'])
        self.config['add'] = {}

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
        msg = ''
        line = f'ID\t名称\t资产\t盈亏\t估值\t方法\t参数\n'
        msg += line
        for fS_code in self.held_funds:
            fund = self.held_funds[fS_code]
            line = f'{fS_code}\t{fund.fS_name()}\t{fund.asset()}\t' + \
                f'{fund.jz_ratio_lastday()}\t{fund.gz_day()[1]}\t{fund.method}\t{fund.args}\n'
            msg += line
        return msg

    def request_advise(self):
        msg = ''
        for fS_code in self.held_funds:
            fund = self.held_funds[fS_code]
            op = fund.get_advise_op()
            if op:
                line = f'{fund.fS_code}\t{fund.fS_name}\t{op[1]}\n'
                msg += line

        msg += '\n' * 3
        msg += self.log_msg()

        self.sendmail(msg)

    def total_profit(self):
        profit = 0
        for fS_code in self.held_funds:
            fund = self.held_funds[fS_code]
            single_profit = fund.gz_profit_day()
            if single_profit:
                profit += single_profit
            else:
                return None
        
        return profit

    def save(self):
        yaml.dump(self.config, open(self.path, 'w', encoding='utf8'))
        pickle.dump(self.held_funds, open(self.config['database'], 'wb'))


if __name__ == '__main__':
    one = Manager('workspace/config.yaml')
    pass


