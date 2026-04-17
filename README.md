# stockscreener

部署步骤：
1. pip3 install akshare dnspython openpyxl pandas
2. chmod +x run_daily.sh
3. crontab -e 添加: 0 18 * * * /workspace/run_daily.sh
