
"""
A股量能放大 + 基本面增强筛选（AsyncIO 高性能版）

特性：
1. asyncio + semaphore 控制并发
2. asyncio.to_thread 包装 baostock 阻塞IO
3. ST 提前过滤
4. 本地财务缓存
5. 智能季度推断
6. 高频量能筛选
7. 实时进度显示

依赖：
pip install baostock pandas
"""

import asyncio
import baostock as bs
import pandas as pd
from datetime import datetime, timedelta
import json
import os
import sys
from pathlib import Path

CACHE_FILE = "growth_cache_async.json"

MAX_CONCURRENT = 32

cache_lock = asyncio.Lock()


def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}


growth_cache = load_cache()


async def save_cache():
    async with cache_lock:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(growth_cache, f, ensure_ascii=False, indent=2)


def get_recent_available_periods():

    now = datetime.now()

    y = now.year
    m = now.month

    if m <= 4:
        return [
            (y - 1, 3),
            (y - 1, 2),
            (y - 1, 1),
            (y - 2, 4),
        ]

    elif m <= 8:
        return [
            (y - 1, 4),
            (y - 1, 3),
            (y - 1, 2),
            (y - 1, 1),
        ]

    elif m <= 10:
        return [
            (y, 2),
            (y - 1, 4),
            (y - 1, 3),
            (y - 1, 2),
        ]

    else:
        return [
            (y, 3),
            (y, 2),
            (y - 1, 4),
            (y - 1, 3),
        ]


AVAILABLE_PERIODS = get_recent_available_periods()


def query_stock_basic_sync():

    rs = bs.query_stock_basic()

    rows = []

    while rs.next():
        rows.append(rs.get_row_data())

    df = pd.DataFrame(rows, columns=rs.fields)

    df = df[
        (df['type'] == '1') &
        (df['status'] == '1') &
        (df['outDate'] == '')
    ][['code', 'code_name']]

    # 提前过滤 ST
    df = df[~df['code_name'].str.contains('ST', na=False)]

    return df.reset_index(drop=True)


async def get_all_stocks():
    return await asyncio.to_thread(query_stock_basic_sync)


def fetch_volume_pe_sync(code, start_date, end_date):

    rs = bs.query_history_k_data_plus(
        code,
        "date,volume,peTTM",
        start_date=start_date,
        end_date=end_date,
        frequency="d",
        adjustflag="3"
    )

    volumes = []
    last_pe = None

    while rs.next():

        row = rs.get_row_data()

        try:
            vol = float(row[1])
            volumes.append(vol)

            pe = row[2]

            if pe and pe != '':
                last_pe = float(pe)

        except:
            pass

    return volumes, last_pe


async def fetch_volume_pe(code, start_date, end_date):

    return await asyncio.to_thread(
        fetch_volume_pe_sync,
        code,
        start_date,
        end_date
    )


def query_growth_sync(code):

    if code in growth_cache:
        return growth_cache[code]

    results = []

    for year, quarter in AVAILABLE_PERIODS:

        try:

            rs = bs.query_growth_data(
                code=code,
                year=year,
                quarter=quarter
            )

            rows = []

            while rs.next():
                rows.append(rs.get_row_data())

            if rows:

                yoni = rows[0][5]

                if yoni and yoni not in ['', '-']:

                    results.append({
                        'yoni': float(yoni),
                        'period': f"{year}Q{quarter}"
                    })

                    if len(results) >= 2:
                        growth_cache[code] = (
                            results[0],
                            results[1]
                        )
                        return growth_cache[code]

        except:
            pass

    growth_cache[code] = None
    return None


async def get_recent_profit_growth(code):

    return await asyncio.to_thread(
        query_growth_sync,
        code
    )


async def process_stock(
    semaphore,
    row,
    start_date,
    end_date,
    counter,
    total
):

    async with semaphore:

        code = row.code
        name = row.code_name

        try:

            vols, pe_ttm = await fetch_volume_pe(
                code,
                start_date,
                end_date
            )

            if len(vols) < 9:
                return None

            recent_2 = sum(vols[-2:]) / 2
            prev_7 = sum(vols[-9:-2]) / 7

            if prev_7 <= 0:
                return None

            ratio = recent_2 / prev_7

            # 核心放量条件
            if ratio < 2:
                return None

            # PE过滤
            if pe_ttm is None or pe_ttm <= 0:
                return None

            growth = await get_recent_profit_growth(code)

            if growth is None:
                return None

            latest, prev = growth

            if latest['yoni'] <= 0.20:
                return None

            if prev['yoni'] <= 0.20:
                return None

            counter['done'] += 1

            if counter['done'] % 200 == 0:

                pct = counter['done'] / total * 100

                print(
                    f"进度: {counter['done']}/{total} "
                    f"({pct:.1f}%)"
                )

            print(
                f"✅ {code} {name} "
                f"量比={ratio:.2f}x"
            )

            return {
                '代码': code,
                '名称': name,
                '近2日均量': int(recent_2),
                '前7日均量': int(prev_7),
                '量比倍数': round(ratio, 2),
                'PE_TTM': round(pe_ttm, 2),
                f'近一期利润增长({latest["period"]})':
                    f"{latest['yoni'] * 100:.1f}%",
                f'前一期利润增长({prev["period"]})':
                    f"{prev['yoni'] * 100:.1f}%",
            }

        except Exception as e:

            print(f"ERROR {code}: {e}")
            return None


async def main():

    print("=" * 60)
    print("AsyncIO 高性能扫描启动")
    print("=" * 60)

    lg = bs.login()

    if lg.error_code != '0':
        print("baostock 登录失败")
        sys.exit(1)

    today = datetime.now()

    start_date = (
        today - timedelta(days=20)
    ).strftime("%Y-%m-%d")

    end_date = today.strftime("%Y-%m-%d")

    print("获取股票列表...")

    stocks_df = await get_all_stocks()

    total = len(stocks_df)

    print(f"股票数量: {total}")
    print(f"最大并发: {MAX_CONCURRENT}")
    print("=" * 60)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    counter = {'done': 0}

    tasks = [
        process_stock(
            semaphore,
            row,
            start_date,
            end_date,
            counter,
            total
        )
        for row in stocks_df.itertuples(index=False)
    ]

    results = await asyncio.gather(*tasks)

    bs.logout()

    await save_cache()

    results = [
        r for r in results
        if r is not None
    ]

    if not results:
        print("没有找到符合条件股票")
        return

    df = pd.DataFrame(results)

    df = df.sort_values(
        '量比倍数',
        ascending=False
    ).reset_index(drop=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M")

    output = Path(
        f"volume_surge_async_{ts}.csv"
    )

    df.to_csv(
        output,
        index=False,
        encoding='utf-8-sig'
    )

    print("=" * 60)
    print(df.to_string(index=False))
    print("=" * 60)
    print(f"结果保存: {output}")
    print(f"缓存保存: {CACHE_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
