import os
import yaml
import requests
import threading
import logging
from datetime import datetime
from urllib.parse import quote
from twilio.rest import Client

# Initialize logger
logger = logging.getLogger("Notifier")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)





class Notifier:
    def __init__(self):
        config = self._load_config()

        # Telegram configuration
        telegram_cfg = config.get("telegram", {})
        self.telegram_token = telegram_cfg.get("token")
        self.telegram_chat_id = telegram_cfg.get("chat_id")

        # Bark configuration
        bark_cfg = config.get("bark", {})
        self.bark_url_prefix = f"{bark_cfg.get('base', '').rstrip('/')}/{bark_cfg.get('key', '')}" if bark_cfg.get('key') else None

        # Twilio configuration
        twilio_cfg = config.get("twilio", {})
        self.twilio_client = None
        if twilio_cfg.get("account_sid") and twilio_cfg.get("auth_token"):
            self.twilio_client = Client(twilio_cfg["account_sid"], twilio_cfg["auth_token"])
        self.twilio_from = twilio_cfg.get("from")
        self.twilio_to = twilio_cfg.get("to")

    def _load_config(self):
        root_path = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(root_path, "config.yaml")

        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def send_all(self, 
                 title="出现新的房子", 
                 long_content="", 
                 short_content="", 
                 url=None, 
                 send_telegram=False,
                 send_bark=False,
                 send_twilio=False):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        message = f"{long_content}\n🕒 发送时间：{timestamp}"

        threads = []

        if send_telegram and self.telegram_token and self.telegram_chat_id:
            threads.append(threading.Thread(target=self._send_telegram, args=(message,)))

        if send_bark and self.bark_url_prefix:
            threads.append(threading.Thread(target=self._send_bark, args=(title, short_content or long_content, url)))

        if send_twilio and self.twilio_client and self.twilio_from and self.twilio_to:
            threads.append(threading.Thread(target=self._send_twilio, args=(message,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        logger.info("Notification sent successfully")

    def _send_telegram(self, message: str):
        try:
            url = f'https://api.telegram.org/bot{self.telegram_token}/sendMessage'
            data = {'chat_id': self.telegram_chat_id, 'text': message}
            response = requests.post(url, data=data)
            logger.info('[Telegram] Status: %s', response.status_code)
        except Exception as e:
            logger.error('[Telegram] Error: %s', e)

    def _send_bark(self, title: str, content: str, url: str = None):
        try:
            if url and url in content:
                content = content.replace(url, '').strip()

            encoded_title = quote(title)
            encoded_content = quote(content)
            push_url = f"{self.bark_url_prefix}/{encoded_title}/{encoded_content}?level=timeSensitive"
            
            if url:
                encoded_url = quote(url, safe=':/?&=')
                push_url += f"&url={encoded_url}"

            logger.info(f"[Bark] URL: {push_url}")
            response = requests.get(push_url)
            if response.status_code == 200:
                logger.info('[Bark] Notification sent successfully')
            else:
                logger.warning('[Bark] Failed to send notification, status code: %s', response.status_code)
        except Exception as e:
            logger.error('[Bark] Error: %s', e)

    def _send_twilio(self, message: str):
        try:
            msg = self.twilio_client.messages.create(
                body=message,
                from_=self.twilio_from,
                to=self.twilio_to
            )
            logger.info('[Twilio] Status: %s', msg.status)
        except Exception as e:
            logger.error('[Twilio] Error: %s', e)


if __name__ == "__main__":
    notifier = Notifier()
    notifier.send_all(
        title="Test Notification",
        long_content="This is a test notification https://example.com",
        url="https://example.com",
        send_telegram=True,
        send_bark=True,
        send_twilio=True
    )