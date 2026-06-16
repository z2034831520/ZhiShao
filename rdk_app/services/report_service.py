import os
import threading
import time
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from settings import BASE_DIR, REPORT_HOUR, REPORT_MINUTE


class ReportService:
    def __init__(self, store, bot, brain):
        self.store = store
        self.bot = bot
        self.brain = brain
        self.log_dir = os.path.join(BASE_DIR, "logs")
        os.makedirs(self.log_dir, exist_ok=True)

    def minutes(self, seconds):
        return float(seconds or 0) / 60.0

    def _weekly_chart(self):
        rows = self.store.get_week_metrics(7)
        dates = [row.get("date", "")[-5:] for row in rows]
        seen = [self.minutes(row.get("seen_seconds", 0)) for row in rows]
        active = [self.minutes(row.get("active_seconds", 0)) for row in rows]
        plt.style.use("dark_background")
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(dates, seen, color="#4cc9f0", marker="o", linewidth=2.5, label="Seen")
        ax.plot(dates, active, color="#80ed99", marker="o", linewidth=2.5, label="Active")
        ax.set_xlabel("Date")
        ax.set_ylabel("Minutes")
        ax.set_title("ZhiShao 7-Day Care Trend")
        ax.grid(color="#333333", linestyle="--", linewidth=0.5)
        ax.legend()
        fig.subplots_adjust(left=0.09, right=0.97, top=0.88, bottom=0.14)
        path = os.path.join(self.log_dir, "weekly_trend.png")
        plt.savefig(path, dpi=150, facecolor="#121212")
        plt.close()
        return path, rows

    def _today_chart(self, metrics):
        labels = ["Seen", "Active", "Search"]
        values = [
            self.minutes(metrics.get("seen_seconds", 0)),
            self.minutes(metrics.get("active_seconds", 0)),
            self.minutes(metrics.get("search_seconds", 0)),
        ]
        plt.style.use("dark_background")
        fig, ax = plt.subplots(figsize=(8, 4.2))
        bars = ax.bar(labels, values, color=["#4cc9f0", "#80ed99", "#ffb703"])
        ax.set_ylabel("Minutes")
        ax.set_title("Today Runtime Summary")
        ax.grid(axis="y", color="#333333", linestyle="--", linewidth=0.5)
        for bar, value in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05, f"{value:.1f}", ha="center", color="white")
        fig.subplots_adjust(left=0.11, right=0.96, top=0.86, bottom=0.14)
        path = os.path.join(self.log_dir, f"daily_report_{datetime.now().strftime('%Y-%m-%d')}.png")
        plt.savefig(path, dpi=150, facecolor="#121212")
        plt.close()
        return path

    def _comfort(self, metrics):
        confirmed = int(metrics.get("confirmed_fall_count", 0) or 0)
        suspects = int(metrics.get("suspect_fall_count", 0) or 0)
        seen = self.minutes(metrics.get("seen_seconds", 0))
        active = self.minutes(metrics.get("active_seconds", 0))
        if confirmed:
            return "需要尽快确认", "今天出现过高风险提醒，建议优先确认父母是否安好。"
        if suspects:
            return "有过疑似风险", "今天出现过疑似风险，系统已记录并保持关注，建议晚间温和问候一次。"
        if seen < 5:
            return "今日数据较少", "今天有效看到目标的时间偏少，可能是设备视野、网络或父母不在房间导致。"
        if active < 10:
            return "整体平稳，活动偏少", "今天整体平稳，但活动量偏少，可以温和提醒父母多走动。"
        return "整体平稳", "今天未发现高风险事件，活动与看护记录整体平稳。"

    def _advice(self, metrics, events):
        fallback = "今晚可以简单问候父母饮水、用餐和睡眠情况；如果父母愿意，也可以陪他们做几分钟轻量活动。"
        try:
            text = str({
                "metrics": metrics,
                "events": events[:8],
                "requirement": "用家属关怀语气给出80字以内建议，强调尊重隐私和必要确认。",
            })
            summary = self.brain.summarize_logs(text)
            return summary or fallback
        except Exception:
            return fallback

    def send_report(self):
        metrics = self.store.get_metrics()
        events = self.store.list_events(limit=30, date=self.store.today())
        weekly_path, rows = self._weekly_chart()
        today_path = self._today_chart(metrics)
        weekly_key = self.bot.upload_image(weekly_path) if os.path.exists(weekly_path) else None
        today_key = self.bot.upload_image(today_path) if os.path.exists(today_path) else None
        level, opening = self._comfort(metrics)
        today_active = self.minutes(metrics.get("active_seconds", 0))
        yesterday_active = self.minutes(rows[-2].get("active_seconds", 0)) if len(rows) > 1 else 0
        diff = today_active - yesterday_active
        family_actions = self.store.count_family_actions()
        blocks = [
            [{"tag": "text", "text": f"今日安心状态：{level}\n{opening}"}],
            [{"tag": "text", "text": (
                f"活动概览\n看到目标：{self.minutes(metrics.get('seen_seconds', 0)):.1f} 分钟\n"
                f"活动时长：{today_active:.1f} 分钟，{'较昨日增加' if diff >= 0 else '较昨日减少'} {abs(diff):.1f} 分钟\n"
                f"最后看到：{metrics.get('last_seen_time') or '暂无记录'}\n"
                f"当前检测模式：{metrics.get('fall_mode') or '保守'}"
            )}],
            [{"tag": "text", "text": (
                f"异常与处置\n疑似摔倒：{int(metrics.get('suspect_fall_count', 0) or 0)} 次\n"
                f"确认提醒：{int(metrics.get('confirmed_fall_count', 0) or 0)} 次\n"
                f"云端拦截误报：{int(metrics.get('rejected_fall_count', 0) or 0)} 次\n"
                f"云端复核失败：{int(metrics.get('validation_failed_count', 0) or 0)} 次\n"
                f"家属处置记录：{family_actions} 条"
            )}],
            [{"tag": "text", "text": (
                "隐私边界\n"
                "今日日报只展示状态、趋势和脱敏图表；真实画面默认不主动推送，仅在家属临时确认安全时限时开启。"
            )}],
        ]
        if today_key:
            blocks.append([{"tag": "img", "image_key": today_key}])
        if weekly_key:
            blocks.append([{"tag": "img", "image_key": weekly_key}])
        blocks.append([{"tag": "text", "text": f"智哨关怀建议\n{self._advice(metrics, events)}"}])
        self.bot.send_rich_post("智哨家属安心日报", blocks)
        print("✅ [日报系统] 家属安心日报已投递。")

    def start_timer(self):
        def worker():
            print(f"⏰ [时钟守护] 日报定时器激活！目标时间每日 -> {REPORT_HOUR:02d}:{REPORT_MINUTE:02d}")
            while True:
                now = time.localtime()
                target = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, REPORT_HOUR, REPORT_MINUTE, 0, 0, 0, -1))
                curr = time.time()
                time.sleep((target + 86400) - curr if target <= curr else target - curr)
                try:
                    print("\n🔔 [时钟守护] 触达定时时间点，正在生成健康日报...")
                    self.send_report()
                except Exception as exc:
                    print(f"❌ [时钟守护] 日报发送异常: {exc}")
                time.sleep(2)

        threading.Thread(target=worker, daemon=True).start()
