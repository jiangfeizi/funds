import argparse
import matplotlib
import matplotlib.pyplot as plt
import requests
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
import re
from datetime import datetime
from queue import Queue, Empty
import threading
import os
from dateutil.relativedelta import relativedelta
import shelve
from tqdm import tqdm


matplotlib.use('Agg')
plt.rcParams['font.family'] = 'SimHei'


MORNING_STAR_URL = 'https://www.icbcswiss.com/ICBCDynamicSite/site/Fund/FundCXRankDetailLittle.aspx'
SHANGZHENG_CODE = 's_sh000001'
SHENZHENG_CODE = 's_sz399001'
CHUANGYE_CODE = 's_sz399006'


jz_pattern = re.compile(r'var[\t ](.*?)[\t ]?=[\t ]?(.*?);')
gz_pattern = re.compile(r'"(.*?)":"(.*?)"')
split_pattern = re.compile(r'\d+\.?\d*')
market_pattern = re.compile(r'var.*?"(.*?),(.*?),(.*?),(.*?),.*?";')


session = requests.Session()
session.mount('http://', HTTPAdapter(max_retries=3))
session.mount('https://', HTTPAdapter(max_retries=3))


def filter_morning_star_funds(last3_level, last5_level):
    try:
        r = session.get(MORNING_STAR_URL)
        bs = BeautifulSoup(r.text, 'lxml')

        filter_funds = []
        for tr in bs.find_all('tr', {'style': 'word-break:keep-all;white-space:nowrap; '}):
            tds = list(tr.find_all('td'))

            fund_last3_level = len(tds[3].string) if '★' in tds[3].string else 0
            fund_last5_level = len(tds[4].string) if '★' in tds[3].string else 0
            if fund_last3_level >= last3_level and fund_last5_level >= last5_level:
                filter_funds.append([str(tds[0].string), str(tds[1].string), fund_last3_level, fund_last5_level])
    except:
        filter_funds = []
        print(f'something is wrong in getting filter_morning_star_funds.')

    return filter_funds

def read_watch_funds(path):
    return [line.strip() for line in open(path, encoding='utf8') if line.strip()]


def get_market_info(fs_code):
    headers = {'Referer': 'https://finance.sina.com.cn',}

    try:
        r = session.get(url=f'http://hq.sinajs.cn/list={fs_code}', headers=headers)
        if r.status_code == requests.codes.ok:
            match_obj = market_pattern.search(r.text)
            data = [match_obj.group(1), match_obj.group(2), match_obj.group(3), '%' + match_obj.group(4)]
        else:
            data = None
    except:
        data = None

    if not data:
        print(f'something is wrong in getting {fs_code} info.')
    
    return data

def get_jz_data(fs_code):
    try:
        r = session.get(f'https://fund.eastmoney.com/pingzhongdata/{fs_code}.js')
        if r.status_code == requests.codes.ok:
            data = dict(jz_pattern.findall(r.text))
        else:
            data = None
    except:
        data = None

    if not data:
        print(f'something is wrong in getting {fs_code} jz_data.')

    return data

def get_gz_data(fs_code):
    try:
        r = session.get(f'http://fundgz.1234567.com.cn/js/{fs_code}.js', timeout=(1, 1))
        if r.status_code == requests.codes.ok:
            data = dict(gz_pattern.findall(r.text))
        else:
            data = None
    except:
        data = None

    if not data:
        print(f'something is wrong in getting {fs_code} gz_data.')

    return data

def thread_update(fs_queue, shelve_funds, fund_dict):
    while True:
        try:
            fs_code = fs_queue.get(block=False)
            if fs_code in shelve_funds:
                fund = shelve_funds[fs_code]
                fund.update()
            else:
                fund = Fund(fs_code)
            fund_dict[fs_code] = fund
        except Empty:
            t = threading.currentThread()
            print(f'thread {t.ident} completed.')
            break
        except:
            print(f'somethine is wrong in {fs_code}.')
            continue

def draw_sly(title, data, syl):
    x, y = list(zip(*data))
    plt.title(f'{title}: %{syl:.2f}')
    plt.plot_date(x, y, 'r')
    inter = len(x) // 4
    plt.xticks(x[::inter])


class Fund:
    def __init__(self, fs_code) -> None:
        self.fs_code = fs_code
        self.jz_data = get_jz_data(self.fs_code)
        self.gz_data = get_gz_data(self.fs_code)
        self.analyze_jz()
        self.analyze_gz()
        self.request_date = datetime.now().date()

    def update(self):
        if self.request_date != datetime.now().date():
            self.jz_data = get_jz_data(self.fs_code)
            self.analyze_jz()
        self.gz_data = get_gz_data(self.fs_code)
        self.analyze_gz()
        self.request_date = datetime.now().date()

    def analyze_jz(self):
        Data_netWorthTrend = eval(self.jz_data['Data_netWorthTrend'].replace('null', 'None'))
        Data_ACWorthTrend = eval(self.jz_data['Data_ACWorthTrend'].replace('null', 'None'))
        Data_ACWorthTrend = [[datetime.fromtimestamp(item[0] / 1000).date(), item[1]] for item in Data_ACWorthTrend]

        self.fs_name = self.jz_data['fS_name'][1:-1]
        self.jsz = Data_netWorthTrend[-1]['y']
        self.jztime = Data_ACWorthTrend[-1][0]
        self.ac_jsz = Data_ACWorthTrend[-1][1]

        ac_data = np.array([item[1] for item in Data_ACWorthTrend if item[1]])
        self.maximum_drawdown = np.max((np.maximum.accumulate(ac_data) - ac_data) / np.maximum.accumulate(ac_data)) * 100
        self.current_drawdown = (np.max(ac_data) - ac_data[-1]) / np.max(ac_data) * 100

        self.jz_1y = []
        self.jz_3y = []
        self.jz_6y = []
        self.jz_1n = []
        self.jz_3n = []
        self.jz_5n = []
        self.jz_total = []
        current_date = datetime.now().date()
        for item in Data_ACWorthTrend:
            if item[0] >= current_date - relativedelta(months=1):
                self.jz_1y.append(item)
                self.jz_3y.append(item)
                self.jz_6y.append(item)
                self.jz_1n.append(item)
                self.jz_3n.append(item)
                self.jz_5n.append(item)
                self.jz_total.append(item)
            elif item[0] >= current_date - relativedelta(months=3):
                self.jz_3y.append(item)
                self.jz_6y.append(item)
                self.jz_1n.append(item)
                self.jz_3n.append(item)
                self.jz_5n.append(item)
                self.jz_total.append(item)
            elif item[0] >= current_date - relativedelta(months=6):
                self.jz_6y.append(item)
                self.jz_1n.append(item)
                self.jz_3n.append(item)
                self.jz_5n.append(item)
                self.jz_total.append(item)
            elif item[0] >= current_date - relativedelta(years=1):
                self.jz_1n.append(item)
                self.jz_3n.append(item)
                self.jz_5n.append(item)
                self.jz_total.append(item)
            elif item[0] >= current_date - relativedelta(years=3):
                self.jz_3n.append(item)
                self.jz_5n.append(item)
                self.jz_total.append(item)
            elif item[0] >= current_date - relativedelta(years=5):
                self.jz_5n.append(item)
                self.jz_total.append(item)
            else:
                self.jz_total.append(item)

        self.jzl_1y = (self.jz_1y[-1][1] - self.jz_1y[0][1]) / self.jz_1y[0][1] * 100 if self.jz_1y else None
        self.jzl_3y = (self.jz_3y[-1][1] - self.jz_3y[0][1]) / self.jz_3y[0][1] * 100 if self.jz_3y else None
        self.jzl_6y = (self.jz_6y[-1][1] - self.jz_6y[0][1]) / self.jz_6y[0][1] * 100 if self.jz_6y else None
        self.jzl_1n = (self.jz_1n[-1][1] - self.jz_1n[0][1]) / self.jz_1n[0][1] * 100 if self.jz_1n else None
        self.jzl_3n = (self.jz_3n[-1][1] - self.jz_3n[0][1]) / self.jz_3n[0][1] * 100 if self.jz_3n else None
        self.jzl_5n = (self.jz_5n[-1][1] - self.jz_5n[0][1]) / self.jz_5n[0][1] * 100 if self.jz_5n else None
        self.jzl_total = (self.jz_total[-1][1] - self.jz_total[0][1]) / self.jz_total[0][1] * 100 if self.jz_total else None

    def analyze_gz(self):
        Data_netWorthTrend = eval(self.jz_data['Data_netWorthTrend'].replace('null', 'None'))
        Data_ACWorthTrend = eval(self.jz_data['Data_ACWorthTrend'].replace('null', 'None'))
        Data_ACWorthTrend = [[datetime.fromtimestamp(item[0] / 1000).date(), item[1]] for item in Data_ACWorthTrend]

        self.gsz = float(self.gz_data['gsz']) if self.gz_data else None
        self.gszzl = float(self.gz_data['gszzl']) if self.gz_data else None
        self.gztime = datetime.strptime(self.gz_data['gztime'], '%Y-%m-%d %H:%M').date() if self.gz_data else None

        if self.gz_data:
            for item in Data_ACWorthTrend[::-1]:
                if item[0] < datetime.strptime(self.gz_data['gztime'], '%Y-%m-%d %H:%M').date():
                    ac_jz = item[1]
                    break
            for item in Data_netWorthTrend[::-1]:
                if datetime.fromtimestamp(item['x'] / 1000).date() < datetime.strptime(self.gz_data['gztime'], '%Y-%m-%d %H:%M').date():
                    jz = item['y']
                    break

        self.ac_gsz = (ac_jz + self.gsz - jz) if self.gz_data else None
        ac_data = np.array([item[1] for item in Data_ACWorthTrend if item[1]])
        self.gz_drawdown = (np.max(ac_data) - self.ac_gsz) / np.max(ac_data) * 100 if self.gz_data else None


if __name__=='__main__':
    parse = argparse.ArgumentParser(prog='TTFund')
    parse.add_argument("--last3_level", default=5)
    parse.add_argument("--last5_level", default=5)
    parse.add_argument("--update_morning_star", action='store_true')
    parse.add_argument("--num_works", default=4)
    parse.add_argument("--data_space", default='data')
    parse.add_argument("--proxy", default='')
    args = parse.parse_args()

    watch_funds_path = os.path.join(args.data_space, 'watch_funds.txt')
    watch_funds_dir = os.path.join(args.data_space, 'watch_funds')
    morning_star_dir = os.path.join(args.data_space, 'morning_star')
    data_shelve = os.path.join(args.data_space, 'data')

    if not os.path.exists(args.data_space):
        os.mkdir(args.data_space)
    if not os.path.exists(watch_funds_dir):
        os.mkdir(watch_funds_dir)
    if not os.path.exists(morning_star_dir):
        os.mkdir(morning_star_dir)

    if args.proxy:
        session.proxies.update({"http": args.proxy, "https": args.proxy})

    shangzheng_info = get_market_info(SHANGZHENG_CODE)
    shenzheng_info = get_market_info(SHENZHENG_CODE)
    chuangye_info = get_market_info(CHUANGYE_CODE)

    print(shangzheng_info)
    print(shenzheng_info)
    print(chuangye_info)

    watch_funds_dict = {}
    watch_funds_table = []
    morning_star_funds_dict = {}
    morning_star_funds_table = []

    with shelve.open(data_shelve) as db:
        shelve_funds = db.get('funds', {})
        watch_funds = read_watch_funds(watch_funds_path)
        for fs_code in tqdm(watch_funds):
            if fs_code in shelve_funds:
                fund = shelve_funds[fs_code]
                fund.update()
            else:
                fund = Fund(fs_code)
            watch_funds_dict[fs_code] = fund

            watch_funds_table.append([fund.fs_code, fund.fs_name, fund.jztime, fund.jsz, fund.ac_jsz, 
                                    fund.gztime, fund.gsz, fund.gszzl, fund.ac_gsz, 
                                    fund.maximum_drawdown, fund.current_drawdown, fund.gz_drawdown])
            if fund.request_date != datetime.now().date() or not os.path.exists(os.path.join(watch_funds_dir, f'{fund.fs_code}.png')):
                plt.figure(1, figsize=(20, 20))
                plt.clf()
                plt.suptitle(f'{fund.fs_name}', fontsize=16, color='red')
                plt.subplot(331)
                draw_sly('jz_1y', fund.jz_1y, fund.jzl_1y)
                plt.subplot(332)
                draw_sly('jz_3y', fund.jz_3y, fund.jzl_3y)
                plt.subplot(333)
                draw_sly('jz_6y', fund.jz_6y, fund.jzl_6y)
                plt.subplot(334)
                draw_sly('jz_1n', fund.jz_1n, fund.jzl_1n)
                plt.subplot(335)
                draw_sly('jz_3n', fund.jz_3n, fund.jzl_3n)
                plt.subplot(336)
                draw_sly('jz_5n', fund.jz_5n, fund.jzl_5n)
                plt.subplot(337)
                draw_sly('jz_total', fund.jz_total, fund.jzl_total)
                plt.tight_layout()
                plt.subplots_adjust(top=0.95)
                plt.savefig(os.path.join(watch_funds_dir, f'{fund.fs_code}.png'))

        watch_funds_table = pd.DataFrame(watch_funds_table, columns = ['ID', '名称', '净值日期', '净值', '累计净值', '估值日期', '估值', 
                                                '估值率(%)', '累计估值', '最大回撤(%)', '当前回撤(%)', '估值回撤(%)'])
        watch_funds_table['最大回撤(%)'] = watch_funds_table['最大回撤(%)'].round(3)
        watch_funds_table['当前回撤(%)'] = watch_funds_table['当前回撤(%)'].round(3)
        watch_funds_table['估值回撤(%)'] = watch_funds_table['估值回撤(%)'].round(3)
        watch_funds_table.to_csv(os.path.join(args.data_space, 'watch_funds.csv'))
        for item in os.listdir(watch_funds_dir):
            fs_code = os.path.splitext(item)[0]
            if not fs_code in watch_funds_dict:
                os.remove(os.path.join(watch_funds_dir, item))

        print('updating...')

        shelve_last3_level = db.get('last3_level', None)
        shelve_last5_level = db.get('last5_level', None)
        if args.update_morning_star or shelve_last3_level != args.last3_level or shelve_last5_level != args.last5_level:
            filter_funds = filter_morning_star_funds(args.last3_level, args.last5_level)
        else:
            filter_funds = db['morning_star']

        morning_star_funds_queue = Queue()
        for fund in filter_funds:
            morning_star_funds_queue.put(fund[0])

        t_list = []
        for i in range(args.num_works):
            t = threading.Thread(target = thread_update, args=(morning_star_funds_queue, shelve_funds, morning_star_funds_dict))
            t_list.append(t)
            t.start()

        for t in t_list:
            t.join()

        for item in tqdm(filter_funds):
            fs_code, _, last3_level, last5_level = item
            fund = morning_star_funds_dict[fs_code]
            morning_star_funds_table.append([fund.fs_code, fund.fs_name, last3_level, last5_level,
                                    fund.jztime, fund.jsz, fund.ac_jsz, fund.gztime, fund.gsz, fund.gszzl, fund.ac_gsz, 
                                    fund.maximum_drawdown, fund.current_drawdown, fund.gz_drawdown])
            if fund.request_date != datetime.now().date() or not os.path.exists(os.path.join(morning_star_dir, f'{fund.fs_code}.png')):
                plt.figure(1, figsize=(20, 20))
                plt.clf()
                plt.suptitle(f'{fund.fs_name}', fontsize=16, color='red')
                plt.subplot(331)
                draw_sly('jz_1y', fund.jz_1y, fund.jzl_1y)
                plt.subplot(332)
                draw_sly('jz_3y', fund.jz_3y, fund.jzl_3y)
                plt.subplot(333)
                draw_sly('jz_6y', fund.jz_6y, fund.jzl_6y)
                plt.subplot(334)
                draw_sly('jz_1n', fund.jz_1n, fund.jzl_1n)
                plt.subplot(335)
                draw_sly('jz_3n', fund.jz_3n, fund.jzl_3n)
                plt.subplot(336)
                draw_sly('jz_5n', fund.jz_5n, fund.jzl_5n)
                plt.subplot(337)
                draw_sly('jz_total', fund.jz_total, fund.jzl_total)
                plt.tight_layout()
                plt.subplots_adjust(top=0.95)
                plt.savefig(os.path.join(morning_star_dir, f'{fund.fs_code}.png'))

        morning_star_funds_table = pd.DataFrame(morning_star_funds_table, columns = ['ID', '名称', '晨星等级(三年)', '晨星等级(五年)', 
            '净值日期', '净值', '累计净值', '估值日期', '估值', '估值率(%)', '累计估值', '最大回撤(%)', '当前回撤(%)', '估值回撤(%)'])
        morning_star_funds_table['最大回撤(%)'] = morning_star_funds_table['最大回撤(%)'].round(3)
        morning_star_funds_table['当前回撤(%)'] = morning_star_funds_table['当前回撤(%)'].round(3)
        morning_star_funds_table['估值回撤(%)'] = morning_star_funds_table['估值回撤(%)'].round(3)
        morning_star_funds_table.to_csv(os.path.join(args.data_space, 'morning_star.csv'))
        for item in os.listdir(morning_star_dir):
            fs_code = os.path.splitext(item)[0]
            if not fs_code in morning_star_funds_dict:
                os.remove(os.path.join(morning_star_dir, item))

        morning_star_funds_dict.update(watch_funds_dict)
        db['last3_level'] = args.last3_level
        db['last5_level'] = args.last5_level
        db['morning_star'] = filter_funds
        db['funds'] = morning_star_funds_dict
