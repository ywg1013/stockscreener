#!/usr/bin/env python3
"""
A股净利润高增长 + 近期涨停 + 低估值筛选脚本
筛选条件：
1. 非ST股票
2. 业绩增长：最近2年年度净利润同比增长率均 > 20% 或 最近连续2个季度净利润同比增长率均 > 20%
3. 活跃度：最近一个月有涨停记录
4. 技术形态：当日收盘价不低于20日均价
5. 估值约束(新增)：市盈率(PE)在 0 到 1000 之间（排除亏损及超高估值）

数据来源：东方财富（通过AKShare）
"""

import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import sys
import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

# ============ 配置区 ============
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
SENDER_EMAIL = "281003252@qq.com"
RECEIVER_EMAIL = "281003252@qq.com"
QQ_AUTH_CODE = os.environ.get("QQ_AUTH_CODE", "")

# 配置日志
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, f'stock_filter_{datetime.now().strftime("%Y%m%d")}.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def get_report_periods():
    today = datetime.now()
    year = today.year
    month = today.month

    if month >= 5:
        latest_annual_year = year - 1
    else:
        latest_annual_year = year - 2

    annual_periods = [
        f"{latest_annual_year - 1}1231",
        f"{latest_annual_year}1231",
    ]

    if month >= 11:
        quarterly_periods = [f"{year}0630", f"{year}0930"]
    elif month >= 9:
        quarterly_periods = [f"{year}0630", f"{year}0930"]
    elif month >= 5:
        quarterly_periods = [f"{year - 1}1231", f"{year}0331"]
    else:
        quarterly_periods = [f"{year - 1}0930", f"{year - 1}1231"]

    logger.info(f"年度报告期: {annual_periods}")
    logger.info(f"季度报告期: {quarterly_periods}")
    return annual_periods, quarterly_periods


def fetch_yjbb(date_str, retries=3):
    for attempt in range(retries):
        try:
            df = ak.stock_yjbb_em(date=date_str)
            return df
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(5)
            else:
                return None


def clean_data(df):
    if df is None or df.empty:
        return pd.DataFrame()
    df = df[~df['股票简称'].str.contains('ST|退', na=False)]
    df = df[df['股票代码'].str.match(r'^[036]')]
    df['净利润-同比增长'] = pd.to_numeric(df['净利润-同比增长'], errors='coerce')
    return df


def filter_annual_growth(annual_periods):
    logger.info("开始筛选：年度净利润连续2年增长>20%")
    dfs = {}
    for period in annual_periods:
        df = fetch_yjbb(period)
        if df is not None:
            dfs[period] = clean_data(df)
        time.sleep(1)

    if len(dfs) < 2: return pd.DataFrame()

    result_codes = None
    for _, df in dfs.items():
        growth_stocks = df[df['净利润-同比增长'] > 20]['股票代码'].unique()
        if result_codes is None: result_codes = set(growth_stocks)
        else: result_codes &= set(growth_stocks)

    latest_period = max(dfs.keys())
    result_df = dfs[latest_period][dfs[latest_period]['股票代码'].isin(result_codes)].copy()
    result_df['筛选条件'] = '年度连续2年增长>20%'
    return result_df


def filter_quarterly_growth(quarterly_periods):
    logger.info("开始筛选：连续2个季度净利润增长>20%")
    dfs = {}
    for period in quarterly_periods:
        df = fetch_yjbb(period)
        if df is not None:
            dfs[period] = clean_data(df)
        time.sleep(1)

    if len(dfs) < 2: return pd.DataFrame()

    result_codes = None
    for _, df in dfs.items():
        growth_stocks = df[df['净利润-同比增长'] > 20]['股票代码'].unique()
        if result_codes is None: result_codes = set(growth_stocks)
        else: result_codes &= set(growth_stocks)

    latest_period = max(dfs.keys())
    result_df = dfs[latest_period][dfs[latest_period]['股票代码'].isin(result_codes)].copy()
    result_df['筛选条件'] = '连续2季度增长>20%'
    return result_df


def merge_growth_results(annual_df, quarterly_df):
    key_cols = ['股票代码', '股票简称', '每股收益', '净利润-净利润', '净利润-同比增长',
                '营业总收入-营业总收入', '营业总收入-同比增长', '净资产收益率',
                '销售毛利率', '所处行业', '筛选条件']
    all_dfs = []
    if not annual_df.empty: all_dfs.append(annual_df[[c for c in key_cols if c in annual_df.columns]])
    if not quarterly_df.empty: all_dfs.append(quarterly_df[[c for c in key_cols if c in quarterly_df.columns]])
    if not all_dfs: return pd.DataFrame()

    merged = pd.concat(all_dfs, ignore_index=True)
    condition_map = merged.groupby('股票代码')['筛选条件'].apply(lambda x: '；'.join(x.unique())).to_dict()
    merged = merged.drop_duplicates(subset=['股票代码'], keep='first')
    merged['筛选条件'] = merged['股票代码'].map(condition_map)
    return merged.sort_values('净利润-同比增长', ascending=False)


def get_ma20_and_close(codes):
    logger.info("开始筛选：当日收盘价不低于20日均价")
    if not codes: return set()
    passed_codes = set()
    import requests as req
    for i, code in enumerate(codes):
        try:
            prefix = 'sh' if code.startswith('6') else 'sz'
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,30,qfq"
            resp = req.get(url, timeout=5)
            data = resp.json()
            key = f"{prefix}{code}"
            raw = data['data'][key].get('qfqday', data['data'][key].get('day', []))
            closes = [float(r[2]) for r in raw if len(r) >= 3]
            if len(closes) >= 20:
                if closes[-1] >= (sum(closes[-20:]) / 20):
                    passed_codes.add(code)
        except: pass
        if (i + 1) % 50 == 0: time.sleep(0.5)
    return passed_codes


def apply_pe_filter(df):
    """
    新增筛选：排除市盈率 > 1000 以及 < 0 的股票
    """
    logger.info("=" * 60)
    logger.info("开始筛选：市盈率过滤 (0 < PE < 1000)")
    logger.info("=" * 60)
    if df.empty: return df

    try:
        spot_df = ak.stock_zh_a_spot_em()
        # '市盈率-动态' 是实时估值的常用指标
        # 部分个股可能没有动态PE（如新股或亏损），'市盈率'列通常包含滚动PE
        pe_col = '市盈率-动态' if '市盈率-动态' in spot_df.columns else '市盈率'
        pe_data = spot_df[['代码', pe_col]].copy()
        pe_data.columns = ['股票代码', '市盈率']
        
        # 转换并合并
        pe_data['市盈率'] = pd.to_numeric(pe_data['市盈率'], errors='coerce')
        df = df.merge(pe_data, on='股票代码', how='left')
        
        before_count = len(df)
        # 筛选：PE >= 0 且 PE <= 1000 (排除亏损股和市盈率过高的泡沫股)
        # 对于 NaN (无法获取PE的股票)，建议保留或剔除根据实际情况，这里选择剔除以保证质量
        filtered_df = df[(df['市盈率'] > 0) & (df['市盈率'] < 1000)].copy()
        
        after_count = len(filtered_df)
        logger.info(f"市盈率筛选前: {before_count}只, 筛选后: {after_count}只, 过滤掉: {before_count - after_count}只")
        return filtered_df
    except Exception as e:
        logger.error(f"获取市盈率数据失败: {e}")
        return df


def fetch_zt_pool_month():
    logger.info("获取最近一个月涨停记录")
    trade_dates_df = ak.tool_trade_date_hist_sina()
    trade_dates_df['trade_date'] = pd.to_datetime(trade_dates_df['trade_date'])
    one_month_ago = datetime.now() - timedelta(days=30)
    recent_dates = trade_dates_df[(trade_dates_df['trade_date'] >= one_month_ago) & (trade_dates_df['trade_date'] <= datetime.now())]['trade_date'].tolist()
    
    all_zt_codes = set()
    zt_detail_list = []
    for trade_date in recent_dates:
        try:
            df = ak.stock_zt_pool_em(date=trade_date.strftime('%Y%m%d'))
            if df is not None and not df.empty:
                codes = df['代码'].tolist()
                names = df['名称'].tolist() if '名称' in df.columns else [''] * len(codes)
                all_zt_codes.update(codes)
                for code, name in zip(codes, names):
                    zt_detail_list.append({'股票代码': code, '股票简称': name, '涨停日期': trade_date.strftime('%Y-%m-%d')})
        except: pass
        time.sleep(0.3)
    
    zt_stats = pd.DataFrame(zt_detail_list).groupby(['股票代码', '股票简称']).agg(涨停次数=('涨停日期', 'count'), 最近涨停日期=('涨停日期', 'max')).reset_index() if zt_detail_list else pd.DataFrame()
    return all_zt_codes, zt_stats


def main():
    start_time = time.time()
    try:
        # 1. 增长筛选
        annual_p, quarterly_p = get_report_periods()
        growth_df = merge_growth_results(filter_annual_growth(annual_p), filter_quarterly_growth(quarterly_p))
        if growth_df.empty: return

        # 2. 市盈率初步筛选 (核心改动)
        growth_df = apply_pe_filter(growth_df)

        # 3. 涨停记录合并
        zt_codes, zt_stats = fetch_zt_pool_month()
        result_df = growth_df[growth_df['股票代码'].isin(zt_codes)].copy()
        if not zt_stats.empty and not result_df.empty:
            result_df = result_df.merge(zt_stats[['股票代码', '涨停次数', '最近涨停日期']], on='股票代码', how='left')

        # 4. MA20 筛选
        if not result_df.empty:
            ma20_codes = get_ma20_and_close(result_df['股票代码'].tolist())
            result_df = result_df[result_df['股票代码'].isin(ma20_codes)]

        # 5. 保存与摘要
        if not result_df.empty:
            output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
            os.makedirs(output_dir, exist_ok=True)
            result_df.to_csv(os.path.join(output_dir, f'stock_filtered_{datetime.now().strftime("%Y%m%d")}.csv'), index=False, encoding='utf-8-sig')
            logger.info(f"筛选完成，共 {len(result_df)} 只股票")
            print(result_df.head())
        
        logger.info(f"运行总时长: {time.time() - start_time:.1f}秒")
    except Exception as e:
        logger.error(f"脚本出错: {e}")

if __name__ == '__main__':
    main()
