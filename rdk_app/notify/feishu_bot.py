import requests
import json
import os
from settings import *

class FeishuBot:
    def __init__(self):
        self.webhook_url = FEISHU_WEBHOOK
        self.app_id = FEISHU_APP_ID
        self.app_secret = FEISHU_APP_SECRET

    def get_tenant_access_token(self):
        """获取自建应用 Token，用于上传图片"""
        if not self.app_id or not self.app_secret:
            print("⚠️ [飞书组件] 未配置 App ID / App Secret，无法获取 Token。")
            return None
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        try:
            res = requests.post(url, json={"app_id": self.app_id, "app_secret": self.app_secret})
            return res.json().get("tenant_access_token")
        except Exception as e: 
            print(f"⚠️ [飞书组件] 获取 Token 失败: {e}")
            return None

    def upload_image(self, image_path):
        """上传本地图片到飞书，返回用于消息显示的 image_key"""
        token = self.get_tenant_access_token()
        if not token: 
            return None
        url = "https://open.feishu.cn/open-apis/im/v1/images"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            with open(image_path, "rb") as f:
                files = {"image": f, "image_type": (None, "message")}
                res = requests.post(url, headers=headers, files=files)
                return res.json().get("data", {}).get("image_key")
        except Exception as e:
            print(f"⚠️ [飞书组件] 图片上传失败: {e}")
            return None

    def reply_text(self, message_id, text):
        """回复飞书消息，供群机器人指令确认使用。"""
        token = self.get_tenant_access_token()
        if not token:
            return None

        url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            return res.json()
        except Exception as e:
            print(f"⚠️ [飞书组件] 文本回复失败: {e}")
            return None

    def reply_rich_post(self, message_id, title, blocks):
        """以富文本形式回复某条飞书消息。"""
        token = self.get_tenant_access_token()
        if not token:
            return None

        url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "msg_type": "post",
            "content": json.dumps({"zh_cn": {"title": title, "content": blocks}}, ensure_ascii=False),
        }
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            return res.json()
        except Exception as e:
            print(f"⚠️ [飞书组件] 富文本回复失败: {e}")
            return None


    def reply_interactive_card(self, message_id, card):
        """回复飞书交互卡片。"""
        token = self.get_tenant_access_token()
        if not token:
            return None
        url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        }
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            return res.json()
        except Exception as e:
            print(f"⚠️ [飞书组件] 交互卡片回复失败: {e}")
            return None

    def send_interactive_card(self, receive_id, card, receive_id_type="chat_id"):
        """向指定 chat/open_id 发送飞书交互卡片。"""
        token = self.get_tenant_access_token()
        if not token:
            return None
        url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        }
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            return res.json()
        except Exception as e:
            print(f"⚠️ [飞书组件] 交互卡片发送失败: {e}")
            return None

    def download_message_image(self, message_id, image_key, save_path):
        """下载飞书消息中的图片，用于手机照片录入人脸。"""
        token = self.get_tenant_access_token()
        if not token:
            return False

        url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{image_key}"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"type": "image"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=20)
            if res.status_code != 200:
                print(f"⚠️ [飞书组件] 图片下载失败: {res.status_code} {res.text[:200]}")
                return False
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(res.content)
            return True
        except Exception as e:
            print(f"⚠️ [飞书组件] 图片下载异常: {e}")
            return False

    def send_webhook(self, title, content, image_key=""):
        """通过 Webhook 向飞书群发送富文本报警或日报"""
        if not self.webhook_url:
            print("⚠️ [飞书组件] 未配置 Webhook，消息未发送。")
            return None
        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": title,
                        "content": [
                            [{"tag": "text", "text": content}],
                            [{"tag": "img", "image_key": image_key}] if image_key else []
                        ]
                    }
                }
            }
        }
        try:
            res = requests.post(self.webhook_url, json=payload, timeout=10)
            return res.json()
        except Exception as e:
            print(f"❌ [飞书组件] Webhook 发送失败: {e}")
            return None

    def send_rich_post(self, title, blocks):
        """发送多段富文本，blocks 为飞书 post content 二维数组。"""
        if not self.webhook_url:
            print("⚠️ [飞书组件] 未配置 Webhook，富文本消息未发送。")
            return None
        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": title,
                        "content": blocks,
                    }
                }
            },
        }
        try:
            res = requests.post(self.webhook_url, json=payload, timeout=10)
            return res.json()
        except Exception as e:
            print(f"❌ [飞书组件] 富文本 Webhook 发送失败: {e}")
            return None

# 导出单例
bot = FeishuBot()
