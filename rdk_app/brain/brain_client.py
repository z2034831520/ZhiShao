import re
import requests
import json
import cv2
import base64
from settings import (
    BRAIN_URL_ASK,
    BRAIN_URL_ANALYZE,
    BRAIN_URL_PRIVACY_CHECK,
    BRAIN_URL_SUMMARIZE,
    CARE_CITY,
    CARE_LOCATION,
    USE_IP_GEOLOCATION,
)

class BrainClient:
    def __init__(self):
        self.ask_url = BRAIN_URL_ASK
        self.analyze_url = BRAIN_URL_ANALYZE
        self.summarize_url = BRAIN_URL_SUMMARIZE
        self.privacy_url = BRAIN_URL_PRIVACY_CHECK
        
        # 默认使用固定看护地点，避免手机热点/运营商出口导致城市漂移。
        self.local_city, self.local_geo_location = self._load_care_location()
        # 天气只在用户明确询问时懒加载，避免普通看护问答主动夹带天气。
        self.real_weather = "暂无气象数据"
        
        # 🚀 核心新增：短期记忆体（滑动窗口）
        self.chat_history = [] 
        self.MAX_HISTORY = 3  # 只记住最近 3 轮对话，防止 Prompt 太长导致云端拒绝或变傻

    def _load_care_location(self):
        if not USE_IP_GEOLOCATION:
            print(f"📍 [看护地点] 已使用固定看护地点: {CARE_LOCATION}")
            return CARE_CITY, CARE_LOCATION
        return self._fetch_local_geo_info()

    def _fetch_local_geo_info(self):
        print("🌍 [边缘阵地] 正在探测本机所处的真实物理坐标...")
        try:
            res = requests.get("http://ip-api.com/json/?lang=zh-CN", timeout=5)
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "success":
                    city = data.get('city', '')
                    loc = f"{data.get('country', '')} {data.get('regionName', '')} {city}"
                    print(f"📍 [边缘阵地] 嗅探成功！本机真实坐标已锚定: {loc}")
                    return city, loc
        except Exception as e:
            print(f"⚠️ [边缘阵地] 网络定位失败...")
        return "Unknown", "当地城市"

    def _weather_day_index(self, question):
        q = question or ""
        if "后天" in q:
            return 2, "后天"
        if "明天" in q:
            return 1, "明天"
        return 0, "今天"

    def _extract_weather_city(self, question):
        q = (question or "").replace("@智哨管家", "").strip()
        for keyword in ("天气", "气温", "温度", "下雨", "下雪", "冷不冷", "热不热", "刮风"):
            idx = q.find(keyword)
            if idx > 0:
                candidate = q[:idx]
                for token in ("今天", "明天", "后天", "现在", "当前", "当地", "看护地点", "的", "会", "请问", "帮我看看"):
                    candidate = candidate.replace(token, "")
                candidate = re.sub(r"[^一-龥]", "", candidate).strip()
                if 2 <= len(candidate) <= 8:
                    return candidate
        match = re.search(r"([一-龥]{2,8})(?:今天|明天|后天).*(?:天气|气温|温度|下雨|下雪|冷不冷|热不热)", q)
        if match:
            return match.group(1)
        return self.local_city

    def _fetch_real_weather(self, city, question=""):
        """按提问城市优先获取天气；没写城市时使用默认看护地点。"""
        if not city or city == "Unknown":
            return "暂无气象数据"
        day_index, day_label = self._weather_day_index(question)
        try:
            res = requests.get(f"https://wttr.in/{city}?format=j1&lang=zh", timeout=5)
            if res.status_code == 200:
                data = res.json()
                days = data.get("weather") or []
                if days:
                    day = days[min(day_index, len(days) - 1)]
                    hourly = day.get("hourly") or []
                    noon = hourly[min(4, len(hourly) - 1)] if hourly else {}
                    desc_items = noon.get("weatherDesc") or []
                    desc = desc_items[0].get("value") if desc_items else "天气状况未明"
                    chance = noon.get("chanceofrain", "未知")
                    weather_info = (
                        f"{city}{day_label}天气：{desc}，"
                        f"{day.get('mintempC', '?')}~{day.get('maxtempC', '?')}℃，"
                        f"平均 {day.get('avgtempC', '?')}℃，降水概率约 {chance}%"
                    )
                    print(f"🌤️ [气象雷达] 成功获取天气: {weather_info}")
                    return weather_info
        except Exception as e:
            print(f"⚠️ [气象雷达] 天气查询失败: {e}")
        try:
            res = requests.get(f"https://wttr.in/{city}?format=%C+%t", timeout=3)
            if res.status_code == 200:
                weather_info = f"{city}当前天气：{res.text.strip()}"
                print(f"🌤️ [气象雷达] 成功获取实时天气: {weather_info}")
                return weather_info
        except Exception:
            pass
        return "暂无气象数据"

    def _question_mentions_weather(self, question):
        keywords = (
            "天气", "气温", "温度", "冷不冷", "热不热", "下雨", "下雪", "刮风",
            "阴天", "晴天", "开窗", "通风", "穿衣", "加衣", "空调", "暖气",
        )
        return any(word in (question or "") for word in keywords)

    def _local_weather_answer(self):
        if self.real_weather and self.real_weather != "暂无气象数据":
            return f"{self.real_weather}。天气数据来自公开接口，可能会有延迟，建议以权威气象预报为准。"
        return "当前暂时没有查到天气数据，建议稍后再问一次，或直接说明城市名称。"

    def ask(self, question, image=None, system_note=""):
        """向大脑发送问题，携带短期历史记忆；天气只在用户明确询问时加入。"""
        needs_weather = self._question_mentions_weather(question)
        weather_context = "本次问题未询问天气，请不要在回答中提到天气、气温、开窗或穿衣建议。"
        if needs_weather:
            query_city = self._extract_weather_city(question)
            self.real_weather = self._fetch_real_weather(query_city, question)
            weather_context = (
                f"本次问题涉及天气/温度/通风/穿衣；用户询问地点优先：{query_city}；"
                f"默认看护地点：{self.local_geo_location}；"
                f"外部气象数据：{self.real_weather}。"
            )
        
        # 🚀 核心逻辑：组装历史对话字符串
        history_str = "无"
        if self.chat_history:
            history_str = "\n".join([f"主人: {q}\n管家: {a}" for q, a in self.chat_history])
        
        # 注入记忆的终极 Prompt
        full_prompt = f"""你是一个贴心的家庭智能看护管家。
        【系统绝密上下文】：
        1. {weather_context}
        
        【历史对话记录（短期记忆）】：
        {history_str}

        【本次额外约束】：
        {system_note or "无"}
        
        【判断与回答规则】：
        1. 最高优先级：只回答主人这一次问的问题，不要扩展到主人没有问的内容。
        2. 禁止答非所问：主人没问天气、气温、地点、产品说明、隐私策略、健康建议、监控链接时，不要主动提这些内容。
        3. 只有当主人明确询问天气、气温、开窗、通风或穿衣时，才允许提到天气；否则绝对不要主动加入天气、气温、开窗或穿衣建议。
        4. 如果问题明确要求看当前画面、判断人在做什么、看一下现场或脱敏画面，应围绕画面中可见动作回答，并将 need_image 设为 true。
        5. 如果从图像或状态无法判断主人所问内容，要直接说“当前无法准确判断”，不要改答其他话题，也不要编造细节。
        6. 回答可以更具体，通常 3 到 5 句话；可以分析人数、姿态、动作变化、互动关系、环境类别和安全状态，但必须都与主人问题直接相关。
        7. 不要写开场寒暄，不要输出无关解释；如果信息不足，说明“不确定”的同时给出你能确定的观察依据。
        
        现在主人向你提问："{question}"
        
        必须且只能输出严格的 JSON：
        {{
            "answer": "这里写你对主人问题的具体回答文本，语气要自然温暖。",
            "need_image": true或false
        }}"""

        payload = {
            "question": question,   
            "prompt": full_prompt,  
            "image": ""
        }
        
        if image is not None:
            _, buffer = cv2.imencode('.jpg', image, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
            payload["image"] = base64.b64encode(buffer).decode('utf-8')

        try:
            if needs_weather:
                print("📡 [云端通信] 正在将携带【天气】与【记忆】的指令发送至大脑...")
            else:
                print("📡 [云端通信] 正在将携带【记忆】的指令发送至大脑...")
            response = requests.post(self.ask_url, json=payload, timeout=20)
            if response.status_code == 200:
                res_data = response.json()
                
                # 🚀 核心闭环：如果大模型成功回答了，就把这一轮对话存入记忆记事本！
                answer = res_data.get("answer", "")
                if answer:
                    self.chat_history.append((question, answer))
                    # 如果记忆超过 3 轮，像队列一样把最老的那轮丢掉（防撑爆）
                    if len(self.chat_history) > self.MAX_HISTORY:
                        self.chat_history.pop(0)
                        
                return res_data
                
        except requests.exceptions.RequestException as e:
            print(f"❌ 呼叫大脑失败: {e}")
        if needs_weather:
            return {"answer": self._local_weather_answer(), "need_image": False}
        return None

    def analyze_critical_event(self, img_path):
        try:
            with open(img_path, 'rb') as f:
                files = {'image': (img_path, f, 'image/jpeg')}
                response = requests.post(self.analyze_url, files=files, timeout=30)
                if response.status_code == 200: return response.json()
        except Exception: pass
        return None

    def privacy_check(self, image):
        """Ask the cloud brain whether the current raw frame is safe to show briefly."""
        if image is None:
            return {
                "safe_to_show": False,
                "risk_level": "blocked",
                "reason": "当前没有可用于复核的画面。",
                "confidence": 1.0,
                "evidence": ["RDK 当前没有可用原始画面"],
                "block_type": "no_image",
            }
        try:
            _, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            payload = {"image": base64.b64encode(buffer).decode("utf-8")}
            response = requests.post(self.privacy_url, json=payload, timeout=20)
            if response.status_code == 200:
                data = response.json()
                required = {"safe_to_show", "risk_level", "reason"}
                if not required.issubset(data.keys()):
                    return {
                        "safe_to_show": False,
                        "risk_level": "unknown",
                        "reason": "隐私复核返回结果不完整，已按保护策略拒绝开启真实画面。",
                        "confidence": 0.0,
                        "evidence": ["返回 JSON 缺少必要字段"],
                        "block_type": "service_unavailable",
                    }
                data.setdefault("confidence", 0.0)
                data.setdefault("evidence", [])
                data.setdefault("block_type", "none" if data.get("safe_to_show") else data.get("risk_level", "uncertain"))
                return data
            return {
                "safe_to_show": False,
                "risk_level": "unknown",
                "reason": f"隐私复核服务 HTTP {response.status_code}，已按保护策略拒绝开启真实画面。",
                "confidence": 0.0,
                "evidence": [response.text[:120] if response.text else "服务未返回正文"],
                "block_type": "service_unavailable",
            }
        except requests.exceptions.RequestException as e:
            print(f"⚠️ [隐私复核] 调用云端大脑失败: {e}")
            return {
                "safe_to_show": False,
                "risk_level": "unknown",
                "reason": f"隐私复核服务不可用：{e}。已按保护策略拒绝开启真实画面。",
                "confidence": 0.0,
                "evidence": [f"RDK 无法连接隐私复核服务：{self.privacy_url}"],
                "block_type": "service_unavailable",
            }
        except Exception as e:
            print(f"⚠️ [隐私复核] 处理隐私复核结果异常: {e}")
        return {
            "safe_to_show": False,
            "risk_level": "unknown",
            "reason": "隐私复核处理异常，已按保护策略拒绝开启真实画面。",
            "confidence": 0.0,
            "evidence": [],
            "block_type": "service_unavailable",
        }

    def summarize_logs(self, log_content):
        try:
            response = requests.post(self.summarize_url, json={"log_content": log_content}, timeout=30)
            if response.status_code == 200: return response.json().get('summary', '')
        except Exception: pass
        return ""

brain = BrainClient()
