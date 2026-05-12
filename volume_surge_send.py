#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股量能放大 + 基本面增强筛选 & 邮件发送（可移植版）

功能：
1. 使用 baostock 获取全A股数据
2. 多条件漏斗筛选（量能≥2倍 / 非ST / PE>0 / 连续两期利润增长>20%）
3. 生成 CSV 附件 + HTML 报告
4. 通过 QQ 邮箱 SMTP_SSL 发送邮件

使用方式：
  python3 volume_surge_send.py

依赖：
  pip install baostock pandas

配置项（在下方 CONFIG 区域修改）：
  - SMTP 服务器、端口、发件人、授权码、收件人
  - 筛选参数（量比倍数、增长百分比阈值等）
  - 输出目录
"""

import smtplib
import os
import sys
import time
import baostock as bs
import pandas as pd
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders


# ═══════════════════════════════════════════════════════════════
#  CONFIG — 修改此处配置
# ═══════════════════════════════════════════════════════════════

# --- SMTP / 邮件配置 ---
SMTP_SERVER   = "smtp.qq.com"
SMTP_PORT     = 465
SENDER_EMAIL  = "281003252@qq.com"
SENDER_AUTH   = os.environ.get("QQ_AUTH_CODE", "")       # QQ邮箱授权码
RECEIVER_EMAIL = "281003252@qq.com"        # 收件人（可多个，逗号分隔）
MAIL_SUBJECT_PREFIX = "A股量能放大+基本面筛选"

# --- 筛选参数 ---
VOLUME_RATIO  = 2.0      # 量比倍数阈值（近2日均量 / 前7日均量）
GROWTH_THRESHOLD = 0.20   # 利润增长率阈值（20%）
CONSECUTIVE_PERIODS = 2   # 需要连续几期满足增长

# --- 输出目录（确保有写权限） ---
OUTPUT_DIR = "./"


# ═══════════════════════════════════════════════════════════════
#  核心筛选逻辑
# ═══════════════════════════════════════════════════════════════

def get_all_a_stocks():
    """获取全量A股（在市、非退市）"""
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
    df = df[['code', 'code_name']].reset_index(drop=True)
    print(f"  A股数量: {len(df)}")
    return df


def fetch_volume_pe(symbol, start_date, end_date):
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
        pe_str = row[3]
        if vol_str and vol_str != '':
            try:
                volumes.append(float(vol_str))
                if pe_str and pe_str != '':
                    last_pe = float(pe_str)
            except ValueError:
                pass
    return volumes, last_pe


def is_st_stock(name):
    """判断是否为ST股票"""
    return 'ST' in name or '*ST' in name


def get_recent_profit_growth(code, periods=2):
    """
    获取最近指定期数的净利润同比增长率（YOYNI）
    返回: list of dict [{yoni, period}, ...] 或 None
    """
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
                        if len(results) >= periods:
                            return results
            except Exception:
                pass
    return results if results else None


def run_screening():
    """执行全量筛选，返回 (结果DataFrame, 统计dict)"""
    today = datetime.now()
    start_date = (today - timedelta(days=40)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")

    print("登录 baostock...")
    lg = bs.login()
    if lg.error_code != '0':
        print(f"登录失败: {lg.error_msg}")
        sys.exit(1)

    print("获取A股列表...")
    stocks_df = get_all_a_stocks()
    total = len(stocks_df)

    print(f"\n{'='*60}")
    print(f"筛选条件:")
    print(f"  1. 近2日均量 >= 前7日均量 x {VOLUME_RATIO}")
    print(f"  2. 剔除ST/*ST")
    print(f"  3. PE-TTM > 0")
    print(f"  4. 连续{CONSECUTIVE_PERIODS}期利润增长 > {GROWTH_THRESHOLD*100:.0f}%")
    print(f"{'='*60}")
    print(f"开始扫描 {total} 只股票...\n")

    results = []
    stats = {
        'total': total,
        'volume_pass': 0,
        'st_filtered': 0,
        'pe_filtered': 0,
        'no_growth_data': 0,
        'growth_filtered': 0,
        'final_pass': 0,
    }

    for i, row in stocks_df.iterrows():
        code = row['code']
        name = row['code_name']

        # 1) 量能筛选
        vols, pe_ttm = fetch_volume_pe(code, start_date, end_date)
        if len(vols) < 9:
            continue
        recent_2_mean = sum(vols[-2:]) / 2
        prev_7_mean = sum(vols[-9:-2]) / 7
        if prev_7_mean <= 0 or recent_2_mean < prev_7_mean * VOLUME_RATIO:
            continue
        stats['volume_pass'] += 1

        # 2) ST过滤
        if is_st_stock(name):
            stats['st_filtered'] += 1
            continue

        # 3) 负PE过滤
        if pe_ttm is None or pe_ttm <= 0:
            stats['pe_filtered'] += 1
            continue

        # 4) 连续增长筛选
        growth_data = get_recent_profit_growth(code, CONSECUTIVE_PERIODS)
        if growth_data is None or len(growth_data) < CONSECUTIVE_PERIODS:
            stats['no_growth_data'] += 1
            continue

        all_pass = all(g['yoni'] > GROWTH_THRESHOLD for g in growth_data)
        if not all_pass:
            stats['growth_filtered'] += 1
            continue

        # 全部通过
        ratio = recent_2_mean / prev_7_mean
        entry = {
            '代码': code,
            '名称': name,
            '近2日均量': int(recent_2_mean),
            '前7日均量': int(prev_7_mean),
            '量比倍数': round(ratio, 2),
            'PE_TTM': round(pe_ttm, 2),
        }
        # 动态添加增长列
        for idx, g in enumerate(growth_data):
            col = f'{"近" if idx == 0 else "前"}一期利润增长({g["period"]})'
            entry[col] = f"{g['yoni']*100:.1f}%"

        results.append(entry)
        stats['final_pass'] += 1
        growth_str = " / ".join(f"[{g['period']}]{g['yoni']*100:.1f}%" for g in growth_data)
        print(f"  [通过] {code} {name:<10} 量比={ratio:.2f}x  PE={pe_ttm:.1f}  增长={growth_str}")

        # 进度日志
        if (i + 1) % 500 == 0:
            pct = (i + 1) / total * 100
            ts = datetime.now().strftime('%H:%M:%S')
            print(f"  [{ts}] {i+1}/{total} ({pct:.1f}%) 通过={stats['final_pass']}")

    bs.logout()
    return pd.DataFrame(results), stats


# ═══════════════════════════════════════════════════════════════
#  HTML 报告生成
# ═══════════════════════════════════════════════════════════════

def gen_html(df, ts, stats):
    """生成 HTML 报告内容（用于邮件正文）"""
    if df.empty:
        return "<p>本次筛选未找到符合条件的股票。</p>"

    cols = list(df.columns)
    ths = "".join(f"<th>{c}</th>" for c in cols)

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
            elif isinstance(val, (int, float)):
                tds += f"<td>{val:,}</td>"
            else:
                tds += f"<td>{val}</td>"
        rows_html += f"<tr>{tds}</tr>\n"

    # 漏斗
    after_st = stats['volume_pass'] - stats['st_filtered']
    after_pe = after_st - stats['pe_filtered']
    funnel = f"""
    <div class="funnel">
      <div class="fn-item"><span class="fn-num">{stats['total']}</span><span class="fn-lbl">全市场扫描</span></div>
      <div class="fn-arrow">&rarr;</div>
      <div class="fn-item"><span class="fn-num">{stats['volume_pass']}</span><span class="fn-lbl">量能&ge;{VOLUME_RATIO}倍</span></div>
      <div class="fn-arrow">&rarr;</div>
      <div class="fn-item"><span class="fn-num">{after_st}</span><span class="fn-lbl">剔除ST</span></div>
      <div class="fn-arrow">&rarr;</div>
      <div class="fn-item"><span class="fn-num">{after_pe}</span><span class="fn-lbl">PE&gt;0</span></div>
      <div class="fn-arrow">&rarr;</div>
      <div class="fn-item fn-final"><span class="fn-num">{stats['final_pass']}</span><span class="fn-lbl">连续增长&gt;{GROWTH_THRESHOLD*100:.0f}%</span></div>
    </div>"""

    date_str = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>A股量能放大+基本面筛选</title>
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
<h1>A股量能放大 + 基本面增强筛选</h1>
<div class="sub">
  <b>筛选条件：</b><br>
  1. 近2个交易日均量 &ge; 两天前过去7个交易日均量 &times; {VOLUME_RATIO}<br>
  2. 剔除 ST/*ST 股票<br>
  3. PE-TTM &gt; 0（剔除负市盈率）<br>
  4. 连续{CONSECUTIVE_PERIODS}期（季报/年报）净利润同比增长率 &gt; {GROWTH_THRESHOLD*100:.0f}%<br>
  数据截止：{date_str} &nbsp;|&nbsp; 数据来源：Baostock
</div>
<div class="stats">
  <div class="card"><div class="num">{len(df)}</div><div class="lbl">最终通过</div></div>
  <div class="card"><div class="num">{df['量比倍数'].max():.1f}x</div><div class="lbl">最高量比</div></div>
  <div class="card"><div class="num">{df['量比倍数'].median():.1f}x</div><div class="lbl">中位量比</div></div>
  <div class="card"><div class="num">{df['PE_TTM'].median():.1f}</div><div class="lbl">中位PE</div></div>
</div>
{funnel}
<div class="tbl-wrap">
<table>
  <thead><tr>{ths}</tr></thead>
  <tbody>{rows_html}</tbody>
</table>
</div>
</body>
</html>"""
    return html


# ═══════════════════════════════════════════════════════════════
#  邮件发送
# ═══════════════════════════════════════════════════════════════

def send_email(subject, html_body, csv_path):
    """通过 SMTP_SSL 发送 HTML 邮件 + CSV 附件"""
    msg = MIMEMultipart('related')
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    # 支持多个收件人
    recipients = [addr.strip() for addr in RECEIVER_EMAIL.split(',')]
    msg['To'] = ', '.join(recipients)

    # HTML 正文
    msg_html = MIMEText(html_body, 'html', 'utf-8')
    msg.attach(msg_html)

    # CSV 附件
    if csv_path and os.path.exists(csv_path):
        with open(csv_path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            filename = os.path.basename(csv_path)
            part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            msg.attach(part)
        print(f"  已附加文件: {filename}")

    # 发送
    print(f"  连接 {SMTP_SERVER}:{SMTP_PORT} ...")
    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30)
        server.login(SENDER_EMAIL, SENDER_AUTH)
        server.sendmail(SENDER_EMAIL, recipients, msg.as_string())
        server.quit()
        print(f"  邮件发送成功 -> {msg['To']}")
        return True
    except Exception as e:
        print(f"  邮件发送失败: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════════

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 60)
    print("  A股量能放大 + 基本面增强筛选 & 邮件发送")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # --- 第一步：执行筛选 ---
    print("\n[1/3] 执行筛选...")
    result_df, stats = run_screening()

    # 统计汇总
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    print(f"\n{'='*60}")
    print("筛选统计:")
    print(f"  全市场扫描      : {stats['total']} 只")
    print(f"  量能放大>={VOLUME_RATIO}倍  : {stats['volume_pass']} 只")
    print(f"  剔除ST          : {stats['st_filtered']} 只")
    print(f"  剔除负PE        : {stats['pe_filtered']} 只")
    print(f"  无增长数据       : {stats['no_growth_data']} 只")
    print(f"  增长未达标       : {stats['growth_filtered']} 只")
    print(f"  最终通过        : {stats['final_pass']} 只")
    print(f"{'='*60}")

    if result_df.empty:
        print("\n未找到符合条件的股票，不发送邮件。")
        return

    result_df = result_df.sort_values('量比倍数', ascending=False).reset_index(drop=True)

    # --- 第二步：生成文件 ---
    print("\n[2/3] 生成报告...")
    csv_path = os.path.join(OUTPUT_DIR, f"volume_surge_enhanced_{ts}.csv")
    html_path = os.path.join(OUTPUT_DIR, f"volume_surge_enhanced_{ts}.html")

    result_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"  CSV  -> {csv_path}")

    html_content = gen_html(result_df, ts, stats)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"  HTML -> {html_path}")

    # --- 第三步：发送邮件 ---
    print("\n[3/3] 发送邮件...")
    subject = f"{MAIL_SUBJECT_PREFIX} {ts[:4]}-{ts[4:6]}-{ts[6:8]} ({len(result_df)}只)"
    success = send_email(subject, html_content, csv_path)

    if success:
        print(f"\n全部完成！共筛选 {len(result_df)} 只股票，邮件已发送。")
    else:
        print(f"\n筛选完成（{len(result_df)}只），但邮件发送失败，请检查SMTP配置。")
        sys.exit(1)


if __name__ == "__main__":
    main()
