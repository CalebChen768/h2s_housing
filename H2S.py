import os
import yaml
import http.client
import json
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from Notifier import Notifier
import time
import logging
from collections import defaultdict

# 初始化通知器
notifier = Notifier()

# 错误统计
error_counter = defaultdict(int)
error_alert_sent = {}

# 日志设置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

# 加载配置
def load_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def get_city_map(config):
    return config.get("cities", {})

def get_scan_settings(config):
    scan_cfg = config.get("scan_settings", {})
    return {
        "interval_seconds": scan_cfg.get("interval_seconds", 2),
        "basic_rent_limit": scan_cfg.get("basic_rent_limit", 1000),
        "allowance_threshold": scan_cfg.get("allowance_threshold", 1),
        "timezone": scan_cfg.get("timezone", "Europe/Amsterdam")
    }

# 初始化配置
config = load_config()
city_map = get_city_map(config)
scan_settings = get_scan_settings(config)

BASIC_RENT_LIMIT = scan_settings.get("basic_rent_limit")
RENT_ALLOWANCE = scan_settings.get("allowance_threshold")
TIME_INTERVAL = scan_settings.get("interval_seconds")
TIME_ZONE = scan_settings.get("timezone")
timezone = ZoneInfo(TIME_ZONE)

# 状态变量
cities = list(city_map.keys())
existing_data = []
sent_morning = False
sent_evening = False
last_check_date = datetime.now(timezone).date()

# 活跃通知
def check_and_send_active_notice():
    global sent_morning, sent_evening, last_check_date
    now = datetime.now(timezone)

    if now.date() != last_check_date:
        sent_morning = False
        sent_evening = False
        last_check_date = now.date()

    current_time = now.time()

    if dtime(8, 0) <= current_time < dtime(8, 10) and not sent_morning:
        notifier.send_all(
            title="🌅 早间系统活跃通知",
            long_content="系统仍在运行（早上8点）",
            short_content="系统已活跃（8AM）",
            url="https://holland2stay.com",
            send_telegram=True
        )
        sent_morning = True
        logging.info("✅ 发送了早间活跃通知")

    if dtime(20, 0) <= current_time < dtime(20, 10) and not sent_evening:
        notifier.send_all(
            title="🌆 晚间系统活跃通知",
            long_content="系统仍在运行（晚上8点）",
            short_content="系统已活跃（8PM）",
            url="https://holland2stay.com",
            send_telegram=True
        )
        sent_evening = True
        logging.info("✅ 发送了晚间活跃通知")

# 获取城市数据
def fetch_city_data(city_code):
    conn = http.client.HTTPSConnection("api.holland2stay.com")
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
        "Origin": "https://holland2stay.com",
        "Referer": "https://holland2stay.com/",
        "Accept": "*/*",
        "Connection": "keep-alive"
    }

    payload = json.dumps({
        "operationName": "GetCategories",
        "variables": {
            "currentPage": 1,
            "id": "Nw==",
            "filters": {
                "available_to_book": {"eq": "179"},
                "city": {"eq": city_code},
                "category_uid": {"eq": "Nw=="}
            },
            "pageSize": 50,
            "sort": {"available_startdate": "ASC"}
        },
        "query": """query GetCategories($id: String!, $pageSize: Int!, $currentPage: Int!, $filters: ProductAttributeFilterInput!, $sort: ProductAttributeSortInput) {
            categories(filters: {category_uid: {in: [$id]}}) {
                items {
                    uid
                    ...CategoryFragment
                    __typename
                }
                __typename
            }
            products(
                pageSize: $pageSize,
                currentPage: $currentPage,
                filter: $filters,
                sort: $sort
            ) {
                ...ProductsFragment
                __typename
            }
        }
        fragment CategoryFragment on CategoryTree {
            uid
            meta_title
            meta_keywords
            meta_description
            __typename
        }
        fragment ProductsFragment on Products {
            items {
                name
                city
                url_key
                offer_text
                offer_text_two
                allowance_price
                next_contract_startdate
                basic_rent
                price_range {
                    minimum_price {
                        regular_price {
                            value
                            currency
                        }
                    }
                }
                __typename
            }
            __typename
        }"""
    })
    
    conn.request("POST", "/graphql/", payload, headers)
    response = conn.getresponse()
    data = response.read().decode("utf-8")
    return json.loads(data)

# 数据筛选
def extract_useful_info(item):
    return {
        "url_key": item.get("url_key"),
        "allowance_price": item.get("allowance_price"),
        "next_contract_startdate": item.get("next_contract_startdate").split(" ")[0],
        "basic_rent": item.get("basic_rent"),
        "regular_price": (
            item.get("price_range", {})
                .get("minimum_price", {})
                .get("regular_price", {})
                .get("value")
        )
    }

def filter_items(item, rent_limit=None, allowance_limit=None):
    try:
        if rent_limit is not None and (item.get("basic_rent") is None or float(item.get("basic_rent")) >= rent_limit):
            return False
        if allowance_limit is not None and (item.get("allowance_price") is None or float(item.get("allowance_price")) < allowance_limit):
            return False
    except ValueError:
        return False
    return True

# 主任务
def job():
    for city in cities:
        json_data = fetch_city_data(city)
        items = json_data["data"]["products"]["items"]
        for item in items:
            useful_info = extract_useful_info(item)
            if filter_items(useful_info, BASIC_RENT_LIMIT, RENT_ALLOWANCE) and useful_info['url_key'] not in existing_data:
                print(f"发现新房源: {item['name']}")
                room_url = f"https://holland2stay.com/residences/{useful_info['url_key']}.html"
                notifier.send_all(
                    title=f"{city_map[city]} -- {item['name']}",
                    long_content=f"City: {city_map[city]}\nName: {item['name']}\nURL: {room_url}\nBasic Rent: {useful_info['basic_rent']}\nAllowance Price: {useful_info['allowance_price']}\nTotal Price: {useful_info['regular_price']}\nNext Contract Start Date: {useful_info['next_contract_startdate']}",
                    short_content=f"基本租金: {useful_info['basic_rent']} 房补: {useful_info['allowance_price']} 总价: {useful_info['regular_price']}",
                    url=room_url,
                    send_telegram=True,
                    send_bark=True,
                    send_twilio=True
                )
            existing_data.append(useful_info['url_key'])

# 启动
if __name__ == "__main__":
    notifier.send_all(
        title="🔔 系统启动通知",
        long_content="系统已启动并开始运行",
        short_content="系统已启动",
        url="https://holland2stay.com",
        send_telegram=True,
        send_bark=True,
        send_twilio=True
    )

    count = 0
    while True:
        try:
            check_and_send_active_notice()
            if count % 150 == 0:
                logging.info(f"抓取任务 @ {datetime.now(timezone).strftime('%Y-%m-%d %H:%M:%S')}")
            job()
        except Exception as e:
            logging.error(f"报错: {e}")
            now = datetime.now(timezone)
            hour_key = now.strftime('%Y-%m-%d %H')
            error_counter[hour_key] += 1

            if error_counter[hour_key] > 10 and not error_alert_sent.get(hour_key, False):
                notifier.send_all(
                    title="🚨 每小时错误超限",
                    long_content=f"{hour_key} 出现了超过 10 次错误，请检查系统状态！",
                    short_content=f"{hour_key} 错误次数: {error_counter[hour_key]}",
                    url="https://holland2stay.com",
                    send_telegram=True
                )
                logging.warning(f"⚠️ 触发错误报警（{hour_key} 错误次数: {error_counter[hour_key]}）")
                error_alert_sent[hour_key] = True

        count += 1
        time.sleep(TIME_INTERVAL)