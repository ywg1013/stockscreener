#!/usr/bin/env python3
"""
A股净利润高增长 + 近期涨停 股票筛选脚本
筛选条件：
1. 非ST股票
2. 条件A：最近2年年度净利润同比增长率均 > 20%
   条件B：最近连续2个季度净利润同比增长率均 > 20%
   满足条件A或条件B即可
3. 最近一个月有涨停记录
4. 当日收盘价不低于20日均价
5. 市盈率(PE-TTM)在0~500之间（排除亏损股和估值泡沫）

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
# 邮件发送配置（使用QQ邮箱SMTP）
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
SENDER_EMAIL = "281003252@qq.com"        # 发件人QQ邮箱
RECEIVER_EMAIL = "281003252@qq.com"       # 收件人邮箱
# QQ邮箱授权码（非QQ密码，需在QQ邮箱设置中开启SMTP并获取授权码）
# 请将下面的xxx替换为你的QQ邮箱授权码
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
    """
    根据当前日期，自动判断可用的报告期
    返回：年度报告期列表、季度报告期列表
    """
    today = datetime.now()
    year = today.year
    month = today.month

    # 确定最新的已披露年报年份
    if month >= 5:
        latest_annual_year = year - 1
    else:
        latest_annual_year = year - 2

    # 两年年度报告期
    annual_periods = [
        f"{latest_annual_year - 1}1231",
        f"{latest_annual_year}1231",
    ]

    # 确定最近的季度报告期
    if month >= 11:
        quarterly_periods = [f"{year}0630", f"{year}0930"]
    elif month >= 9:
        quarterly_periods = [f"{year}0630", f"{year}0930"]
    elif month >= 5:
        quarterly_periods = [f"{year - 1}1231", f"{year}0331"]
    else:
        quarterly_periods = [f"{year - 1}0930", f"{year - 1}1231"]

    logger.info(f"当前日期: {today.strftime('%Y-%m-%d')}")
    logger.info(f"年度报告期: {annual_periods}")
    logger.info(f"季度报告期: {quarterly_periods}")

    return annual_periods, quarterly_periods


def fetch_yjbb(date_str, retries=3):
    """获取业绩报表数据，带重试机制"""
    for attempt in range(retries):
        try:
            logger.info(f"正在获取业绩报表: {date_str} (尝试 {attempt + 1}/{retries})")
            df = ak.stock_yjbb_em(date=date_str)
            logger.info(f"获取 {date_str} 数据成功，共 {len(df)} 条记录")
            return df
        except Exception as e:
            logger.warning(f"获取 {date_str} 数据失败: {e}")
            if attempt < retries - 1:
                time.sleep(5)
            else:
                logger.error(f"获取 {date_str} 数据最终失败，跳过该报告期")
                return None


def clean_data(df):
    """清洗数据：排除ST、退市，只保留沪深A股"""
    if df is None or df.empty:
        return pd.DataFrame()

    # 排除ST、*ST、退市股票
    df = df[~df['股票简称'].str.contains('ST|退', na=False)]

    # 只保留沪深A股（6/0/3开头）
    df = df[df['股票代码'].str.match(r'^[036]')]

    # 确保净利润同比增长为数值
    df['净利润-同比增长'] = pd.to_numeric(df['净利润-同比增长'], errors='coerce')

    return df


def filter_annual_growth(annual_periods):
    """筛选条件A：最近2年年度净利润同比增长率均 > 20%"""
    logger.info("=" * 60)
    logger.info("开始筛选：年度净利润连续2年增长>20%")
    logger.info("=" * 60)

    dfs = {}
    for period in annual_periods:
        df = fetch_yjbb(period)
        if df is not None:
            dfs[period] = clean_data(df)
        time.sleep(2)

    if len(dfs) < 2:
        logger.warning("年度数据不足2期，无法进行年度筛选")
        return pd.DataFrame()

    result_codes = None
    for period, df in dfs.items():
        growth_stocks = df[df['净利润-同比增长'] > 20]['股票代码'].unique()
        logger.info(f"报告期 {period}: 净利润同比增长>20%的股票数 = {len(growth_stocks)}")
        if result_codes is None:
            result_codes = set(growth_stocks)
        else:
            result_codes &= set(growth_stocks)

    logger.info(f"连续2年年度净利润增长>20%的股票数: {len(result_codes)}")

    latest_period = max(dfs.keys())
    latest_df = dfs[latest_period]
    result_df = latest_df[latest_df['股票代码'].isin(result_codes)].copy()
    result_df['筛选条件'] = '年度连续2年增长>20%'

    return result_df


def filter_quarterly_growth(quarterly_periods):
    """筛选条件B：连续2个季度净利润同比增长率均 > 20%"""
    logger.info("=" * 60)
    logger.info("开始筛选：连续2个季度净利润增长>20%")
    logger.info("=" * 60)

    dfs = {}
    for period in quarterly_periods:
        df = fetch_yjbb(period)
        if df is not None:
            dfs[period] = clean_data(df)
        time.sleep(2)

    if len(dfs) < 2:
        logger.warning("季度数据不足2期，无法进行季度筛选")
        return pd.DataFrame()

    result_codes = None
    for period, df in dfs.items():
        growth_stocks = df[df['净利润-同比增长'] > 20]['股票代码'].unique()
        logger.info(f"报告期 {period}: 净利润同比增长>20%的股票数 = {len(growth_stocks)}")
        if result_codes is None:
            result_codes = set(growth_stocks)
        else:
            result_codes &= set(growth_stocks)

    logger.info(f"连续2季度净利润增长>20%的股票数: {len(result_codes)}")

    latest_period = max(dfs.keys())
    latest_df = dfs[latest_period]
    result_df = latest_df[latest_df['股票代码'].isin(result_codes)].copy()
    result_df['筛选条件'] = '连续2季度增长>20%'

    return result_df


def merge_growth_results(annual_df, quarterly_df):
    """合并两个增长筛选条件的结果"""
    key_cols = ['股票代码', '股票简称', '每股收益', '净利润-净利润', '净利润-同比增长',
                '营业总收入-营业总收入', '营业总收入-同比增长', '净资产收益率',
                '销售毛利率', '所处行业', '筛选条件']

    all_dfs = []
    if not annual_df.empty:
        available_cols = [c for c in key_cols if c in annual_df.columns]
        all_dfs.append(annual_df[available_cols])
    if not quarterly_df.empty:
        available_cols = [c for c in key_cols if c in quarterly_df.columns]
        all_dfs.append(quarterly_df[available_cols])

    if not all_dfs:
        return pd.DataFrame()

    merged = pd.concat(all_dfs, ignore_index=True)

    # 同一只股票可能同时满足两个条件，合并筛选条件
    if '股票代码' in merged.columns and '筛选条件' in merged.columns:
        condition_map = merged.groupby('股票代码')['筛选条件'].apply(lambda x: '；'.join(x.unique())).to_dict()
        merged = merged.drop_duplicates(subset=['股票代码'], keep='first')
        merged['筛选条件'] = merged['股票代码'].map(condition_map)

    merged = merged.sort_values('净利润-同比增长', ascending=False).reset_index(drop=True)

    return merged


def get_pe_filter(codes):
    """获取股票市盈率(PE-TTM)，筛选0 < PE <= 500的股票"""
    logger.info("=" * 60)
    logger.info("开始筛选：市盈率 0 < PE <= 500")
    logger.info("=" * 60)

    if not codes:
        logger.warning("股票代码列表为空，跳过PE筛选")
        return set()

    passed_codes = set()
    total = len(codes)
    codes_list = list(codes)

    # 使用腾讯财经API获取市盈率
    import requests as req
    batch_size = 100  # 每批100只股票

    for batch_start in range(0, len(codes_list), batch_size):
        batch = codes_list[batch_start:batch_start + batch_size]

        # 构建股票代码字符串: sh600000,sz000001
        stock_codes = []
        for code in batch:
            if code.startswith('6'):
                stock_codes.append(f"sh{code}")
            elif code.startswith('3') or code.startswith('0'):
                stock_codes.append(f"sz{code}")
            else:
                stock_codes.append(f"sh{code}")

        codes_str = ','.join(stock_codes)
        url = f"https://qt.gtimg.cn/q={codes_str}"

        try:
            resp = req.get(url, timeout=30)
            resp.encoding = 'utf-8'
            text = resp.text

            # 解析返回数据
            lines = text.strip().split('\n')
            for line in lines:
                if not line.strip():
                    continue

                parts = line.split('~')
                if len(parts) < 40:
                    continue

                # 提取代码（去掉前缀）
                raw_code = parts[2]  # 位置2是代码
                pe_str = parts[39]   # 位置39是PEttm

                if not raw_code or not pe_str:
                    continue

                try:
                    pe_val = float(pe_str) if pe_str != '-' else None
                    if pe_val is not None and 0 < pe_val <= 500:
                        passed_codes.add(raw_code)
                        logger.debug(f"  ✅ {raw_code}: PE={pe_val:.2f}")
                    elif pe_val is None or pe_val == '-':
                        logger.debug(f"  ❌ {raw_code}: PE=未知")
                    else:
                        logger.debug(f"  ❌ {raw_code}: PE={pe_val:.2f} (不在0~500范围)")
                except (ValueError, TypeError) as e:
                    logger.debug(f"  ❌ {raw_code}: PE={pe_str} (解析错误: {e})")
        except Exception as e:
            logger.warning(f"  获取市盈率批次 {batch_start//batch_size + 1} 失败: {e}")

        logger.info(f"  市盈率筛选进度: {min(batch_start + batch_size, total)}/{total}")
        time.sleep(0.2)

    logger.info(f"0 < PE <= 500的股票数: {len(passed_codes)}/{total}")
    return passed_codes


def apply_pe_filter(df, pe_codes):
    """在已有筛选结果上，进一步筛选0 < 市盈率 <= 500的股票"""
    logger.info("=" * 60)
    logger.info("应用筛选：市盈率 0 < PE <= 500")
    logger.info("=" * 60)

    if df.empty:
        logger.warning("输入数据为空，跳过市盈率筛选")
        return df

    before_count = len(df)
    filtered_df = df[df['股票代码'].isin(pe_codes)].copy()
    after_count = len(filtered_df)

    logger.info(f"筛选前: {before_count}只, 筛选后: {after_count}只, 过滤掉: {before_count - after_count}只")

    return filtered_df


def get_ma20_and_close(codes):
    """
    获取股票当日收盘价和20日均价，筛选收盘价>=20日均价的股票
    使用新浪财经实时行情API
    """
    logger.info("=" * 60)
    logger.info("开始筛选：当日收盘价不低于20日均价")
    logger.info("=" * 60)

    if not codes:
        logger.warning("股票代码列表为空，跳过MA20筛选")
        return set()

    passed_codes = set()
    total = len(codes)

    # 使用腾讯财经API获取K线数据计算MA20
    import requests as req

    for i, code in enumerate(codes):
        try:
            # 确定市场前缀
            if code.startswith('6'):
                prefix = 'sh'
            elif code.startswith('3') or code.startswith('0'):
                prefix = 'sz'
            else:
                prefix = 'sh'

            # 获取近30天日K线（前复权）
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,30,qfq"
            resp = req.get(url, timeout=10)
            data = resp.json()
            key = f"{prefix}{code}"
            raw = data['data'][key].get('qfqday', data['data'][key].get('day', []))

            if len(raw) < 20:
                logger.debug(f"  {code} K线数据不足20天，跳过")
                continue

            # 提取收盘价
            closes = []
            for r in raw:
                if len(r) >= 4:
                    closes.append(float(r[2]))  # close在第3列
                elif len(r) >= 3:
                    closes.append(float(r[2]))

            if len(closes) < 20:
                continue

            # 当日收盘价（最后一天）
            close_today = closes[-1]
            # 20日均价
            ma20 = sum(closes[-20:]) / 20

            if close_today >= ma20:
                passed_codes.add(code)
                logger.debug(f"  ✅ {code}: 收盘价={close_today:.2f}, MA20={ma20:.2f}, 偏离={((close_today-ma20)/ma20*100):.2f}%")
            else:
                logger.debug(f"  ❌ {code}: 收盘价={close_today:.2f}, MA20={ma20:.2f}, 偏离={((close_today-ma20)/ma20*100):.2f}%")

        except Exception as e:
            logger.debug(f"  {code}: 获取MA20数据失败 - {e}")

        # 控制请求频率，每50只休息1秒
        if (i + 1) % 50 == 0:
            logger.info(f"  MA20筛选进度: {i+1}/{total}")
            time.sleep(0.5)

    logger.info(f"收盘价>=MA20的股票数: {len(passed_codes)}/{total}")
    return passed_codes


def apply_ma20_filter(df, ma20_codes):
    """在已有筛选结果上，进一步筛选收盘价>=20日均价的股票"""
    logger.info("=" * 60)
    logger.info("应用筛选：收盘价不低于20日均价")
    logger.info("=" * 60)

    if df.empty:
        logger.warning("输入数据为空，跳过MA20筛选")
        return df

    before_count = len(df)
    filtered_df = df[df['股票代码'].isin(ma20_codes)].copy()
    after_count = len(filtered_df)

    logger.info(f"筛选前: {before_count}只, 筛选后: {after_count}只, 过滤掉: {before_count - after_count}只")

    return filtered_df


def fetch_zt_pool_month():
    """
    获取最近一个月所有涨停股票代码集合
    逐日获取涨停池数据，汇总去重
    """
    logger.info("=" * 60)
    logger.info("开始获取：最近一个月涨停记录")
    logger.info("=" * 60)

    # 获取交易日历
    trade_dates_df = ak.tool_trade_date_hist_sina()
    trade_dates_df['trade_date'] = pd.to_datetime(trade_dates_df['trade_date'])

    # 筛选最近一个月的交易日
    one_month_ago = datetime.now() - timedelta(days=30)
    today = datetime.now()
    recent_dates = trade_dates_df[
        (trade_dates_df['trade_date'] >= one_month_ago) &
        (trade_dates_df['trade_date'] <= today)
    ]['trade_date'].tolist()

    logger.info(f"最近一个月交易日数: {len(recent_dates)}")

    # 逐日获取涨停数据
    all_zt_codes = set()
    zt_detail_list = []  # 记录每只股票的涨停次数和日期

    for i, trade_date in enumerate(recent_dates):
        date_str = trade_date.strftime('%Y%m%d')
        try:
            df = ak.stock_zt_pool_em(date=date_str)
            if df is not None and not df.empty:
                codes = df['代码'].tolist()
                names = df['名称'].tolist() if '名称' in df.columns else [''] * len(codes)
                new_codes = set(codes) - all_zt_codes
                all_zt_codes.update(codes)
                # 记录涨停详情
                for code, name in zip(codes, names):
                    zt_detail_list.append({
                        '股票代码': code,
                        '股票简称': name,
                        '涨停日期': trade_date.strftime('%Y-%m-%d')
                    })
                logger.info(f"  {date_str}: {len(codes)} 只涨停 (新增: {len(new_codes)}, 累计: {len(all_zt_codes)})")
            else:
                logger.info(f"  {date_str}: 无涨停数据")
        except Exception as e:
            logger.warning(f"  {date_str}: 获取失败 - {e}")

        time.sleep(0.5)  # 控制请求频率

    logger.info(f"最近一个月涨停股票去重总数: {len(all_zt_codes)}")

    # 构建涨停统计 DataFrame
    if zt_detail_list:
        zt_detail_df = pd.DataFrame(zt_detail_list)
        zt_stats = zt_detail_df.groupby(['股票代码', '股票简称']).agg(
            涨停次数=('涨停日期', 'count'),
            最近涨停日期=('涨停日期', 'max'),
            涨停日期列表=('涨停日期', lambda x: ','.join(sorted(x.unique())))
        ).reset_index()
        logger.info(f"涨停统计表构建完成，共 {len(zt_stats)} 只股票")
    else:
        zt_stats = pd.DataFrame()

    return all_zt_codes, zt_stats


def apply_zt_filter(growth_df, zt_codes, zt_stats):
    """
    在增长筛选结果上，进一步筛选最近一个月有涨停记录的股票
    """
    logger.info("=" * 60)
    logger.info("开始筛选：净利润高增长 + 近期涨停")
    logger.info("=" * 60)

    if growth_df.empty:
        logger.warning("增长筛选结果为空，无法进行涨停筛选")
        return pd.DataFrame()

    # 取交集：净利润高增长 且 近一个月有涨停
    filtered_df = growth_df[growth_df['股票代码'].isin(zt_codes)].copy()

    logger.info(f"净利润高增长股票数: {len(growth_df)}")
    logger.info(f"近一个月涨停股票数: {len(zt_codes)}")
    logger.info(f"交集（高增长+涨停）: {len(filtered_df)}")

    # 合并涨停统计信息
    if not zt_stats.empty and not filtered_df.empty:
        filtered_df = filtered_df.merge(
            zt_stats[['股票代码', '涨停次数', '最近涨停日期', '涨停日期列表']],
            on='股票代码',
            how='left'
        )

    # 按涨停次数降序、净利润增长率降序排列
    if '涨停次数' in filtered_df.columns:
        filtered_df = filtered_df.sort_values(
            ['涨停次数', '净利润-同比增长'],
            ascending=[False, False]
        ).reset_index(drop=True)
    else:
        filtered_df = filtered_df.sort_values(
            '净利润-同比增长', ascending=False
        ).reset_index(drop=True)

    return filtered_df


def format_output(df):
    """格式化输出结果"""
    if df.empty:
        return pd.DataFrame()

    output = df.copy()
    if '净利润-同比增长' in output.columns:
        output['净利润-同比增长'] = output['净利润-同比增长'].apply(lambda x: f"{x:.2f}%" if pd.notna(x) else "")
    if '营业总收入-同比增长' in output.columns:
        output['营业总收入-同比增长'] = output['营业总收入-同比增长'].apply(lambda x: f"{x:.2f}%" if pd.notna(x) else "")
    if '净资产收益率' in output.columns:
        output['净资产收益率'] = output['净资产收益率'].apply(lambda x: f"{x:.2f}%" if pd.notna(x) else "")
    if '销售毛利率' in output.columns:
        output['销售毛利率'] = output['销售毛利率'].apply(lambda x: f"{x:.2f}%" if pd.notna(x) else "")
    if '每股收益' in output.columns:
        output['每股收益'] = output['每股收益'].apply(lambda x: f"{x:.4f}" if pd.notna(x) else "")
    if '净利润-净利润' in output.columns:
        output['净利润-净利润'] = output['净利润-净利润'].apply(lambda x: f"{x/1e8:.2f}亿" if pd.notna(x) and x != 0 else "")
    if '营业总收入-营业总收入' in output.columns:
        output['营业总收入-营业总收入'] = output['营业总收入-营业总收入'].apply(lambda x: f"{x/1e8:.2f}亿" if pd.notna(x) and x != 0 else "")

    return output


def save_results(df, output_dir):
    """保存结果到文件"""
    os.makedirs(output_dir, exist_ok=True)
    date_str = datetime.now().strftime('%Y%m%d')

    # 保存CSV
    csv_path = os.path.join(output_dir, f'stock_growth_zt_{date_str}.csv')
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    logger.info(f"CSV已保存: {csv_path}")

    # 保存Excel
    excel_path = os.path.join(output_dir, f'stock_growth_zt_{date_str}.xlsx')
    try:
        formatted_df = format_output(df)
        formatted_df.to_excel(excel_path, index=False, engine='openpyxl')
        logger.info(f"Excel已保存: {excel_path}")
    except Exception as e:
        logger.warning(f"保存Excel失败: {e}")
        excel_path = csv_path

    return csv_path, excel_path


def generate_email_html(df):
    """生成邮件HTML内容"""
    date_str = datetime.now().strftime('%Y年%m月%d日')

    if df.empty:
        html = f"""
        <html>
        <head><style>
            body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; padding: 20px; color: #333; }}
        </style></head>
        <body>
            <h2>A股净利润高增长+近期涨停 筛选结果</h2>
            <p>日期：{date_str}</p>
            <p>今日无满足筛选条件的股票。</p>
        </body>
        </html>
        """
        return html

    formatted = format_output(df)

    # 构建表格列
    display_cols = []
    col_headers = []
    col_map = {
        '股票代码': '股票代码',
        '股票简称': '股票简称',
        '净利润-同比增长': '净利润同比增长',
        '所处行业': '行业',
        '涨停次数': '月涨停次数',
        '最近涨停日期': '最近涨停',
        '筛选条件': '增长条件',
    }
    for col, header in col_map.items():
        if col in formatted.columns:
            display_cols.append(col)
            col_headers.append(header)

    # 构建表格行
    rows_html = ""
    for _, row in formatted.iterrows():
        row_cells = ""
        for col in display_cols:
            val = row[col] if pd.notna(row[col]) else ""
            row_cells += f"<td style='padding:6px 10px;border:1px solid #ddd;'>{val}</td>"
        rows_html += f"<tr>{row_cells}</tr>"

    html = f"""
    <html>
    <head><style>
        body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; padding: 20px; color: #333; }}
        h2 {{ color: #c0392b; border-bottom: 2px solid #c0392b; padding-bottom: 8px; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 15px; font-size: 13px; }}
        th {{ background-color: #2c3e50; color: white; padding: 8px 10px; text-align: center; border: 1px solid #ddd; }}
        tr:nth-child(even) {{ background-color: #f9f9f9; }}
        tr:hover {{ background-color: #eef; }}
        .summary {{ margin: 15px 0; padding: 12px; background: #fef9e7; border-left: 4px solid #f39c12; border-radius: 4px; }}
    </style></head>
    <body>
        <h2>A股净利润高增长 + 近期涨停 筛选结果</h2>
        <p>日期：{date_str}</p>
        <div class="summary">
            <strong>筛选条件：</strong><br>
            1. 非ST股票<br>
            2. 最近2年年度净利润同比增长均 &gt; 20% 或 连续2季度净利润同比增长均 &gt; 20%<br>
            3. 最近一个月有涨停记录<br>
            4. 当日收盘价不低于20日均价<br>
            5. 市盈率(PE-TTM)在0~500之间（排除亏损股和估值泡沫）<br>
            <strong>符合条件的股票数：{len(df)}</strong>
        </div>
        <table>
            <thead>
                <tr>
                    {"".join(f'<th>{h}</th>' for h in col_headers)}
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </body>
    </html>
    """
    return html


def send_email(df, excel_path):
    """发送筛选结果到邮箱"""
    if not QQ_AUTH_CODE:
        logger.warning("未配置QQ邮箱授权码(QQ_AUTH_CODE)，跳过邮件发送")
        logger.warning("获取授权码方法：QQ邮箱 → 设置 → 账户 → POP3/SMTP服务 → 开启 → 获取授权码")
        logger.warning("可通过环境变量设置: export QQ_AUTH_CODE='你的授权码'")
        return False

    logger.info(f"准备发送邮件到 {RECEIVER_EMAIL} ...")

    try:
        date_str = datetime.now().strftime('%Y年%m月%d日')

        msg = MIMEMultipart()
        msg['Subject'] = f'A股筛选报告：净利润高增长+近期涨停 ({date_str}) - {len(df)}只'
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL

        # HTML正文
        html_content = generate_email_html(df)
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))

        # 附件：Excel文件
        if os.path.exists(excel_path):
            with open(excel_path, 'rb') as f:
                attachment = MIMEApplication(f.read())
                attachment.add_header(
                    'Content-Disposition',
                    'attachment',
                    filename=('utf-8', '', os.path.basename(excel_path))
                )
                msg.attach(attachment)

        # 发送邮件
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(SENDER_EMAIL, QQ_AUTH_CODE)
            server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())

        logger.info(f"邮件发送成功！")
        return True

    except Exception as e:
        logger.error(f"邮件发送失败: {e}")
        return False


def main():
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("A股净利润高增长 + 近期涨停 股票筛选 - 开始运行")
    logger.info(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    try:
        # ========== 第一步：净利润增长筛选 ==========
        annual_periods, quarterly_periods = get_report_periods()
        annual_df = filter_annual_growth(annual_periods)
        quarterly_df = filter_quarterly_growth(quarterly_periods)
        growth_df = merge_growth_results(annual_df, quarterly_df)

        if growth_df.empty:
            logger.info("净利润增长筛选结果为空")
        else:
            logger.info(f"净利润高增长股票数: {len(growth_df)}")

        # ========== 第二步：获取近一个月涨停记录 ==========
        zt_codes, zt_stats = fetch_zt_pool_month()

        # ========== 第三步：取交集（高增长+涨停） ==========
        result_df = apply_zt_filter(growth_df, zt_codes, zt_stats)

        if result_df.empty:
            logger.info("无同时满足净利润高增长和近期涨停的股票")
        else:
            logger.info(f"高增长+涨停筛选结果: {len(result_df)} 只股票")

        # ========== 第四步：筛选收盘价>=20日均价 ==========
        if not result_df.empty:
            candidate_codes = result_df['股票代码'].tolist()
            ma20_codes = get_ma20_and_close(candidate_codes)
            result_df = apply_ma20_filter(result_df, ma20_codes)

        # ========== 第五步：筛选市盈率0 < PE <= 500 ==========
        if not result_df.empty:
            candidate_codes = result_df['股票代码'].tolist()
            pe_codes = get_pe_filter(candidate_codes)
            result_df = apply_pe_filter(result_df, pe_codes)

        if result_df.empty:
            logger.info("最终无满足全部条件的股票")
        else:
            logger.info(f"最终筛选结果: {len(result_df)} 只股票")

        # ========== 第六步：保存结果 =========="
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
        csv_path, excel_path = save_results(result_df, output_dir)

        # ========== 第七步：打印摘要 =========="
        formatted = format_output(result_df)
        logger.info("\n" + "=" * 60)
        logger.info("筛选结果摘要:")
        logger.info("=" * 60)
        if not formatted.empty:
            print_cols = [c for c in ['股票代码', '股票简称', '净利润-同比增长', '涨停次数', '最近涨停日期', '所处行业', '筛选条件'] if c in formatted.columns]
            logger.info(f"\n{formatted[print_cols].to_string(index=False)}")
        else:
            logger.info("无满足条件的股票")

        # ========== 第八步：发送邮件 =========="
        send_email(result_df, excel_path)

        elapsed = time.time() - start_time
        logger.info(f"\n脚本运行耗时: {elapsed:.1f}秒")

        return result_df

    except Exception as e:
        logger.error(f"脚本运行出错: {e}", exc_info=True)
        return pd.DataFrame()


if __name__ == '__main__':
    main()
