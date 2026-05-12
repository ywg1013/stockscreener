"""
A股量能放大 + 基本面增强筛选脚本（baostock版）

筛选条件（必须全部满足）：
1. 量能放大：近2个交易日均量 ≥ 两天前过去7个交易日均量 × 2
2. 剔除ST/*ST股票
3. PE-TTM > 0（剔除负市盈率）
4. 连续两期（季报或年报）净利润同比增长率 > 20%

数据来源：baostock
"""

import baostock as bs
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import sys
import json

OUTPUT_DIR = "/tmp/volume_surge"

# ─── 全局变量：缓存股票列表 ───
STOCK_LIST = []

def get_all_a_stocks(lg) -> pd.DataFrame:
    """获取全量A股（type=1, status=1, 未退市）"""
    global STOCK_LIST
    rs = bs.query_stock_basic()
    data = []
    while rs.next():
        data.append(rs.get_row_data())
    df = pd.DataFrame(data, columns=rs.fields)
    df = df[
        (df['type'] == '1') &
        (df['status'] == '1') &
        (df['outDate'] == '')
    ].copy()
    STOCK_LIST = data  # 缓存原始列表用于ST判断
    df = df[['code', 'code_name']].reset_index(drop=True)
    print(f"  筛选后 A 股数量：{len(df)}")
    return df


def is_st_stock(code: str, name: str) -> bool:
    """判断是否为ST股票"""
    if 'ST' in name or '*ST' in name:
        return True
    return False


def fetch_volume_pe(symbol: str, start_date: str, end_date: str):
    """获取成交量序列 + 最新PE-TTM"""
    rs = bs.query_history_k_data_plus(
        symbol,
        'date,close,volume,peTTM',
        start_date=start_date,
        end_date=end_date,
        frequency='d',
        adjustflag='3'
    )
    volumes = []
    last_pe = None
    while rs.next():
        row = rs.get_row_data()
        vol_str = row[2]
        pe_str  = row[3]
        if vol_str and vol_str != '':
            try:
                volumes.append(float(vol_str))
                if pe_str and pe_str != '':
                    last_pe = float(pe_str)
            except ValueError:
                pass
    return volumes, last_pe


def get_recent_profit_growth(code: str):
    """
    获取最近两期的净利润同比增长率（YOYNI）
    优先用最近两个已公布的季报/年报
    返回：(latest_yoni, prev_yoni, latest_name, prev_name) 或 None
    """
    # 从最近的季度开始逐个查，找到2期有效增长数据即返回
    results = []
    for year in [2026, 2025, 2024, 2023]:
        for quarter in [4, 3, 2, 1]:
            try:
                rs = bs.query_growth_data(code=code, year=year, quarter=quarter)
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if rows:
                    yoni = rows[0][5]  # YOYNI 字段
                    if yoni and yoni != '' and yoni != '-':
                        results.append({
                            'yoni': float(yoni),
                            'period': f"{year}Q{quarter}"
                        })
                        if len(results) >= 2:
                            return results[0], results[1]
            except:
                pass

    return None


def get_latest_np_margin(code: str):
    """获取最近一期的净利润率(npMargin)"""
    for year in [2026, 2025, 2024, 2023]:
        for quarter in [4, 3, 2, 1]:
            try:
                rs = bs.query_profit_data(code=code, year=year, quarter=quarter)
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if rows:
                    npm = rows[0][4]  # npMargin
                    net_profit = rows[0][7]  # netProfit
                    if npm and npm != '' and npm != '-':
                        return float(npm)
            except:
                pass
    return None


def main():
    today      = datetime.now()
    start_date = (today - timedelta(days=40)).strftime("%Y-%m-%d")
    end_date   = today.strftime("%Y-%m-%d")

    print("登录 baostock...")
    lg = bs.login()
    if lg.error_code != '0':
        print(f"登录失败: {lg.error_msg}")
        sys.exit(1)

    print("获取 A 股列表...")
    stocks_df = get_all_a_stocks(lg)
    total     = len(stocks_df)

    print(f"\n{'='*70}")
    print("筛选条件：")
    print("  ① 近2日均量 ≥ 前7日均量 × 2")
    print("  ② 剔除 ST/*ST 股票")
    print("  ③ PE-TTM > 0（剔除负市盈率）")
    print("  ④ 连续两期净利润同比增长率 > 20%")
    print(f"{'='*70}")
    print(f"开始扫描 {total} 只股票...\n")

    results = []
    stats = {
        'total': total,
        'volume_pass': 0,      # 通过量能筛选
        'st_filtered': 0,       # 被ST过滤
        'pe_filtered': 0,       # 被负PE过滤
        'no_growth_data': 0,    # 无增长数据
        'growth_filtered': 0,   # 增长不达标
        'final_pass': 0,
    }

    for i, row in stocks_df.iterrows():
        code  = row['code']
        name  = row['code_name']

        # ① 量能筛选
        vols, pe_ttm = fetch_volume_pe(code, start_date, end_date)
        if len(vols) < 9:
            continue
        recent_2_mean = sum(vols[-2:]) / 2
        prev_7_mean   = sum(vols[-9:-2]) / 7
        if prev_7_mean <= 0 or recent_2_mean < prev_7_mean * 2:
            continue
        stats['volume_pass'] += 1

        # ② ST过滤
        if is_st_stock(code, name):
            stats['st_filtered'] += 1
            continue

        # ③ 负PE过滤
        if pe_ttm is None or pe_ttm <= 0:
            stats['pe_filtered'] += 1
            continue

        # ④ 连续两期利润增长>20%
        growth_result = get_recent_profit_growth(code)
        if growth_result is None:
            stats['no_growth_data'] += 1
            continue
        latest, prev = growth_result
        if latest['yoni'] <= 0.20 or prev['yoni'] <= 0.20:
            stats['growth_filtered'] += 1
            continue

        # 全部通过
        ratio = recent_2_mean / prev_7_mean
        results.append({
            '代码'    : code,
            '名称'    : name,
            '近2日均量': int(recent_2_mean),
            '前7日均量': int(prev_7_mean),
            '量比倍数' : round(ratio, 2),
            'PE_TTM'  : round(pe_ttm, 2),
            f'近一期利润增长({latest["period"]})': f"{latest['yoni']*100:.1f}%",
            f'前一期利润增长({prev["period"]})': f"{prev['yoni']*100:.1f}%",
        })
        stats['final_pass'] += 1
        print(f"  ✅ {code} {name:<10} 量比={ratio:.2f}x  PE={pe_ttm:.1f}  "
              f"增长=[{latest['period']}] {latest['yoni']*100:.1f}% / [{prev['period']}] {prev['yoni']*100:.1f}%")

        if (i + 1) % 500 == 0:
            pct = (i + 1) / total * 100
            ts  = datetime.now().strftime('%H:%M:%S')
            print(f"  [{ts}] {i+1}/{total} ({pct:.1f}%) "
                  f"量能通过={stats['volume_pass']} ST过滤={stats['st_filtered']} "
                  f"PE过滤={stats['pe_filtered']} 增长通过={stats['final_pass']}")

    bs.logout()

    # ── 统计汇总 ──────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    result_df = pd.DataFrame(results)

    print(f"\n{'='*70}")
    print(f"📊 筛选统计")
    print(f"{'─'*70}")
    print(f"  全市场扫描        : {stats['total']} 只")
    print(f"  ① 量能放大≥2倍   : {stats['volume_pass']} 只")
    print(f"  ② 剔除ST         : {stats['st_filtered']} 只")
    print(f"  ③ 剔除负PE       : {stats['pe_filtered']} 只")
    print(f"  ④ 无增长数据      : {stats['no_growth_data']} 只")
    print(f"  ⑤ 增长未达20%     : {stats['growth_filtered']} 只")
    print(f"  ✅ 最终通过        : {stats['final_pass']} 只")
    print(f"{'='*70}")

    if not result_df.empty:
        result_df = result_df.sort_values('量比倍数', ascending=False).reset_index(drop=True)
        csv_path  = os.path.join(OUTPUT_DIR, f"volume_surge_enhanced_{ts}.csv")
        html_path = os.path.join(OUTPUT_DIR, f"volume_surge_enhanced_{ts}.html")
        result_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        gen_html(result_df, html_path, ts, stats)
        print(f"   CSV  → {csv_path}")
        print(f"   HTML → {html_path}")
        print(f"{'='*70}")
        print(result_df.to_string(index=False))
    else:
        print("  未找到同时满足所有条件的股票。")


def gen_html(df: pd.DataFrame, path: str, ts: str, stats: dict):
    cols = list(df.columns)
    # 构建表头
    ths = "".join(f"<th>{c}</th>" for c in cols)
    # 构建表行
    rows_html = ""
    for _, r in df.iterrows():
        ratio = r['量比倍数']
        color = "#c0392b" if ratio >= 5 else "#e67e22" if ratio >= 3 else "#f39c12"
        tds = ""
        for c in cols:
            val = r[c]
            if c == '量比倍数':
                tds += f"<td style='color:{color};font-weight:700;font-size:15px'>{val}x</td>"
            elif '增长' in c:
                tds += f"<td style='color:#27ae60;font-weight:600'>{val}</td>"
            elif c == 'PE_TTM':
                tds += f"<td>{val:.1f}</td>"
            else:
                tds += f"<td>{val:,}</td>" if isinstance(val, (int, float)) and c != 'PE_TTM' else f"<td>{val}</td>"
        rows_html += f"<tr>{tds}</tr>\n"

    # 漏斗统计
    funnel_html = f"""
    <div class="funnel">
      <div class="fn-item"><span class="fn-num">{stats['total']}</span><span class="fn-lbl">全市场扫描</span></div>
      <div class="fn-arrow">→</div>
      <div class="fn-item"><span class="fn-num">{stats['volume_pass']}</span><span class="fn-lbl">量能≥2倍</span></div>
      <div class="fn-arrow">→</div>
      <div class="fn-item"><span class="fn-num">{stats['volume_pass'] - stats['st_filtered']}</span><span class="fn-lbl">剔除ST</span></div>
      <div class="fn-arrow">→</div>
      <div class="fn-item"><span class="fn-num">{stats['volume_pass'] - stats['st_filtered'] - stats['pe_filtered']}</span><span class="fn-lbl">PE>0</span></div>
      <div class="fn-arrow">→</div>
      <div class="fn-item fn-final"><span class="fn-num">{stats['final_pass']}</span><span class="fn-lbl">连续两期增长>20%</span></div>
    </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>A股量能放大+基本面筛选 {ts}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:'Microsoft YaHei',Helvetica,sans-serif;background:#f0f2f5;padding:24px;}}
h1{{color:#1a1a2e;font-size:22px;margin-bottom:6px;}}
.sub{{color:#888;font-size:13px;margin-bottom:20px;line-height:1.8;}}
.stats{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:20px;}}
.card{{background:#fff;border-radius:10px;padding:14px 22px;box-shadow:0 2px 6px rgba(0,0,0,.07);min-width:110px;}}
.card .num{{font-size:28px;font-weight:700;color:#c0392b;}}
.card .lbl{{font-size:12px;color:#aaa;margin-top:3px;}}
.funnel{{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:24px;padding:16px;
          background:#fff;border-radius:10px;box-shadow:0 2px 6px rgba(0,0,0,.07);}}
.fn-item{{text-align:center;padding:8px 14px;background:#f8f9fa;border-radius:8px;}}
.fn-item.fn-final{{background:#c0392b;color:#fff;}}
.fn-item.fn-final .fn-num,.fn-item.fn-final .fn-lbl{{color:#fff;}}
.fn-num{{display:block;font-size:22px;font-weight:700;color:#1a1a2e;}}
.fn-lbl{{display:block;font-size:11px;color:#888;margin-top:2px;}}
.fn-arrow{{color:#ccc;font-size:18px;font-weight:700;}}
.tbl-wrap{{overflow-x:auto;}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;
       box-shadow:0 2px 6px rgba(0,0,0,.07);overflow:hidden;}}
thead tr{{background:#1a1a2e;color:#fff;}}
th,td{{padding:9px 12px;text-align:center;font-size:12px;border-bottom:1px solid #f2f2f2;white-space:nowrap;}}
tr:last-child td{{border-bottom:none;}}
tr:hover td{{background:#fffbf0;}}
</style>
</head>
<body>
<h1>📊 A股量能放大 + 基本面增强筛选</h1>
<div class="sub">
  <b>筛选条件：</b><br>
  ① 近2个交易日均量 ≥ 两天前过去7个交易日均量 × 2<br>
  ② 剔除 ST/*ST 股票<br>
  ③ PE-TTM > 0（剔除负市盈率）<br>
  ④ 连续两期（季报/年报）净利润同比增长率 > 20%<br>
  数据截止：{ts[:4]}-{ts[4:6]}-{ts[6:8]} &nbsp;|&nbsp; 数据来源：Baostock
</div>
<div class="stats">
  <div class="card"><div class="num">{len(df)}</div><div class="lbl">最终通过</div></div>
  <div class="card"><div class="num">{df['量比倍数'].max():.1f}x</div><div class="lbl">最高量比</div></div>
  <div class="card"><div class="num">{df['量比倍数'].median():.1f}x</div><div class="lbl">中位量比</div></div>
  <div class="card"><div class="num">{df['PE_TTM'].median():.1f}</div><div class="lbl">中位PE</div></div>
</div>
{funnel_html}
<div class="tbl-wrap">
<table>
  <thead><tr>{ths}</tr></thead>
  <tbody>{rows_html}</tbody>
</table>
</div>
</body>
</html>"""
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)


if __name__ == "__main__":
    main()
