import re
from datetime import datetime, timedelta
import pickle
import os
from collections import OrderedDict

import schedule
import requests
from requests.adapters import HTTPAdapter
import yaml
from email.mime.text import MIMEText
import smtplib
import pandas as pd
import numpy as np
pd.set_option('display.unicode.ambiguous_as_wide', True)
pd.set_option('display.unicode.east_asian_width', True)
pd.set_option('display.width', 180)     

from advise import *

proxies = {'http': 'http://172.30.3.98:20171', 'https': 'http://172.30.3.98:20171'}
a = requests.get(r'http://fund.eastmoney.com/pingzhongdata/000060.js', proxies=proxies) #verify是否验证服务器的SSL证书
# a = requests.get(r'http://www.example.com') #verify是否验证服务器的SSL证书

session = requests.Session()
session.mount('http://', HTTPAdapter(max_retries=3))
session.mount('https://', HTTPAdapter(max_retries=3))

def update_proxies(socks):
    proxies = {"http": f"http://{socks}", "https": f"http://{socks}"}
    session.proxies.update(proxies)

update_proxies('172.30.3.98:20171')

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
        self._syl_1y = None
        self._syl_3y = None
        self._syl_6y = None
        self._syl_1n = None

        self.gsz = None
        self.gszzl = None
        self.gztime = None

    def update_fund(self):
        date_day = datetime.now().date()
        if not self._jz_update_date or self._jz_update_date != date_day:
            try:
                r = session.get(f'https://fund.eastmoney.com/pingzhongdata/{self.fS_code}.js', timeout=(1, 1))
                if r.status_code == requests.codes.ok:
                    jz_info = dict(self.jz_pattern.findall(r.text))

                    self.fS_name = eval(jz_info['fS_name'])
                    self.fund_Rate = float(eval(jz_info['fund_Rate']))
                    self._Data_netWorthTrend = eval(jz_info['Data_netWorthTrend'])
                    self._Data_ACWorthTrend = eval(jz_info['Data_ACWorthTrend'].replace('null', 'None'))
                    self._syl_1y = float(eval(jz_info['syl_1y'])) if eval(jz_info['syl_1y']) else None
                    self._syl_3y = float(eval(jz_info['syl_3y'])) if eval(jz_info['syl_3y']) else None
                    self._syl_6y = float(eval(jz_info['syl_6y'])) if eval(jz_info['syl_6y']) else None
                    self._syl_1n = float(eval(jz_info['syl_1n'])) if eval(jz_info['syl_1n']) else None
                else:
                    print(f'Status_code is {r.status_code} in connection of {self.fS_code}.')
            except requests.exceptions.RequestException as e:
                print(f'Timeout in connection of {self.fS_code}.')
            else:
                self._jz_update_date = date_day
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
        except:
            pass

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

    def get_max_drawdown(self):
        jz_data = np.array([item[1] for item in self._Data_ACWorthTrend if item[1]])
        return np.max((np.maximum.accumulate(jz_data) - jz_data)/np.maximum.accumulate(jz_data))
    
    def get_jz_drawdown(self):
        jz_data = np.array([item[1] for item in self._Data_ACWorthTrend if item[1]])
        return ((np.maximum.accumulate(jz_data) - jz_data)/np.maximum.accumulate(jz_data))[-1]

    def get_gz_now(self):
        return self.gsz, self.gszzl

    def get_gz_drawdown(self):
        jz_data = np.array([item[1] for item in self._Data_ACWorthTrend if item[1]])
        if self.gztime.date() == datetime.fromtimestamp(self._Data_ACWorthTrend[-1][0] / 1000).date():
            return 1 - self._Data_ACWorthTrend[-2][1] * (1 + self.gszzl * 0.01) / np.max(jz_data[:-1])
        else:
            return 1 - self._Data_ACWorthTrend[-1][1] * (1 + self.gszzl * 0.01) / np.max(jz_data)


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
        yestearday_date = (datetime.now() - timedelta(1)).date()
        if op[0] <= yestearday_date:
            op_update_date = op[0]
            cost = 0
            share = 0
            while op_update_date < yestearday_date:
                jz_data = self.get_jz_data(op_update_date)
                if jz_data:
                    price, ratio, split = jz_data
                    if self.dividend:
                        cost /= split
                    else:
                        share *= split
                        
                    if op[0] == op_update_date:
                        cost += op[1]
                        share += op[1] / price * (1 - self.fund_Rate * 0.01)
                        self.op.append(op)

                op_update_date += timedelta(1)

            self.cost += cost
            self.share += share
        else:
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
                    fS_code, date, asset = command[1], datetime.strptime(command[2], '%Y-%m-%d').date(), float(command[3])
                    self.held_funds[fS_code] = HeldFund(fS_code, date, asset)
                elif command[0] == 'remove_held':
                    self.held_funds.pop(command[1])
                elif command[0] == 'op_held':
                    fS_code, date, num = command[1], datetime.strptime(command[2], '%Y-%m-%d').date(), float(command[3])
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
        self.fund_center.update()
        self.fund_center.parse(self.config['op'])

        schedule.every().day.at("14:45").do(self.request_advise)

        self.total_profit()

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
            d.append([fS_code, fund.fS_name, f'{fund.asset():.2f}', f'{fund.gszzl}%' if self.fund_center.trading() else None, 
                        f'{fund.get_max_drawdown()*100:.2f}%' if self.fund_center.trading() else None, 
                        f'{fund.get_gz_drawdown()*100:.2f}%' if self.fund_center.trading() else None, 
                        fund._syl_1y,
                        fund.remain_op])

        d.sort(key=lambda x: float(x[5][:-1]))

        df = pd.DataFrame(d, columns = ['ID', '名称', '资产', '估值', '最大回撤', '回撤', '近一月', '操作'])
        return df.__str__()

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
    import numpy as np
    
    def maxdrawdown(arr):
        i = np.argmax((np.maximum.accumulate(arr) - arr)/np.maximum.accumulate(arr)) # end of the period
        j = np.argmax(arr[:i]) # start of period
        return (1-arr[i]/arr[j])

    # one = HeldFund('519198', (datetime.now() - timedelta(1)).date(), 1000)
    # one.update_op()
    # print(one.get_max_drawdown())
    # print(one.get_gz_drawdown())
    # print()

    import requests
    
    import pandas as pd
    from bs4 import BeautifulSoup

    morning_star_url = 'https://www.icbcswiss.com/ICBCDynamicSite/site/Fund/FundCXRankDetailLittle.aspx'
    proxies = {'http': 'http://172.30.3.98:20171', 'https': 'http://172.30.3.98:20171',}
    r = requests.get(morning_star_url, proxies=proxies)

    from bs4 import BeautifulSoup

    bs = BeautifulSoup(r.text, 'lxml')
    pd.DataFrame()

    total_funds = []
    for tr in bs.find_all('tr', {'style': 'word-break:keep-all;white-space:nowrap; '}):
        tds = list(tr.find_all('td'))

        level3 = len(tds[3].string) if '★' in tds[3].string else None
        level5 = len(tds[4].string) if '★' in tds[3].string else None
        if level3 == level5 == 5:
            total_funds.append([tds[0].string, tds[1].string, tds[2].string, level3, level5])

    result = []
    for item in total_funds:
        fund = Fund(item[0])
        fund.update_fund()
        # print(item[0], item[1], fund.get_max_drawdown(), fund.get_jz_drawdown())
        result.append((item[0], item[1], fund.get_max_drawdown(), fund.get_jz_drawdown()))

    result.sort(key=lambda item: item[3])

    for i in result:
        print(f"{i[0]}, {i[1]}, {i[2]:.2f}, {i[3]:.2f}")
    
    # pds = pd.DataFrame(total_funds, columns=['基金代码', '基金名称', '晨星评级日期', '晨星评级(三年)', '晨星评级(五年)'], dtype=str)
    # pds.to_csv(r'\\172.30.3.98\jwdata\111.aaa')
    


