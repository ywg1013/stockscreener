#!/usr/bin/env python3
"""
邮件发送脚本 - 将筛选结果发送到QQ邮箱
通过直接连接QQ的MX服务器投递邮件（无需SMTP授权码）
"""

import smtplib
import dns.resolver
import base64
import os
import glob
import pandas as pd
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.utils import formataddr

RECEIVER_EMAIL = "281003252@qq.com"
SENDER_NAME = "A股筛选系统"
SENDER_EMAIL = "stock-filter@stock-screener.com"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')


def find_latest_result():
    """查找最新的筛选结果文件"""
    pattern = os.path.join(OUTPUT_DIR, 'stock_growth_zt_*.xlsx')
    files = sorted(glob.glob(pattern))
    if not files:
        # 尝试CSV
        pattern = os.path.join(OUTPUT_DIR, 'stock_growth_zt_*.csv')
        files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def build_email(result_file):
    """构建邮件内容"""
    # 读取数据
    if result_file.endswith('.xlsx'):
        df = pd.read_excel(result_file, engine='openpyxl')
    else:
        df = pd.read_csv(result_file)

    date_str = datetime.now().strftime('%Y年%m月%d日')

    formatted = df.copy()
    if '净利润-同比增长' in formatted.columns:
        formatted['净利润-同比增长'] = formatted['净利润-同比增长'].apply(
            lambda x: f"{x:.2f}%" if pd.notna(x) else ""
        )

    # 纯文本内容
    lines = [
        f"A股净利润高增长+近期涨停 筛选结果",
        f"日期：{date_str}",
        f"符合条件的股票数：{len(df)}",
        "",
        "筛选条件：",
        "1. 非ST股票",
        "2. 最近2年年度净利润同比增长均>20% 或 连续2季度净利润同比增长均>20%",
        "3. 最近一个月有涨停记录",
        "",
        "结果列表：",
    ]
    for _, row in formatted.iterrows():
        code = row.get('股票代码', '')
        name = row.get('股票简称', '')
        growth = row.get('净利润-同比增长', '')
        industry = row.get('所处行业', '')
        zt_count = row.get('涨停次数', '')
        zt_date = row.get('最近涨停日期', '')
        condition = row.get('筛选条件', '')
        lines.append(
            f"{code} {name} | 增长:{growth} | 涨停:{zt_count}次 | {zt_date} | {industry} | {condition}"
        )
    text_body = '\n'.join(lines)

    # HTML内容
    display_cols = ['股票代码', '股票简称', '净利润-同比增长', '所处行业', '涨停次数', '最近涨停日期', '筛选条件']
    available_cols = [c for c in display_cols if c in formatted.columns]
    rows_html = ""
    for _, row in formatted.iterrows():
        row_cells = ""
        for col in available_cols:
            val = str(row[col]) if pd.notna(row[col]) else ""
            row_cells += f"<td style='padding:6px 10px;border:1px solid #ddd;'>{val}</td>"
        rows_html += f"<tr>{row_cells}</tr>"

    col_headers_map = {
        '股票代码': '股票代码', '股票简称': '股票简称', '净利润-同比增长': '净利润同比增长',
        '所处行业': '行业', '涨停次数': '月涨停次数', '最近涨停日期': '最近涨停', '筛选条件': '增长条件'
    }

    html_body = f"""<html><body style="font-family:Arial,sans-serif;padding:20px;">
<h2 style="color:#c0392b;">A股净利润高增长 + 近期涨停 筛选结果</h2>
<p>日期：{date_str}</p>
<div style="margin:15px 0;padding:12px;background:#fef9e7;border-left:4px solid #f39c12;">
<strong>筛选条件：</strong><br>
1. 非ST股票<br>
2. 最近2年年度净利润同比增长均 &gt; 20% 或 连续2季度净利润同比增长均 &gt; 20%<br>
3. 最近一个月有涨停记录<br>
<strong>符合条件的股票数：{len(df)}</strong>
</div>
<table style="border-collapse:collapse;width:100%;font-size:13px;">
<thead><tr>{"".join(f'<th style="background:#2c3e50;color:white;padding:8px 10px;">{col_headers_map.get(c, c)}</th>' for c in available_cols)}</tr></thead>
<tbody>{rows_html}</tbody>
</table>
</body></html>"""

    # 构建MIME邮件
    msg = MIMEMultipart()
    subject = f"A股筛选报告：净利润高增长+近期涨停 ({date_str}) - {len(df)}只"
    msg['Subject'] = f'=?utf-8?B?{base64.b64encode(subject.encode()).decode()}?='
    msg['From'] = formataddr((SENDER_NAME, SENDER_EMAIL))
    msg['To'] = RECEIVER_EMAIL

    msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    # Excel附件
    if result_file.endswith('.xlsx') and os.path.exists(result_file):
        with open(result_file, 'rb') as f:
            attachment = MIMEApplication(f.read())
            attachment.add_header(
                'Content-Disposition', 'attachment',
                filename=('utf-8', '', os.path.basename(result_file))
            )
            msg.attach(attachment)

    return msg


def send_via_qq_mx(msg):
    """直接通过QQ邮箱MX服务器发送邮件"""
    # 查询QQ的MX记录
    answers = dns.resolver.resolve('qq.com', 'MX')
    mx_list = [(rdata.preference, str(rdata.exchange).rstrip('.')) for rdata in answers]
    mx_list.sort()

    # 按优先级尝试每个MX服务器
    for priority, mx_server in mx_list:
        try:
            print(f"尝试连接 {mx_server} (priority: {priority})...")
            with smtplib.SMTP(mx_server, 25, timeout=30) as s:
                s.ehlo('stock-screener.com')
                code, msg_text = s.mail(SENDER_EMAIL)
                if code != 250:
                    print(f"  MAIL FROM 被拒绝: {code} {msg_text}")
                    continue

                code, msg_text = s.rcpt(RECEIVER_EMAIL)
                if code != 250:
                    print(f"  RCPT TO 被拒绝: {code} {msg_text}")
                    continue

                code, msg_text = s.data(msg.as_string())
                if code == 250:
                    print(f"  ✅ 邮件投递成功！(via {mx_server})")
                    return True
                else:
                    print(f"  DATA 被拒绝: {code} {msg_text}")
        except Exception as e:
            print(f"  连接 {mx_server} 失败: {e}")
            continue

    print("❌ 所有MX服务器均投递失败")
    return False


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始发送邮件...")

    # 查找最新结果文件
    result_file = find_latest_result()
    if not result_file:
        print("未找到筛选结果文件")
        return False

    print(f"结果文件: {result_file}")

    # 构建邮件
    msg = build_email(result_file)

    # 发送
    success = send_via_qq_mx(msg)

    if success:
        print("邮件发送完成！请检查QQ邮箱（可能在垃圾箱中）")
    return success


if __name__ == '__main__':
    main()
