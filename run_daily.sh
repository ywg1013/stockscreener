#!/bin/bash
# A股净利润高增长+近期涨停 股票筛选 - 每日定时任务脚本
# 设置环境变量，确保cron环境下能正确找到python和akshare

export PATH="/root/.pyenv/shims:/root/.pyenv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PYENV_ROOT="/root/.pyenv"

# 项目目录
SCRIPT_DIR="/workspace/stock_growth_filter"
LOG_FILE="${SCRIPT_DIR}/logs/cron_$(date +%Y%m%d).log"

# 激活pyenv
eval "$(pyenv init -)" 2>/dev/null

# 运行筛选脚本
cd "${SCRIPT_DIR}"
python3 stock_filter.py >> "${LOG_FILE}" 2>&1

# 自动发送邮件（通过直接连接QQ MX服务器）
python3 send_email.py >> "${LOG_FILE}" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 定时任务执行完成" >> "${LOG_FILE}"
