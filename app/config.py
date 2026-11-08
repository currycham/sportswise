import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
ENV = os.getenv('APP_ENV', 'development')
DB_PATH = Path(os.getenv('DB_PATH', str(ROOT / 'data/sportswise.db')))
if not DB_PATH.is_absolute():
    DB_PATH = ROOT / DB_PATH
SITE_URL = os.getenv('SITE_URL', 'http://127.0.0.1:8500').rstrip('/')
INVITE_CODE = os.getenv('INVITE_CODE', '')
ADMIN_EMAILS = set(os.getenv('ADMIN_EMAILS', '').lower().split(','))
API_KEY = os.getenv('DEEPSEEK_API_KEY', '')
BASE_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/')
MODEL = os.getenv('MODEL_NAME', 'deepseek-chat')
DAILY_BUDGET = float(os.getenv('DAILY_BUDGET_YUAN', '20'))
USER_DAILY_CALLS = int(os.getenv('USER_DAILY_CALLS', '30'))
PRICE_IN = float(os.getenv('MODEL_PRICE_INPUT', '2'))
PRICE_OUT = float(os.getenv('MODEL_PRICE_OUTPUT', '8'))
SMTP_HOST = os.getenv('SMTP_HOST', '')
SMTP_PORT = int(os.getenv('SMTP_PORT', '465'))
SMTP_USER = os.getenv('SMTP_USER', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
SMTP_FROM = os.getenv('SMTP_FROM', '') or SMTP_USER

PLANNER_MODEL = os.getenv('PLANNER_MODEL', 'deepseek-flash')
PLANNER_REVIEW_MODEL = os.getenv('PLANNER_REVIEW_MODEL', PLANNER_MODEL)
PLANNER_EXPERT_MODEL = os.getenv('PLANNER_EXPERT_MODEL', 'deepseek-v4-pro')
PLANNER_EFFORT = os.getenv('PLANNER_EFFORT', 'low')
PLANNER_AUTHOR_EFFORT = os.getenv('PLANNER_AUTHOR_EFFORT', 'low')
PLANNER_MAX_TOKENS = int(os.getenv('PLANNER_MAX_TOKENS', '32768'))
PLANNER_REVIEW_MAX_TOKENS = int(os.getenv('PLANNER_REVIEW_MAX_TOKENS', '32768'))
PLANNER_PRICE_IN = float(os.getenv('PLANNER_PRICE_INPUT', '3'))
PLANNER_PRICE_OUT = float(os.getenv('PLANNER_PRICE_OUTPUT', '12'))
PLANNER_EXPERT_PRICE_IN = float(os.getenv('PLANNER_EXPERT_PRICE_INPUT', '12'))
PLANNER_EXPERT_PRICE_OUT = float(os.getenv('PLANNER_EXPERT_PRICE_OUTPUT', '48'))
