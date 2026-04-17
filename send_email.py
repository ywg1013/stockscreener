#!/usr/bin/env python3
"""
邮件发送脚本 - 将筛选结果发送到QQ邮箱
使用QQ邮箱SMTP（授权码方式）
"""

import os
import glob
import pandas as pd
import smtplib
import base64
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.utils import formataddr

# ============ 邮件配置 ============
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
SENDER_EMAIL = "281003252@qq.com"
RECEIVER_EMAIL = "281003252@qq.com"
SENDER_NAME = "A股筛选系统"
QQ_AUTH_CODE = os.environ.get("QQ_AUTH_CODE", "")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')


def find_latest_result():
    """查找最新的筛选结果文件"""
    pattern = os.path.join(OUTPUT_DIR, 'stock_growth_zt_*.xlsx')
    files = sorted(glob.glob(pattern))
    if not files:
        pattern = os.path.join(OUTPUT_DIR, 'stock_growth_zt_*.csv')
        files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def build_email_content(result_file):
    """构建邮件内容（纯文本+HTML+附件）"""
    if result_file.endswith('.xlsx'):
        df = pd.read_excel(result_file, engine='openpyxl')
    else:
        df = pd.read_csv(result_file)

    date_str = datetime.now().strftime('%Y年%m月%d日')

    # 格式化百分比列
    formatted = df.copy()
    if '净利润-同比增长' in formatted.columns:
        formatted['净利润-同比增长'] = pd.to_numeric(
            formatted['净利润-同比增长'].astype(str).str.replace('%', ''), errors='coerce'
        )
        formatted['净利润-同比增长'] = formatted['净利润-同比增长'].apply(
            lambda x: f"{x:.2f}%" if pd.notna(x) else ""
        )

    # 显示列
    display_cols = ['股票代码', '股票简称', '净利润-同比增长', '所处行业', '涨停次数', '最近涨停日期', '筛选条件']
    available_cols = [c for c in display_cols if c in formatted.columns]

    # 纯文本
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
        parts = [str(row[c]) if pd.notna(row[c]) else "" for c in available_cols]
        lines.append(" | ".join(parts))
    text_body = '\n'.join(lines)

    # HTML表格
    col_headers = {
        '股票代码': '股票代码', '股票简称': '股票简称', '净利润-同比增长': '净利润同比增长',
        '所处行业': '行业', '涨停次数': '月涨停次数', '最近涨停日期': '最近涨停', '筛选条件': '增长条件'
    }

    rows_html = ""
    for _, row in formatted.iterrows():
        row_cells = "".join(
            f"<td style='padding:6px 10px;border:1px solid #ddd;'>{str(row[c]) if pd.notna(row[c]) else ''}</td>"
            for c in available_cols
        )
        rows_html += f"<tr>{row_cells}</tr>"

    html_body = f"""<html><body style="font-family:Arial,sans-serif;padding:20px;">
<h2 style="color:#c0392b;">A股净利润高增长 + 近期涨停 筛选结果</h2>
<p>日期：{date_str}</p>
<div style="margin:15px 0;padding:12px;background:#fef9e7;border-left:4px solid #f39c12;">
<strong>筛选条件：</strong><br>
1. 非ST股票<br>
2. 最近2年年度净利润同比增长均 &amp;gt; 20% 或 连续2季度净利润同比增长均 &amp;gt; 20%<br>
3. 最近一个月有涨停记录<br>
<strong>符合条件的股票数：{len(df)}</strong>
</div>
<table style="border-collapse:collapse;width:100%;font-size:13px;">
<thead><tr>{"".join(f'<th style="background:#2c3e50;color:white;padding:8px 10px;">{col_headers.get(c, c)}</th>' for c in available_cols)}</tr></thead>
<tbody>{rows_html}</tbody>
</table>
</body></html>"""

    subject = f"A股筛选报告：净利润高增长+近期涨停 ({date_str}) - {len(df)}只"

    return text_body, html_body, subject, len(df), result_file


def send_email(text_body, html_body, subject, result_file):
    """通过QQ邮箱SMTP发送邮件"""
    print(f"发送方式: QQ邮箱SMTP")
    print(f"收件人: {RECEIVER_EMAIL}")

    msg = MIMEMultipart()
    msg['Subject'] = f'=?utf-8?B?{base64.b64encode(subject.encode()).decode()}?='
    msg['From'] = formataddr((SENDER_NAME, SENDER_EMAIL))
    msg['To'] = RECEIVER_EMAIL

    msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    # 添加Excel附件
    if result_file.endswith('.xlsx') and os.path.exists(result_file):
        with open(result_file, 'rb') as f:
            attachment = MIMEApplication(f.read())
            attachment.add_header(
                'Content-Disposition', 'attachment',
                filename=('utf-8', '', os.path.basename(result_file))
            )
            msg.attach(attachment)
            print(f"附件: {os.path.basename(result_file)}")

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.login(SENDER_EMAIL, QQ_AUTH_CODE)
            server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        print(f"✅ 邮件发送成功！")
        return True
    except Exception as e:
        print(f"❌ 发送失败: {e}")
        return False


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始发送邮件...")

    result_file = find_latest_result()
    if not result_file:
        print("未找到筛选结果文件")
        return False

    print(f"结果文件: {result_file}")

    text_body, html_body, subject, count, result_file = build_email_content(result_file)
    print(f"股票数量: {count}")

    success = send_email(text_body, html_body, subject, result_file)

    if success:
        print(f"\n请检查QQ邮箱（可能在垃圾邮件中）")
    return success


if __name__ == '__main__':
    main()
