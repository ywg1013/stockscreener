#!/usr/bin/env python3
"""
生成结果查看网页 - 将筛选结果生成为可交互的HTML页面
每天运行筛选后自动调用此脚本
"""

import os
import glob
import pandas as pd
import json
from datetime import datetime

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
HTML_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'result.html')


def find_latest_result():
    pattern = os.path.join(OUTPUT_DIR, 'stock_growth_zt_*.xlsx')
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def format_percent(val):
    try:
        f = float(str(val).replace('%', ''))
        return f"{f:.2f}%"
    except:
        return str(val) if val else "-"


def format_number(val):
    try:
        f = float(val)
        if abs(f) >= 1e8:
            return f"{f/1e8:.2f}亿"
        elif abs(f) >= 1e4:
            return f"{f/1e4:.2f}万"
        else:
            return f"{f:.2f}"
    except:
        return str(val) if val else "-"


def generate_html():
    result_file = find_latest_result()
    if not result_file:
        print("未找到筛选结果文件")
        return False

    df = pd.read_excel(result_file, engine='openpyxl')
    date_str = datetime.now().strftime('%Y年%m月%d日')

    # 格式化数据
    rows_data = []
    for _, row in df.iterrows():
        row_data = {
            'code': str(row.get('股票代码', '')),
            'name': str(row.get('股票简称', '')),
            'eps': format_number(row.get('每股收益', '')),
            'profit': format_number(row.get('净利润-净利润', '')),
            'profit_growth': format_percent(row.get('净利润-同比增长', '')),
            'revenue': format_number(row.get('营业总收入-营业总收入', '')),
            'revenue_growth': format_percent(row.get('营业总收入-同比增长', '')),
            'roe': format_percent(row.get('净资产收益率', '')),
            'gross_margin': format_percent(row.get('销售毛利率', '')),
            'industry': str(row.get('所处行业', '')),
            'condition': str(row.get('筛选条件', '')),
            'zt_count': str(row.get('涨停次数', '')),
            'zt_latest': str(row.get('最近涨停日期', '')),
            'zt_dates': str(row.get('涨停日期列表', '')),
        }
        rows_data.append(row_data)

    rows_json = json.dumps(rows_data, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股筛选结果 - 净利润高增长+近期涨停</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, 'Microsoft YaHei', sans-serif; background: #f0f2f5; color: #333; padding: 20px; }}
.header {{ background: linear-gradient(135deg, #c0392b, #e74c3c); color: white; padding: 30px; border-radius: 12px; margin-bottom: 20px; }}
.header h1 {{ font-size: 24px; margin-bottom: 8px; }}
.header .date {{ font-size: 14px; opacity: 0.9; }}
.summary {{ display: flex; gap: 15px; margin-bottom: 20px; flex-wrap: wrap; }}
.summary .card {{ background: white; padding: 20px; border-radius: 10px; flex: 1; min-width: 150px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
.summary .card .num {{ font-size: 28px; font-weight: bold; color: #c0392b; }}
.summary .card .label {{ font-size: 13px; color: #888; margin-top: 4px; }}
.filters {{ background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
.filters h3 {{ margin-bottom: 12px; font-size: 15px; color: #555; }}
.filter-row {{ display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }}
.filter-row input, .filter-row select {{ padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }}
.filter-row input {{ width: 200px; }}
.filter-row select {{ width: 160px; }}
.filter-row .count {{ font-size: 13px; color: #888; margin-left: auto; }}
.table-wrap {{ background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
thead {{ position: sticky; top: 0; z-index: 1; }}
th {{ background: #2c3e50; color: white; padding: 12px 10px; text-align: center; white-space: nowrap; cursor: pointer; user-select: none; }}
th:hover {{ background: #34495e; }}
th .sort {{ font-size: 10px; margin-left: 2px; opacity: 0.6; }}
td {{ padding: 10px; border-bottom: 1px solid #f0f0f0; text-align: center; white-space: nowrap; }}
tr:nth-child(even) {{ background: #fafafa; }}
tr:hover {{ background: #fff3e0; }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; }}
.tag-annual {{ background: #e3f2fd; color: #1565c0; }}
.tag-quarter {{ background: #f3e5f5; color: #7b1fa2; }}
.tag-both {{ background: #fff3e0; color: #e65100; }}
.zt-high {{ color: #c0392b; font-weight: bold; }}
.growth-high {{ color: #27ae60; font-weight: bold; }}
.modal {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 100; }}
.modal-content {{ background: white; margin: 80px auto; padding: 24px; border-radius: 12px; max-width: 500px; box-shadow: 0 8px 32px rgba(0,0,0,0.2); }}
.modal-content h3 {{ margin-bottom: 16px; color: #c0392b; }}
.modal-content .info-row {{ display: flex; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }}
.modal-content .info-label {{ width: 100px; color: #888; flex-shrink: 0; }}
.modal-content .info-value {{ flex: 1; font-weight: 500; }}
.modal-content .close-btn {{ margin-top: 16px; padding: 8px 24px; background: #c0392b; color: white; border: none; border-radius: 6px; cursor: pointer; }}
.tips {{ background: #fff8e1; border-left: 4px solid #f39c12; padding: 16px; border-radius: 0 10px 10px 0; margin-bottom: 20px; font-size: 14px; line-height: 1.8; }}
</style>
</head>
<body>

<div class="header">
    <h1>📈 A股净利润高增长 + 近期涨停 筛选结果</h1>
    <div class="date">📅 {date_str} · 自动筛选</div>
</div>

<div class="summary">
    <div class="card">
        <div class="num" id="totalCount">{len(df)}</div>
        <div class="label">符合条件的股票</div>
    </div>
    <div class="card">
        <div class="num" id="annualCount">{len([r for r in rows_data if '年度' in r['condition'] and '季度' not in r['condition']])}</div>
        <div class="label">年度连续2年增长</div>
    </div>
    <div class="card">
        <div class="num" id="quarterCount">{len([r for r in rows_data if '季度' in r['condition'] and '年度' not in r['condition']])}</div>
        <div class="label">连续2季度增长</div>
    </div>
    <div class="card">
        <div class="num" id="bothCount">{len([r for r in rows_data if '年度' in r['condition'] and '季度' in r['condition']])}</div>
        <div class="label">同时满足两个条件</div>
    </div>
</div>

<div class="tips">
    <strong>筛选条件：</strong><br>
    1️⃣ 非ST股票<br>
    2️⃣ 最近2年年度净利润同比增长均 &gt; 20% <strong>或</strong> 连续2季度净利润同比增长均 &gt; 20%<br>
    3️⃣ 最近一个月有涨停记录<br>
    💡 点击表头可排序 · 点击股票名称查看详情 · 支持搜索和筛选
</div>

<div class="filters">
    <h3>🔍 搜索与筛选</h3>
    <div class="filter-row">
        <input type="text" id="searchInput" placeholder="搜索代码/名称/行业..." oninput="filterTable()">
        <select id="conditionFilter" onchange="filterTable()">
            <option value="">全部条件</option>
            <option value="年度">年度连续2年增长</option>
            <option value="季度">连续2季度增长</option>
        </select>
        <select id="ztFilter" onchange="filterTable()">
            <option value="">涨停次数</option>
            <option value="3">≥3次</option>
            <option value="5">≥5次</option>
        </select>
        <span class="count" id="filterCount">显示 {len(df)} 只</span>
    </div>
</div>

<div class="table-wrap" style="max-height: 70vh; overflow-y: auto;">
    <table id="stockTable">
        <thead>
            <tr>
                <th onclick="sortTable(0)">股票代码 <span class="sort">↕</span></th>
                <th onclick="sortTable(1)">股票简称 <span class="sort">↕</span></th>
                <th onclick="sortTable(2)">净利润同比增长 <span class="sort">↕</span></th>
                <th onclick="sortTable(3)">涨停次数 <span class="sort">↕</span></th>
                <th onclick="sortTable(4)">最近涨停 <span class="sort">↕</span></th>
                <th onclick="sortTable(5)">行业 <span class="sort">↕</span></th>
                <th>增长条件</th>
                <th onclick="sortTable(7)">ROE <span class="sort">↕</span></th>
                <th onclick="sortTable(8)">毛利率 <span class="sort">↕</span></th>
            </tr>
        </thead>
        <tbody id="tableBody"></tbody>
    </table>
</div>

<div class="modal" id="detailModal" onclick="if(event.target===this)closeModal()">
    <div class="modal-content" id="modalContent"></div>
</div>

<script>
const DATA = {rows_json};
let currentData = [...DATA];
let sortCol = -1, sortAsc = true;

function renderTable(data) {{
    const tbody = document.getElementById('tableBody');
    tbody.innerHTML = data.map(r => `
        <tr>
            <td>${{r.code}}</td>
            <td style="cursor:pointer;color:#c0392b;text-decoration:underline" onclick="showDetail('${{r.code}}','${{r.name}}')">${{r.name}}</td>
            <td class="${{parseFloat(r.profit_growth) > 50 ? 'growth-high' : ''}}">${{r.profit_growth}}</td>
            <td class="${{parseInt(r.zt_count) >= 3 ? 'zt-high' : ''}}">${{r.zt_count}}</td>
            <td>${{r.zt_latest}}</td>
            <td>${{r.industry}}</td>
            <td>${{getConditionTag(r.condition)}}</td>
            <td>${{r.roe}}</td>
            <td>${{r.gross_margin}}</td>
        </tr>
    `).join('');
    document.getElementById('filterCount').textContent = `显示 ${{data.length}} 只`;
}}

function getConditionTag(c) {{
    if (c.includes('年度') && c.includes('季度')) return '<span class="tag tag-both">双条件</span>';
    if (c.includes('年度')) return '<span class="tag tag-annual">年度增长</span>';
    if (c.includes('季度')) return '<span class="tag tag-quarter">季度增长</span>';
    return c;
}}

function filterTable() {{
    const search = document.getElementById('searchInput').value.toLowerCase();
    const cond = document.getElementById('conditionFilter').value;
    const ztMin = parseInt(document.getElementById('ztFilter').value) || 0;
    
    currentData = DATA.filter(r => {{
        if (search && !(r.code.toLowerCase().includes(search) || r.name.toLowerCase().includes(search) || r.industry.toLowerCase().includes(search))) return false;
        if (cond && !r.condition.includes(cond)) return false;
        if (ztMin && parseInt(r.zt_count) < ztMin) return false;
        return true;
    }});
    
    if (sortCol >= 0) applySortToData();
    renderTable(currentData);
}}

function sortTable(col) {{
    if (sortCol === col) sortAsc = !sortAsc;
    else {{ sortCol = col; sortAsc = false; }}
    applySortToData();
    renderTable(currentData);
}}

function applySortToData() {{
    const keys = ['code','name','profit_growth_num','zt_count_num','zt_latest','industry','','roe_num','gross_margin_num'];
    const key = keys[sortCol];
    if (!key) return;
    
    currentData.sort((a, b) => {{
        let va = a[key], vb = b[key];
        if (key.endsWith('_num')) {{
            va = parseFloat(String(va).replace('%','')) || 0;
            vb = parseFloat(String(vb).replace('%','')) || 0;
        }}
        if (va < vb) return sortAsc ? -1 : 1;
        if (va > vb) return sortAsc ? 1 : -1;
        return 0;
    }});
}}

function showDetail(code, name) {{
    const r = DATA.find(d => d.code === code && d.name === name);
    if (!r) return;
    const modal = document.getElementById('detailModal');
    const content = document.getElementById('modalContent');
    content.innerHTML = `
        <h3>${{r.code}} ${{r.name}}</h3>
        <div class="info-row"><span class="info-label">净利润</span><span class="info-value">${{r.profit}}</span></div>
        <div class="info-row"><span class="info-label">净利润增长</span><span class="info-value">${{r.profit_growth}}</span></div>
        <div class="info-row"><span class="info-label">营业收入</span><span class="info-value">${{r.revenue}}</span></div>
        <div class="info-row"><span class="info-label">营收增长</span><span class="info-value">${{r.revenue_growth}}</span></div>
        <div class="info-row"><span class="info-label">每股收益</span><span class="info-value">${{r.eps}}</span></div>
        <div class="info-row"><span class="info-label">ROE</span><span class="info-value">${{r.roe}}</span></div>
        <div class="info-row"><span class="info-label">毛利率</span><span class="info-value">${{r.gross_margin}}</span></div>
        <div class="info-row"><span class="info-label">行业</span><span class="info-value">${{r.industry}}</span></div>
        <div class="info-row"><span class="info-label">增长条件</span><span class="info-value">${{r.condition}}</span></div>
        <div class="info-row"><span class="info-label">月涨停次数</span><span class="info-value">${{r.zt_count}} 次</span></div>
        <div class="info-row"><span class="info-label">最近涨停</span><span class="info-value">${{r.zt_latest}}</span></div>
        <div class="info-row"><span class="info-label">涨停日期</span><span class="info-value" style="white-space:normal;line-height:1.8">${{r.zt_dates}}</span></div>
        <button class="close-btn" onclick="closeModal()">关闭</button>
    `;
    modal.style.display = 'block';
}}

function closeModal() {{
    document.getElementById('detailModal').style.display = 'none';
}}

// 初始化
currentData.forEach(r => {{
    r.profit_growth_num = r.profit_growth;
    r.zt_count_num = r.zt_count;
    r.roe_num = r.roe;
    r.gross_margin_num = r.gross_margin;
}});
renderTable(currentData);
</script>

</body>
</html>"""

    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"结果网页已生成: {HTML_FILE}")
    print(f"包含 {len(df)} 只股票的数据")
    return True


if __name__ == '__main__':
    generate_html()
