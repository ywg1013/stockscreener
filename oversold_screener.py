#!/usr/bin/env python3
"""
A股超跌股自动筛选脚本 v2
两步筛选策略：
  Step1: 新浪API获取全量行情，按跌幅初筛（当日跌幅<-3% 或 年内跌幅>30%）
  Step2: 腾讯API获取候选股K线，计算13项超跌指标，筛选≥6项
"""

import os
import sys
import time
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime

# ============ 配置 ============
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
MIN_INDICATORS = 6
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# ============ 超跌指标阈值 ============
THRESHOLDS_ORI = {
    'bias_ma20': -10,
    'bias_ma60': -15,
    'below_ma_count': 3,
    'rsi14': 30,
    'kdj_j': 0,
    'ret_20d': -20,
    'ret_60d': -30,
    'band_drop': -40,
    'boll_pos': 0,
    'low_vol_days': 2,
    'max_consecutive_down': 5,
    'ret_5d': -15,
    'ret_10d': -20,
}

THRESHOLDS = {
    'bias_ma20': -20,
    'bias_ma60': -30,
    'below_ma_count': 3,
    'rsi14': 25,
    'kdj_j': 0,
    'ret_20d': -20,
    'ret_60d': -30,
    'band_drop': -50,
    'boll_pos': 15,
    'low_vol_days': 2,
    'max_consecutive_down': 5,
    'ret_5d': -15,
    'ret_10d': -20,
}

def get_all_stocks_sina():
    """新浪API获取全部A股列表+实时行情（含涨跌幅、年内涨跌等）"""
    print("  [Step1] 获取A股实时行情...")
    all_stocks = []
    page = 1
    while True:
        url = (f'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'
               f'Market_Center.getHQNodeData?page={page}&num=500&sort=changepercent&asc=1&node=hs_a&symbol=&_s_r_a=auto')
        try:
            r = requests.get(url, timeout=15, headers=HEADERS)
            data = json.loads(r.text)
            if not data:
                break
            all_stocks.extend(data)
            page += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"  新浪API第{page}页失败: {e}")
            break

    if not all_stocks:
        return pd.DataFrame()

    df = pd.DataFrame(all_stocks)
    # 过滤非ST沪深A股
    df = df[df['code'].str.match(r'^[036]')]
    df = df[~df['name'].str.contains('ST|退', na=False)]

    # 转数值
    for col in ['trade', 'changepercent', 'settlement', 'open', 'high', 'low',
                'volume', 'amount', 'turnoverratio', 'per', 'pb', 'mktcap']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    print(f"  共获取 {len(df)} 只非ST A股")
    return df


def prefilter_by_decline(df):
    """根据实时行情初筛：当日跌幅或区间跌幅较大的股票"""
    # 当日跌幅 < -3% 的候选（超跌倾向）
    mask_today = df['changepercent'] < -3

    # 另外获取一批涨跌幅靠后的股票（按涨幅升序排，新浪API已按asc=1排序）
    # 取涨幅后30%的股票
    n = len(df)
    mask_bottom = df.index < int(n * 0.30)

    # 合并
    mask = mask_today | mask_bottom
    filtered = df[mask].copy()

    print(f"  初筛候选: {len(filtered)} 只（当日跌>3%: {mask_today.sum()}, 涨幅后30%: {mask_bottom.sum()}）")
    return filtered


def get_kline_tencent(code, retry=2):
    """从腾讯API获取日K线（前复权）"""
    prefix = 'sh' if code.startswith('6') else 'sz'
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,300,qfq"

    for attempt in range(retry):
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            data = r.json()
            key = f'{prefix}{code}'
            if key in data.get('data', {}):
                rows = data['data'][key].get('qfqday', [])
                if not rows:
                    return None
                for i in range(len(rows)):
                    if len(rows[i]) == 6:
                        rows[i].append('0')
                col_names = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
                df = pd.DataFrame(rows, columns=col_names)
                for col in col_names[1:]:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
                if len(df) < 120:
                    return None
                return df
        except Exception:
            if attempt < retry - 1:
                time.sleep(1)
    return None


def calc_oversold_indicators(df):
    """计算13项超跌指标"""
    if df is None or len(df) < 120:
        return None

    latest = df.iloc[-1]
    close = latest['close']
    if close <= 0:
        return None

    indicators = {}

    # 1. 均线偏离
    for n in [20, 60, 120, 250]:
        df[f'ma{n}'] = df['close'].rolling(n).mean()

    ma20 = df['ma20'].iloc[-1]
    if pd.notna(ma20) and ma20 > 0:
        bias_ma20 = (close - ma20) / ma20 * 100
        indicators['bias_ma20'] = {'value': round(bias_ma20, 2), 'met': bias_ma20 < THRESHOLDS['bias_ma20']}
    else:
        indicators['bias_ma20'] = {'value': None, 'met': False}

    ma60 = df['ma60'].iloc[-1]
    if pd.notna(ma60) and ma60 > 0:
        bias_ma60 = (close - ma60) / ma60 * 100
        indicators['bias_ma60'] = {'value': round(bias_ma60, 2), 'met': bias_ma60 < THRESHOLDS['bias_ma60']}
    else:
        indicators['bias_ma60'] = {'value': None, 'met': False}

    below_count = 0
    for n in [20, 60, 120, 250]:
        ma_val = df[f'ma{n}'].iloc[-1]
        if pd.notna(ma_val) and close < ma_val:
            below_count += 1
    indicators['below_ma_count'] = {'value': below_count, 'met': below_count >= THRESHOLDS['below_ma_count']}

    # 2. 动量超卖
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    rsi14 = (100 - (100 / (1 + rs))).iloc[-1]
    if pd.notna(rsi14):
        indicators['rsi14'] = {'value': round(rsi14, 2), 'met': rsi14 < THRESHOLDS['rsi14']}
    else:
        indicators['rsi14'] = {'value': None, 'met': False}

    low_min = df['low'].rolling(9).min()
    high_max = df['high'].rolling(9).max()
    denom = high_max - low_min
    rsv = pd.Series(np.where(denom > 0, (df['close'] - low_min) / denom * 100, 50), index=df.index)
    k = rsv.ewm(com=2).mean().iloc[-1]
    d = rsv.ewm(com=2).mean().ewm(com=2).mean().iloc[-1]
    j = 3 * k - 2 * d
    if pd.notna(j):
        indicators['kdj_j'] = {'value': round(j, 2), 'met': j < THRESHOLDS['kdj_j']}
    else:
        indicators['kdj_j'] = {'value': None, 'met': False}

    # 区间跌幅
    for n, key in [(5, 'ret_5d'), (10, 'ret_10d'), (20, 'ret_20d'), (60, 'ret_60d')]:
        if len(df) > n:
            ret_n = (close / df['close'].iloc[-n-1] - 1) * 100
            indicators[key] = {'value': round(ret_n, 2), 'met': ret_n < THRESHOLDS[key]}
        else:
            indicators[key] = {'value': None, 'met': False}

    # 波段跌幅
    recent_120 = df.tail(120)
    high_120 = recent_120['high'].max()
    band_drop = (close / high_120 - 1) * 100
    indicators['band_drop'] = {'value': round(band_drop, 2), 'met': band_drop < THRESHOLDS['band_drop']}

    # 3. 布林带位置
    boll_mid = df['close'].rolling(20).mean().iloc[-1]
    std20 = df['close'].rolling(20).std().iloc[-1]
    if pd.notna(boll_mid) and pd.notna(std20) and std20 > 0:
        boll_upper = boll_mid + 2 * std20
        boll_lower = boll_mid - 2 * std20
        boll_pos = (close - boll_lower) / (boll_upper - boll_lower) * 100
        indicators['boll_pos'] = {'value': round(boll_pos, 2), 'met': boll_pos <= THRESHOLDS['boll_pos']}
    else:
        indicators['boll_pos'] = {'value': None, 'met': False}

    # 4. 量价特征
    vol_ma20 = df['volume'].rolling(20).mean()
    recent_20 = df.tail(20)
    low_vol_days = int((recent_20['volume'] < vol_ma20.tail(20) * 0.5).sum())
    indicators['low_vol_days'] = {'value': low_vol_days, 'met': low_vol_days >= THRESHOLDS['low_vol_days']}

    max_consec = 0
    cur_consec = 0
    for _, row in df.tail(30).iterrows():
        if row['close'] < row['open']:
            cur_consec += 1
            max_consec = max(max_consec, cur_consec)
        else:
            cur_consec = 0
    indicators['max_consecutive_down'] = {'value': max_consec, 'met': max_consec >= THRESHOLDS['max_consecutive_down']}

    met_count = sum(1 for v in indicators.values() if v['met'])

    return {
        'close': round(close, 2),
        'indicators': indicators,
        'met_count': met_count,
        'met_details': [k for k, v in indicators.items() if v['met']]
    }


def screen_stocks():
    """主筛选流程"""
    start_time = time.time()
    print("=" * 70)
    print(f"  A股超跌股筛选 v2 - 满足≥{MIN_INDICATORS}个超跌指标")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Step1: 获取全量行情并初筛
    df_all = get_all_stocks_sina()
    if df_all.empty:
        print("  未获取到股票列表，退出")
        return pd.DataFrame()

    candidates = prefilter_by_decline(df_all)
    total_candidates = len(candidates)
    print(f"\n  [Step2] 对 {total_candidates} 只候选股进行技术分析...")

    # 断点续跑
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    checkpoint_path = os.path.join(OUTPUT_DIR, 'oversold_checkpoint.json')
    done_codes = set()
    results = []

    if os.path.exists(checkpoint_path):
        try:
            with open(checkpoint_path, 'r') as f:
                ckpt = json.load(f)
            done_codes = set(ckpt.get('done_codes', []))
            results = ckpt.get('results', [])
            print(f"  从断点恢复: 已完成 {len(done_codes)} 只, 已筛选出 {len(results)} 只")
        except:
            pass

    errors = 0
    no_data = 0
    processed = len(done_codes)

    for _, row in candidates.iterrows():
        code = row['code']
        name = row['name']

        if code in done_codes:
            continue

        processed += 1
        if processed % 20 == 0 or processed == 1:
            elapsed = time.time() - start_time
            speed = processed / elapsed if elapsed > 0 else 0
            eta = (total_candidates - processed) / speed if speed > 0 else 0
            print(f"  进度: {processed}/{total_candidates} ({processed/total_candidates*100:.1f}%) | 超跌股: {len(results)} | 速度: {speed:.1f}只/秒 | 剩余: {eta/60:.1f}分钟")

        kline = get_kline_tencent(code)
        if kline is None:
            no_data += 1
            done_codes.add(code)
            continue

        try:
            result = calc_oversold_indicators(kline)
            if result and result['met_count'] >= MIN_INDICATORS:
                result['code'] = code
                result['name'] = name
                results.append(result)
        except Exception as e:
            errors += 1

        done_codes.add(code)

        # 每100只保存断点
        if processed % 100 == 0:
            try:
                with open(checkpoint_path, 'w') as f:
                    json.dump({'done_codes': list(done_codes), 'results': results}, f, ensure_ascii=False)
            except:
                pass

        time.sleep(0.25)

    # 排序
    results.sort(key=lambda x: x['met_count'], reverse=True)

    # 清除断点
    if os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)

    # 输出
    elapsed = time.time() - start_time
    print(f"\n{'='*70}")
    print(f"  筛选完成! 耗时: {elapsed/60:.1f}分钟")
    print(f"  候选: {total_candidates} 只 | 无数据: {no_data} | 错误: {errors}")
    print(f"  满足≥{MIN_INDICATORS}个指标: {len(results)} 只")
    print(f"{'='*70}")

    if not results:
        print("  未找到满足条件的超跌股")
        return pd.DataFrame()

    # 构建结果DataFrame
    rows_out = []
    for r in results:
        row_data = {
            '股票代码': r['code'],
            '股票简称': r['name'],
            '最新价': r['close'],
            '满足指标数': r['met_count'],
            '满足的指标': '、'.join(r['met_details']),
        }
        ind = r['indicators']
        row_data['RSI(14)'] = ind['rsi14']['value']
        row_data['KDJ-J'] = ind['kdj_j']['value']
        row_data['MA20偏离%'] = ind['bias_ma20']['value']
        row_data['MA60偏离%'] = ind['bias_ma60']['value']
        row_data['跌破均线数'] = ind['below_ma_count']['value']
        row_data['5日跌幅%'] = ind['ret_5d']['value']
        row_data['10日跌幅%'] = ind['ret_10d']['value']
        row_data['20日跌幅%'] = ind['ret_20d']['value']
        row_data['60日跌幅%'] = ind['ret_60d']['value']
        row_data['波段跌幅%'] = ind['band_drop']['value']
        row_data['布林位置%'] = ind['boll_pos']['value']
        row_data['地量天数'] = ind['low_vol_days']['value']
        row_data['连续阴线'] = ind['max_consecutive_down']['value']
        rows_out.append(row_data)

    result_df = pd.DataFrame(rows_out)

    # 保存
    date_str = datetime.now().strftime('%Y%m%d')
    csv_path = os.path.join(OUTPUT_DIR, f'oversold_stocks_{date_str}.csv')
    result_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"\n  CSV已保存: {csv_path}")

    excel_path = os.path.join(OUTPUT_DIR, f'oversold_stocks_{date_str}.xlsx')
    result_df.to_excel(excel_path, index=False, engine='openpyxl')
    print(f"  Excel已保存: {excel_path}")

    # 打印摘要
    print(f"\n{'='*70}")
    print(f"  超跌股筛选结果（满足≥{MIN_INDICATORS}个指标）")
    print(f"{'='*70}")
    show_cols = ['股票代码', '股票简称', '满足指标数', 'RSI(14)', 'MA20偏离%', '20日跌幅%', '60日跌幅%', '波段跌幅%', '满足的指标']
    available = [c for c in show_cols if c in result_df.columns]
    pd.set_option('display.max_colwidth', 60)
    pd.set_option('display.width', 200)
    print(result_df[available].to_string(index=False))

    print(f"\n{'='*70}")
    print(f"  指标满足数分布:")
    print(f"{'='*70}")
    for n in sorted(result_df['满足指标数'].unique(), reverse=True):
        count = len(result_df[result_df['满足指标数'] == n])
        print(f"    {n}个指标: {count} 只")

    return result_df


if __name__ == '__main__':
    screen_stocks()
