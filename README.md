# KAP OTP Bot

Telegram bot for an authorised ProRewards OTP login flow.

Confirmed endpoints:
- POST /server/userLogin
- POST /server/login/finish
- GET /server/checkUser

Set BOT_TOKEN as an environment variable. Do not commit Telegram tokens, JWTs, OTPs, cookies, or authorization headers.

Run:
pip install -r requirements.txt
python bot.py
