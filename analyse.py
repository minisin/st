#!/usr/bin/python
# -*- coding: utf-8 -*-

import numpy as np
from matplotlib import pyplot

from stocks import Util, Stocks, Stock
from index import MACD, EMA, EMA2, Cross
from account import VirtualAccount


# 分析买卖股票的策略，数据概率统计
# 1. 入市策略
# (1) 某个入市点，后每一天的涨幅概率分布，涨幅平均值(期望涨幅)，方差，止损概率(亏损10%)
# (2) 入市包括: 1> 上穿某日均线 2> 均线金叉 3> 某日涨幅超平均波动 4> 回踩某均线 5> MACD金叉 6> 其他指标
# 2. 出市策略
# (1) 选定入市点, 止损出市， 止盈出市
# 3. 资金管理策略
# 1. 挑选盘整后，放量上涨的股票
# (1) 短，中期均线走平，
class Analyse(object):
    def __init__(self):
        self.in_market_analyse_days = 60   # 大约3个月
        self.stocks = Stocks()
        self.stocks.load_from_file('stock_data.dat')

    def analyse_in_market(self, in_market_stra, selected_stock_id = None):
        result_time = []
        result_time_stock = {}
        result_price_change = []
        for stock_id, stock in self.stocks.stock_list.items():
            #print stock_id
            if selected_stock_id == stock_id or not selected_stock_id:
                in_market_stra.reset()
                # 选定满足策略的入市时间
                for time_, price in stock.iter_tick():
                    if in_market_stra.update(price):
                        result_time.append(time_)
                        if stock_id not in result_time_stock: result_time_stock[stock_id] = []
                        result_time_stock[stock_id].append(time_)
                        # 根据每个入市时间，统计入市后的每日涨幅(相比入市点)
                        timeslice_price = stock.get_timeslice_close_price(time_, self.in_market_analyse_days)
                        start_price = timeslice_price[0]
                        result_price_change.append([100*(price/float(start_price)-1) if price else None for price in timeslice_price])
        price_len = len(result_price_change)
        result = []
        for price in zip(*result_price_change):
            assert len(price) == price_len, 'price error'
            price_set = set(price)
            if None in price_set: price_set.remove(None)
            price_array = np.array(tuple(price_set))
            # 求平均值和方差
            result.append((round(np.mean(price_array), 2), round(np.std(price_array), 2)))
        for stock_id, time_list in result_time_stock.items():
            print stock_id
            print time_list
        return result, result_time


    def analyse_trade(self, in_market_stra, out_market_stra, selected_stock_id = None):
        account = VirtualAccount()
        for stock_id, stock in self.stocks.stock_list.items():
            #print stock_id
            if selected_stock_id == stock_id or not selected_stock_id:
                in_market_stra.reset()
                out_market_stra.reset()
                market_status_in_market = False
                # 选定满足策略的入市时间
                for time_, price in stock.iter_tick():
                    in_market_trigger = in_market_stra.update(price)
                    out_market_trigger = out_market_stra.update(price)
                    if not market_status_in_market:  # 不在市场内, 寻找入市机会
                        if in_market_trigger:
                            account.buy_stock(stock_id, price[1], today = time_)  # close价格作为买入, 卖出价
                            market_status_in_market = True
                    else:
                        if out_market_trigger:
                            account.sell_stock(stock_id, price[1], today = time_)
                            market_status_in_market = False
        print account
        account.show()


# 某日单日涨幅 或跌幅
class RaiseBigStra(object):
    def __init__(self, raise_value, raise_report = True):
        self.raise_report = raise_report  # True: 上涨, False: 下跌
        self.raise_value = raise_value  # 幅度百分比
        self.reset()

    def reset(self):
        self.old_price = None

    def update(self, price):  # [open, close, high, low]
        in_market_trigger = False
        if price:
            o, c, h, l = price
            if self.old_price:
                price_raise = 100*(c / float(self.old_price) - 1)
                if self.raise_report and price_raise >= self.raise_value:
                    in_market_trigger = True
                elif not self.raise_report and price_raise <= self.raise_value:
                    in_market_trigger = True
            self.old_price = c
        return in_market_trigger


# 上穿, 下穿某日均线
class AvgLineCrossStra(object):
    def __init__(self, avg_days, up_cross_report = True):
        self.avg_days = avg_days
        self.up_cross_report = up_cross_report  # True: 上穿, False: 下穿
        self.reset()

    def reset(self):
        self.ema = EMA(self.avg_days)
        self.cross = Cross()
        self.direction = 0  # 0: invalid, 1: top 2: bottom

    def update(self, price):  # [open, close, high, low]
        in_market_trigger = False
        if price:
            o, c, h, l = price
            avg_value = self.ema.update(c)
            cross = self.cross.update(c, avg_value)
            if (cross == 'gold' and self.up_cross_report) or (cross == 'dead' and not self.up_cross_report):
                in_market_trigger = True
        return in_market_trigger


class TwoAvgLineCrossStra(object):
    def __init__(self, short_days, long_days, up_cross_report = True):
        self.ema2_param = (short_days, long_days)
        self.up_cross_report = up_cross_report
        self.reset()

    def reset(self):
        self.ema2 = EMA2(*self.ema2_param)
        self.direction = 0  # 0: invalid, 1: top 2: bottom

    def update(self, price):  # [open, close, high, low]
        in_market_trigger = False
        if price:
            o, c, h, l = price
            avg_value, cross = self.ema2.update(c)
            if (cross == 'gold' and self.up_cross_report) or (cross == 'dead' and not self.up_cross_report):
                in_market_trigger = True
        return in_market_trigger


# MACD背离
class MacdDeviationStra(object):
    def __init__(self, gold_cross_report = True, short_days = 12, long_days = 26, dif_days = 9, price_dev = (-0.1, 0), dif_dev = 0.5, last_dif = 3):
        self.macd_para = (short_days, long_days, dif_days)
        self.gold_cross_report = gold_cross_report
        self.price_dev = price_dev
        self.dif_dev = dif_dev
        self.last_dif = last_dif
        self.reset()

    def reset(self):
        self.macd = MACD(*self.macd_para)
        self.low_prices = []
        self.high_prices = []
        self.last_gold_cross_dif = []
        self.last_dead_cross_dif = []
        self.last_cross = None

    # price: [open, close, high, low]
    def update(self, price):
        macd_deviation = None
        if price:
            o, c, h, l = price
            macd_price, macd_dif, macd_cross = self.macd.update(c)
            if macd_cross == 'gold':
                if macd_dif < 0 and self.low_prices:
                    lowest_price = min(self.low_prices)
                    min_dif = -1  # maximum value
                    for p, dif in self.last_gold_cross_dif[::-1]:
                        #print float(lowest_price - p)/p, float(macd_dif)
                        if self.price_dev[0] < float(lowest_price - p) / p < self.price_dev[1] and float(macd_dif) / dif < self.dif_dev and dif < min_dif:
                            #print price, self.last_gold_cross_dif, lowest_price, p, dif, macd_dif
                            macd_deviation = 'gold'
                            break
                        min_dif = min(min_dif, dif)
                    self.last_gold_cross_dif.append((lowest_price, macd_dif))
                    if len(self.last_gold_cross_dif) > self.last_dif:
                        self.last_gold_cross_dif.pop(0)
                self.last_cross = macd_cross
                self.high_prices = []
            elif macd_cross == 'dead':
                if macd_dif > 0 and self.high_prices:
                    highest_price = max(self.high_prices)
                    max_dif = 1   # minimum value
                    for p, dif in self.last_dead_cross_dif[::-1]:
                        if self.price_dev[0] < float(highest_price - p) / p < self.price_dev[1] and float(macd_dif) / dif < self.dif_dev and dif > max_dif:
                            macd_deviation = 'dead'
                            break
                        max_dif = max(max_dif, dif)
                    self.last_dead_cross_dif.append((highest_price, macd_dif))
                    if len(self.last_dead_cross_dif) > self.last_dif:
                        self.last_dead_cross_dif.pop(0)
                self.last_cross = macd_cross
                self.low_prices = []

            if self.last_cross == 'gold':
                self.high_prices.append(h)
            elif self.last_cross == 'dead':
                self.low_prices.append(l)
        return macd_deviation == 'gold' if self.gold_cross_report else macd_deviation == 'dead'


if __name__ == '__main__':
    test = 2
    if test == 1:
        analyse = Analyse()
        #stra = RaiseBigStra(9)  # 8% raise
        #stra = RaiseBigStra(-8, False)  # 8% drop
        #stra = AvgLineCrossStra(120)
        stra = MacdDeviationStra()
        #stra = AvgLineCrossStra(120, False)
        #result,result_time = analyse.analyse_in_market(stra, selected_stock_id = '999999')
        result,result_time = analyse.analyse_in_market(stra)
        result_time_1 = list(set(result_time))
        result_time_1.sort()
        result = zip(*result)
        print result
        print len(result_time), len(result_time_1)
        print result_time_1
        if False:
            pyplot.figure()
            pyplot.plot(result[0], '*-')
            pyplot.plot(result[1], 'r*-')
            pyplot.grid(True)
            pyplot.show()
    elif test == 2:
        analyse = Analyse()
        in_stra = MacdDeviationStra()
        #in_stra = AvgLineCrossStra(20, up_cross_report = True)
        #in_stra = TwoAvgLineCrossStra(10, 60)
        out_stra = TwoAvgLineCrossStra(5, 20, up_cross_report = False)
        #out_stra = AvgLineCrossStra(20, up_cross_report = False)
        analyse.analyse_trade(in_stra, out_stra)


