import logging
import socket
import threading
import time

import cv2
from flask import Flask, Response, jsonify, request
from werkzeug.serving import WSGIRequestHandler


def get_lan_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_monitor_url(port=5000):
    return f"http://{get_lan_ip()}:{port}"


class QuietRequestHandler(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        return


class WebDashboard:
    def __init__(self, app_service, host="0.0.0.0", port=5000):
        self.app_service = app_service
        self.host = host
        self.port = port
        self.flask = Flask(__name__)
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        self._routes()

    def _jpeg_stream(self, source):
        while True:
            frame = self.app_service.get_video_frame(source)
            quality = 68 if source == "raw" else 72
            ret, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
            if ret:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
            time.sleep(0.05 if source == "raw" else 0.08)

    def _routes(self):
        @self.flask.route("/video/raw")
        def video_raw():
            resp = Response(self._jpeg_stream("raw"), mimetype="multipart/x-mixed-replace; boundary=frame")
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["X-Accel-Buffering"] = "no"
            return resp

        @self.flask.route("/video/skeleton")
        def video_skeleton():
            resp = Response(self._jpeg_stream("skeleton"), mimetype="multipart/x-mixed-replace; boundary=frame")
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["X-Accel-Buffering"] = "no"
            return resp

        @self.flask.route("/api/status")
        def status():
            return jsonify(self.app_service.status_payload())

        @self.flask.route("/health")
        def health():
            return jsonify({
                "ok": True,
                "service": "ZhiShao WebDashboard",
                "monitor_url": get_monitor_url(self.port),
                "lan_ip": get_lan_ip(),
                "note": "手机必须能访问 RDK 所在网络。子女不在同一网络时，需要 HTTPS 中转或内网穿透。",
            })

        @self.flask.route("/api/command", methods=["POST"])
        def command():
            data = request.get_json(silent=True) or {}
            ok, reply = self.app_service.handle_command(data.get("command", ""), source="web")
            return jsonify({"ok": ok, "reply": reply})

        @self.flask.route("/")
        def index():
            return self._html()

    def _html(self):
        return """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>智哨安心看护</title>
  <style>
    :root { color-scheme: dark; --bg:#101418; --panel:#171d23; --line:#26313a; --text:#eef6f8; --muted:#9aabb7; --cyan:#4cc9f0; --green:#80ed99; --amber:#ffb703; --red:#ff6b6b; }
    * { box-sizing: border-box; }
    html, body { height:100%; overflow:hidden; }
    body { margin:0; background:var(--bg); color:var(--text); font-family:"Microsoft YaHei","Segoe UI",sans-serif; letter-spacing:0; }
    header { height:42px; display:flex; align-items:center; justify-content:space-between; gap:10px; padding:0 14px; border-bottom:1px solid var(--line); background:#12181d; }
    h1 { margin:0; font-size:15px; }
    .stamp { color:var(--muted); font-size:12px; white-space:nowrap; }
    main { height:calc(100vh - 42px); display:grid; grid-template-columns:minmax(420px,1.45fr) minmax(330px,.55fr); gap:8px; padding:8px; overflow:hidden; }
    main > div:first-child, main > div:first-child > section { min-height:0; display:flex; flex-direction:column; }
    section { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:8px; }
    h2 { margin:0 0 6px; font-size:14px; }
    .hero { display:grid; grid-template-columns:1fr auto; gap:8px; align-items:center; }
    .comfort { font-size:22px; font-weight:700; color:var(--green); line-height:1.15; }
    .summary { color:#dcebf0; white-space:pre-wrap; line-height:1.35; margin-top:5px; font-size:12px; }
    .badge { border:1px solid var(--line); border-radius:999px; padding:5px 8px; color:var(--muted); font-size:12px; }
    .video { margin-top:7px; flex:1; min-height:0; background:#050709; border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    .video img { width:100%; height:100%; min-height:0; object-fit:contain; display:block; background:#050709; }
    .toolbar { display:flex; flex-wrap:wrap; gap:6px; margin-top:7px; }
    .side { min-height:0; display:grid; grid-template-rows:auto auto auto auto minmax(58px,.8fr); gap:8px; overflow:hidden; }
    .grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:6px; }
    .metric { border:1px solid var(--line); border-radius:6px; padding:7px; min-height:52px; background:#12181d; }
    .metric b { display:block; font-size:18px; margin-bottom:2px; }
    .metric span { color:var(--muted); font-size:11px; }
    .lockPanel { display:grid; gap:8px; }
    .lockRow { display:flex; justify-content:space-between; gap:8px; border-bottom:1px solid rgba(255,255,255,.06); padding:4px 0; font-size:12px; }
    .lockRow span:first-child { color:var(--muted); white-space:nowrap; }
    .lockRow b { text-align:right; font-weight:600; }
    .lockReason { margin-top:4px; padding:6px; border-radius:6px; background:#101820; color:#dcebf0; line-height:1.35; font-size:12px; }
    .statusPanel { display:grid; gap:0; }
    .statusRow { display:flex; justify-content:space-between; gap:8px; border-bottom:1px solid rgba(255,255,255,.06); padding:4px 0; font-size:12px; }
    .statusRow:last-child { border-bottom:0; }
    .statusRow span:first-child { color:var(--muted); white-space:nowrap; }
    .statusRow b { text-align:right; font-weight:600; }
    .ok { color:var(--green); }
    .warnText { color:var(--amber); }
    pre { white-space:pre-wrap; word-break:break-word; margin:0; font-family:inherit; line-height:1.35; font-size:12px; }
    .buttons { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:6px; }
    button { border:1px solid var(--line); border-radius:6px; background:#1e2830; color:var(--text); min-height:30px; cursor:pointer; font-size:12px; padding:0 8px; }
    button:hover { border-color:var(--cyan); }
    button.primary { background:#164052; border-color:#236077; }
    button.warn { background:#3a2d1a; border-color:#735c27; }
    .events { display:flex; flex-direction:column; gap:8px; max-height:240px; overflow:auto; }
    .event { border-left:3px solid var(--cyan); padding:7px 8px; background:#12181d; border-radius:4px; font-size:13px; }
    .event small { display:block; color:var(--muted); margin-top:3px; }
    .modalBack { position:fixed; inset:0; display:none; align-items:center; justify-content:center; padding:18px; background:rgba(0,0,0,.72); z-index:20; }
    .modal { width:min(560px,100%); background:#151d24; border:1px solid #38505f; border-radius:8px; padding:18px; box-shadow:0 18px 60px rgba(0,0,0,.35); }
    .modal h2 { font-size:18px; margin-bottom:12px; }
    .modal p { color:#dcebf0; line-height:1.65; margin:8px 0; }
    .modal .rule { color:var(--amber); }
    .modalActions { display:flex; gap:10px; justify-content:flex-end; margin-top:16px; flex-wrap:wrap; }
    .check { display:flex; gap:8px; align-items:flex-start; color:#dcebf0; margin-top:12px; line-height:1.5; }
    .check input { margin-top:4px; }
    @media(max-width:900px){ html,body{height:auto;overflow:auto;} header{height:52px;} main{height:auto;display:grid;grid-template-columns:1fr;overflow:visible;} main > div:first-child, main > div:first-child > section{display:block;} .side{display:flex;overflow:visible;} .grid{grid-template-columns:repeat(2,minmax(0,1fr));} .video,.video img{min-height:300px;} .hero{grid-template-columns:1fr;} }
  </style>
</head>
<body>
  <header><h1>智哨安心看护</h1><div class="stamp" id="stamp">连接中</div></header>
  <main>
    <div>
      <section>
        <div class="hero">
          <div>
            <div class="comfort" id="comfort">加载中</div>
            <div class="summary" id="summary">正在读取本地看护状态...</div>
          </div>
          <div class="badge" id="privacy">边界看护</div>
        </div>
        <div class="toolbar">
          <button class="primary" onclick="switchVideo('skeleton')">查看脱敏画面</button>
          <button class="warn" onclick="showPrivacyModal()">临时确认真实画面</button>
          <button onclick="cmd('close_raw_view')">关闭真实画面</button>
        </div>
        <div class="video"><img id="video" src="/video/skeleton" alt="脱敏看护画面"></div>
      </section>
    </div>
    <div class="side">
      <section><h2>今日概览</h2><div class="grid">
        <div class="metric"><b id="seen">0.0</b><span>看到目标 分钟</span></div>
        <div class="metric"><b id="active">0.0</b><span>活动 分钟</span></div>
        <div class="metric"><b id="suspect">0</b><span>疑似风险 次</span></div>
        <div class="metric"><b id="alert">0</b><span>确认告警 次</span></div>
      </div></section>
      <section><h2>锁定与跟随</h2>
        <div class="lockPanel">
          <div class="lockRow"><span>锁定对象</span><b id="lockedName">未锁定</b></div>
          <div class="lockRow"><span>锁定轨迹</span><b id="lockedTrack">无</b></div>
          <div class="lockRow"><span>当前识别</span><b id="activeTrack">无</b></div>
          <div class="lockRow"><span>云台跟随</span><b id="ptzTrack">无</b></div>
          <div class="lockRow"><span>跟随锁定对象</span><b id="followingLocked">否</b></div>
          <div class="lockRow"><span>锁定状态</span><b id="lockState">未锁定</b></div>
          <div class="lockRow"><span>衣着匹配</span><b id="clothScore">0.00</b></div>
          <div class="lockReason" id="followReason">暂无目标</div>
        </div>
      </section>
      <section><h2>系统状态</h2>
        <div class="statusPanel">
          <div class="statusRow"><span>安心状态</span><b id="briefComfort">读取中</b></div>
          <div class="statusRow"><span>摄像头</span><b id="briefCamera">读取中</b></div>
          <div class="statusRow"><span>自动跟随</span><b id="briefFollow">读取中</b></div>
          <div class="statusRow"><span>摔倒检测</span><b id="briefFall">读取中</b></div>
          <div class="statusRow"><span>可信目标</span><b id="briefTarget">0</b></div>
          <div class="statusRow"><span>真实画面</span><b id="briefRaw">默认关闭</b></div>
        </div>
      </section>
      <section><h2>控制</h2><div class="buttons">
        <button onclick="cmd('lock')">锁定</button><button onclick="cmd('unlock')">取消锁定</button><button onclick="cmd('center')">回中</button>
        <button onclick="cmd('left')">左转</button><button onclick="cmd('right')">右转</button><button onclick="cmd('up')">上调</button>
        <button onclick="cmd('down')">下调</button><button onclick="cmd('pause_follow')">暂停跟随</button><button onclick="cmd('resume_follow')">恢复跟随</button>
        <button onclick="cmd('mode_conservative')">保守模式</button><button onclick="cmd('mode_sensitive')">灵敏模式</button><button onclick="cmd('report')">日报</button>
      </div></section>
      <section><h2>最近事件</h2><div class="events" id="events"></div></section>
    </div>
  </main>

  <div class="modalBack" id="privacyModal" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
    <div class="modal">
      <h2 id="modalTitle">临时查看真实画面确认</h2>
      <p>真实画面只用于确认父母此刻是否安全。点击确认后，系统会先调用大模型判断当前画面是否存在明显隐私泄露。</p>
      <p>只有大模型确认无明显隐私风险时，真实画面才会开启 3 分钟，并叠加“临时安全确认”水印。</p>
      <p class="rule">请避免录屏、截图、转发或让无关人员观看。若当前状态平稳，建议优先使用脱敏画面和电话问候。</p>
      <label class="check">
        <input id="privacyAck" type="checkbox" />
        <span>我确认本次查看仅用于安全确认，并理解系统会先做大模型隐私复核，通过后才限时开启。</span>
      </label>
      <div class="modalActions">
        <button onclick="hidePrivacyModal()">取消</button>
        <button class="warn" onclick="confirmRawView()">确认开启 3 分钟</button>
      </div>
    </div>
  </div>

  <script>
    const min = v => ((Number(v || 0) / 60).toFixed(1));
    const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    function switchVideo(kind){ document.getElementById('video').src='/video/'+kind+'?t='+Date.now(); }
    function showPrivacyModal(){ document.getElementById('privacyAck').checked=false; document.getElementById('privacyModal').style.display='flex'; }
    function hidePrivacyModal(){ document.getElementById('privacyModal').style.display='none'; }
    async function confirmRawView(){
      if(!document.getElementById('privacyAck').checked){
        document.getElementById('stamp').textContent='请先确认隐私提示';
        return;
      }
      hidePrivacyModal();
      await cmd('open_raw_view');
    }
    async function refresh(){
      const res = await fetch('/api/status'); const data = await res.json(); const m = data.metrics || {}; const s = data.status || {};
      document.getElementById('seen').textContent = min(m.seen_seconds);
      document.getElementById('active').textContent = min(m.active_seconds);
      document.getElementById('suspect').textContent = Number(m.suspect_fall_count || 0).toFixed(0);
      document.getElementById('alert').textContent = Number(m.confirmed_fall_count || 0).toFixed(0);
      document.getElementById('comfort').textContent = data.comfort_text || '读取中';
      document.getElementById('summary').textContent = data.family_summary || '';
      document.getElementById('privacy').textContent = s.raw_video_allowed ? ('真实画面剩余 ' + s.raw_video_seconds_left + ' 秒') : '真实画面默认关闭';
      document.getElementById('lockedName').textContent = s.locked_name || '未锁定';
      document.getElementById('lockedTrack').textContent = s.locked_track_id || '无';
      document.getElementById('activeTrack').textContent = s.active_track_id || '无';
      document.getElementById('ptzTrack').textContent = s.ptz_follow_track_id || '无';
      document.getElementById('followingLocked').textContent = s.following_locked ? '是' : '否';
      document.getElementById('followingLocked').className = s.following_locked ? 'ok' : 'warnText';
      document.getElementById('lockState').textContent = s.lock_state || '未锁定';
      document.getElementById('clothScore').textContent = Number(s.cloth_score || 0).toFixed(2);
      document.getElementById('followReason').textContent = s.follow_reason || '暂无目标';
      const fallMap = {NORMAL:'平稳', CANDIDATE:'观察中', SUSPECT:'疑似风险', VALIDATING:'复核中', CONFIRMED:'已告警', REJECTED:'已拦截', VALIDATION_FAILED:'复核失败'};
      document.getElementById('briefComfort').textContent = data.comfort_text || '读取中';
      document.getElementById('briefCamera').textContent = s.camera_ok ? '正常' : '无画面';
      document.getElementById('briefCamera').className = s.camera_ok ? 'ok' : 'warnText';
      document.getElementById('briefFollow').textContent = s.follow_enabled ? '开启' : '暂停';
      document.getElementById('briefFall').textContent = (s.fall_mode || '保守') + ' / ' + (fallMap[s.fall_state] || s.fall_state || '未知');
      document.getElementById('briefTarget').textContent = String(s.target_count || 0);
      document.getElementById('briefRaw').textContent = s.raw_video_allowed ? ('开启 ' + s.raw_video_seconds_left + ' 秒') : '默认关闭';
      document.getElementById('briefRaw').className = s.raw_video_allowed ? 'warnText' : '';
      const age = data.video_age || {};
      const rawAge = Number(age.raw || 0);
      const skAge = Number(age.skeleton || 0);
      const lag = (rawAge > 1.5 || skAge > 2.5) ? ` · 画面延迟 raw ${rawAge.toFixed(1)}s / 骨架 ${skAge.toFixed(1)}s` : '';
      document.getElementById('stamp').textContent = '已连接 ' + new Date().toLocaleTimeString() + lag;
      const box = document.getElementById('events'); box.innerHTML='';
      (data.events || []).forEach(e => {
        const div=document.createElement('div');
        div.className='event';
        const d=e.data || {};
        const parts=[];
        if(d.reason) parts.push('原因：' + d.reason);
        if(d.risk_level) parts.push('风险：' + d.risk_level);
        if(d.confidence !== undefined && d.confidence !== null) parts.push('置信度：' + Number(d.confidence || 0).toFixed(2));
        if(Array.isArray(d.evidence) && d.evidence.length) parts.push('依据：' + d.evidence.slice(0,3).join('；'));
        const detail = parts.length ? `<small>${esc(parts.join(' | '))}</small>` : '';
        div.innerHTML=`${esc(e.message || e.type)}${detail}<small>${esc(e.ts || '')} · ${esc(e.type || '')}</small>`;
        box.appendChild(div);
      });
    }
    async function cmd(command){
      const res=await fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command})});
      const data=await res.json();
      document.getElementById('stamp').textContent=data.reply || '命令已发送';
      if(command === 'open_raw_view' && data.ok) switchVideo('raw');
      if(command === 'open_raw_view' && !data.ok) switchVideo('skeleton');
      if(command === 'close_raw_view') switchVideo('skeleton');
      refresh();
    }
    refresh(); setInterval(refresh,3000);
  </script>
</body>
</html>
        """

    def start(self):
        def worker():
            print(f"📺 [产品看板] Web 安心看护页已启动: {get_monitor_url(self.port)}")
            self.flask.run(host=self.host, port=self.port, threaded=True, use_reloader=False, request_handler=QuietRequestHandler)

        threading.Thread(target=worker, daemon=True).start()
