#!/usr/bin/env python3
"""
超跌股筛选结果邮件发送脚本
将超跌股筛选结果发送到QQ邮箱
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
SENDER_NAME = "A股超跌筛选系统"
QQ_AUTH_CODE = os.environ.get("QQ_AUTH_CODE", "gyygwyzeivxtbhce")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')

# ============ 超跌指标说明 ============
INDICATOR_DESC = {
    'bias_ma20': 'MA20偏离<-10%',
    'bias_ma60': 'MA60偏离<-15%',
    'below_ma_count': '跌破≥3条均线',
    'rsi14': 'RSI(14)<30',
    'kdj_j': 'KDJ-J<0',
    'ret_5d': '5日跌幅>15%',
    'ret_10d': '10日跌幅>20%',
    'ret_20d': '20日跌幅>20%',
    'ret_60d': '60日跌幅>30%',
    'band_drop': '波段跌幅>40%',
    'boll_pos': '布林带底部',
    'low_vol_days': '近20日地量≥2天',
    'max_consecutive_down': '连续阴线≥5天',
}


def find_latest_oversold_result():
    """查找最新的超跌股筛选结果文件"""
    pattern = os.path.join(OUTPUT_DIR, 'oversold_stocks_*.xlsx')
    files = sorted(glob.glob(pattern))
    if not files:
        pattern = os.path.join(OUTPUT_DIR, 'oversold_stocks_*.csv')
        files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def format_pct(val):
    """格式化百分比数值"""
    if pd.isna(val) or val is None:
        return '-'
    try:
        v = float(val)
        if v == 0:
            return '0.00%'
        return f"{v:+.2f}%" if v < 0 else f"{v:.2f}%"
    except:
        return str(val)


def format_indicator_tags(met_str):
    """将满足的指标文本转为HTML标签"""
    if pd.isna(met_str) or not met_str:
        return ''
    tags = []
    for ind in met_str.split('、'):
        desc = INDICATOR_DESC.get(ind, ind)
        # 根据指标类型设置颜色
        if '跌幅' in desc or '偏离' in desc or '波段' in desc:
            color = '#e74c3c'  # 红色 - 跌幅类
        elif 'RSI' in desc or 'KDJ' in desc:
            color = '#8e44ad'  # 紫色 - 动量类
        elif '布林' in desc or '均线' in desc:
            color = '#2980b9'  # 蓝色 - 趋势类
        else:
            color = '#27ae60'  # 绿色 - 量价类
        tags.append(f'<span style="display:inline-block;margin:2px;padding:2px 6px;background:{color}15;color:{color};border:1px solid {color}30;border-radius:3px;font-size:11px;">{desc}</span>')
    return ' '.join(tags)


def met_count_color(count):
    """根据满足指标数返回颜色"""
    if count >= 10:
        return '#c0392b'   # 深红 - 极度超跌
    elif count >= 8:
        return '#e74c3c'   # 红色 - 严重超跌
    elif count >= 7:
        return '#e67e22'   # 橙色 - 明显超跌
    else:
        return '#f39c12'   # 黄色 - 偏超跌


def build_email_content(result_file):
    """构建邮件内容（纯文本+HTML+附件）"""
    if result_file.endswith('.xlsx'):
        df = pd.read_excel(result_file, engine='openpyxl')
    else:
        df = pd.read_csv(result_file)

    date_str = datetime.now().strftime('%Y年%m月%d日')

    # ===== 纯文本 =====
    lines = [
        f"A股超跌股筛选结果",
        f"日期：{date_str}",
        f"满足≥6个超跌指标的股票数：{len(df)}",
        "",
        "超跌指标体系（13项，满足≥6项即入选）：",
        "  均线偏离：MA20偏离<-10%、MA60偏离<-15%、跌破≥3条均线",
        "  动量超卖：RSI(14)<30、KDJ-J<0",
        "  区间跌幅：5日>15%、10日>20%、20日>20%、60日>30%",
        "  波段跌幅：近120日高点回落>40%",
        "  布林位置：处于布林带底部及以下",
        "  量价特征：近20日地量≥2天、连续阴线≥5天",
        "",
        "─" * 60,
    ]

    for i, row in df.iterrows():
        name = row.get('股票简称', '')
        code = str(row.get('股票代码', '')).zfill(6)
        met = row.get('满足指标数', 0)
        rsi = row.get('RSI(14)', '-')
        bias20 = row.get('MA20偏离%', '-')
        ret20 = row.get('20日跌幅%', '-')
        ret60 = row.get('60日跌幅%', '-')
        band = row.get('波段跌幅%', '-')
        lines.append(f"  {i+1}. {code} {name} | 满足{met}项 | RSI:{rsi} | MA20偏离:{bias20}% | 20日跌:{ret20}% | 60日跌:{ret60}% | 波段跌:{band}%")

    text_body = '\n'.join(lines)

    # ===== HTML =====
    # 顶部摘要
    summary_html = f"""
    <div style="background:linear-gradient(135deg,#1a1a2e,#16213e);color:white;padding:24px;border-radius:8px;margin-bottom:20px;">
        <h2 style="margin:0 0 10px 0;">📉 A股超跌股筛选报告</h2>
        <p style="margin:5px 0;font-size:15px;">📅 {date_str} | 🔍 扫描全市场非ST A股 | 📊 13项超跌指标体系</p>
        <div style="font-size:28px;font-weight:bold;margin:12px 0;">满足≥6项指标：<span style="color:#e74c3c;">{len(df)}</span> 只</div>
    </div>
    """

    # 指标说明卡片
    indicator_cards = """
    <div style="margin-bottom:20px;padding:16px;background:#f8f9fa;border-radius:6px;border-left:4px solid #3498db;">
        <strong>超跌指标体系（满足≥6项即入选）：</strong><br>
        <span style="color:#e74c3c;">● 跌幅类</span> MA20偏离<-10% | MA60偏离<-15% | 5日跌>15% | 10日跌>20% | 20日跌>20% | 60日跌>30% | 波段跌>40%<br>
        <span style="color:#8e44ad;">● 动量类</span> RSI(14)<30 | KDJ-J<0<br>
        <span style="color:#2980b9;">● 趋势类</span> 跌破≥3条均线 | 布林带底部<br>
        <span style="color:#27ae60;">● 量价类</span> 近20日地量≥2天 | 连续阴线≥5天
    </div>
    """

    # 表格行
    rows_html = ""
    for i, row in df.iterrows():
        met = int(row.get('满足指标数', 0))
        color = met_count_color(met)

        # 各列格式化
        code_val = str(row.get('股票代码', '')).zfill(6)
        name_val = row.get('股票简称', '')
        price_val = f"{row.get('最新价', 0):.2f}" if pd.notna(row.get('最新价')) else '-'
        met_val = f'<span style="font-weight:bold;color:{color};font-size:15px;">{met}</span>'

        rsi_val = format_pct(row.get('RSI(14)'))
        kdj_val = format_pct(row.get('KDJ-J'))
        bias20_val = format_pct(row.get('MA20偏离%'))
        bias60_val = format_pct(row.get('MA60偏离%'))
        below_val = str(int(row.get('跌破均线数', 0))) if pd.notna(row.get('跌破均线数')) else '-'
        ret5_val = format_pct(row.get('5日跌幅%'))
        ret10_val = format_pct(row.get('10日跌幅%'))
        ret20_val = format_pct(row.get('20日跌幅%'))
        ret60_val = format_pct(row.get('60日跌幅%'))
        band_val = format_pct(row.get('波段跌幅%'))
        boll_val = format_pct(row.get('布林位置%'))
        low_vol_val = str(int(row.get('地量天数', 0))) if pd.notna(row.get('地量天数')) else '-'
        consec_val = str(int(row.get('连续阴线', 0))) if pd.notna(row.get('连续阴线')) else '-'
        tags_val = format_indicator_tags(row.get('满足的指标', ''))

        bg = '#fff5f5' if met >= 10 else ('#fff8f0' if met >= 8 else 'white')
        rows_html += f"""
        <tr style="background:{bg};">
            <td style="padding:8px;text-align:center;font-weight:bold;">{i+1}</td>
            <td style="padding:8px;font-family:monospace;font-weight:bold;">{code_val}</td>
            <td style="padding:8px;font-weight:bold;">{name_val}</td>
            <td style="padding:8px;text-align:center;">{price_val}</td>
            <td style="padding:8px;text-align:center;">{met_val}</td>
            <td style="padding:8px;text-align:center;color:#8e44ad;">{rsi_val}</td>
            <td style="padding:8px;text-align:center;color:#8e44ad;">{kdj_val}</td>
            <td style="padding:8px;text-align:center;color:#e74c3c;">{bias20_val}</td>
            <td style="padding:8px;text-align:center;color:#e74c3c;">{bias60_val}</td>
            <td style="padding:8px;text-align:center;">{below_val}</td>
            <td style="padding:8px;text-align:center;color:#e74c3c;">{ret5_val}</td>
            <td style="padding:8px;text-align:center;color:#e74c3c;">{ret10_val}</td>
            <td style="padding:8px;text-align:center;color:#e74c3c;font-weight:bold;">{ret20_val}</td>
            <td style="padding:8px;text-align:center;color:#e74c3c;font-weight:bold;">{ret60_val}</td>
            <td style="padding:8px;text-align:center;color:#c0392b;font-weight:bold;">{band_val}</td>
            <td style="padding:8px;text-align:center;color:#2980b9;">{boll_val}</td>
            <td style="padding:8px;text-align:center;">{low_vol_val}</td>
            <td style="padding:8px;text-align:center;">{consec_val}</td>
        </tr>
        <tr><td colspan="18" style="padding:4px 8px 10px 8px;background:#fafafa;border-bottom:2px solid #eee;">{tags_val}</td></tr>
        """

    # 分布统计
    dist_html = ""
    for n in sorted(df['满足指标数'].unique(), reverse=True):
        cnt = len(df[df['满足指标数'] == n])
        pct = cnt / len(df) * 100
        color = met_count_color(n)
        dist_html += f"""
        <div style="display:flex;align-items:center;margin:4px 0;">
            <span style="width:80px;text-align:right;margin-right:10px;font-weight:bold;color:{color};">{n}项指标</span>
            <div style="flex:1;background:#eee;border-radius:3px;height:20px;">
                <div style="width:{pct}%;background:{color};border-radius:3px;height:20px;"></div>
            </div>
            <span style="margin-left:10px;">{cnt}只</span>
        </div>
        """

    html_body = f"""<html><body style="font-family:'Microsoft YaHei',Arial,sans-serif;padding:20px;max-width:1200px;margin:0 auto;">
    {summary_html}
    {indicator_cards}

    <h3 style="color:#2c3e50;">📊 超跌强度分布</h3>
    <div style="margin-bottom:20px;padding:12px;background:#fafafa;border-radius:6px;">
        {dist_html}
    </div>

    <h3 style="color:#2c3e50;">📋 详细筛选结果</h3>
    <div style="overflow-x:auto;">
    <table style="border-collapse:collapse;width:100%;font-size:12px;min-width:1100px;">
    <thead><tr style="background:#2c3e50;color:white;">
        <th style="padding:8px;width:30px;">#</th>
        <th style="padding:8px;">代码</th>
        <th style="padding:8px;">简称</th>
        <th style="padding:8px;">最新价</th>
        <th style="padding:8px;">满足数</th>
        <th style="padding:8px;">RSI(14)</th>
        <th style="padding:8px;">KDJ-J</th>
        <th style="padding:8px;">MA20偏离</th>
        <th style="padding:8px;">MA60偏离</th>
        <th style="padding:8px;">破均线</th>
        <th style="padding:8px;">5日跌幅</th>
        <th style="padding:8px;">10日跌幅</th>
        <th style="padding:8px;">20日跌幅</th>
        <th style="padding:8px;">60日跌幅</th>
        <th style="padding:8px;">波段跌幅</th>
        <th style="padding:8px;">布林位置</th>
        <th style="padding:8px;">地量天</th>
        <th style="padding:8px;">连阴线</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
    </table>
    </div>

    <div style="margin-top:20px;padding:12px;background:#eaf2f8;border-radius:6px;font-size:12px;color:#555;">
        <strong>⚠️ 免责声明：</strong>本筛选结果仅供参考，不构成投资建议。超跌不代表见底，需结合基本面、行业趋势综合判断。投资有风险，入市需谨慎。
    </div>
    </body></html>"""

    subject = f"A股超跌股筛选报告 ({date_str}) - {len(df)}只满足≥6项指标"

    return text_body, html_body, subject, len(df), result_file


def send_email(text_body, html_body, subject, result_file):
    """通过QQ邮箱SMTP发送邮件"""
    print(f"发送方式: QQ邮箱SMTP")
    print(f"发件人: {SENDER_EMAIL}")
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
    elif result_file.endswith('.csv') and os.path.exists(result_file):
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
        print("✅ 邮件发送成功！")
        return True
    except Exception as e:
        print(f"❌ 发送失败: {e}")
        return False


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始发送超跌股筛选邮件...")

    result_file = find_latest_oversold_result()
    if not result_file:
        print("未找到超跌股筛选结果文件")
        return False

    print(f"结果文件: {result_file}")

    text_body, html_body, subject, count, result_file = build_email_content(result_file)
    print(f"超跌股数量: {count}")

    success = send_email(text_body, html_body, subject, result_file)

    if success:
        print(f"\n请检查QQ邮箱（可能在垃圾邮件中）")
    return success


if __name__ == '__main__':
    main()
