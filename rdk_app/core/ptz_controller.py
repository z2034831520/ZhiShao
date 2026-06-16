import serial
import time
import threading
import queue

class PTZController:
    def __init__(self, port='/dev/ttyS1', baudrate=9600):
        self.port = port
        self.baudrate = baudrate
        self.serial_conn = None
        self.current_pan = -1
        self.current_tilt = -1
        self.lock = threading.Lock()
        
        # 引入指令队列，解耦视觉线程和串口 I/O
        self.cmd_queue = queue.Queue(maxsize=10)
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        
        self.connect()
        self.worker_thread.start()

    def connect(self):
        try:
            self.serial_conn = serial.Serial(self.port, self.baudrate, timeout=0.5)
            print(f"? [底层驱动] 云台串口连接成功: {self.port} @ {self.baudrate}")
            self.center()
            return True
        except Exception as e:
            self.serial_conn = None
            print(f"? [底层驱动] 串口连接失败: {e}")
            return False

    def is_open(self):
        return bool(self.serial_conn is not None and getattr(self.serial_conn, "is_open", False))

    def ensure_connected(self):
        if self.is_open():
            return True
        return self.connect()

    def _worker_loop(self):
        """后台专门负责发送串口指令的线程"""
        while self.running:
            try:
                # 阻塞等待指令，超时时间 0.1 秒以便能响应退出信号
                servo_id, angle = self.cmd_queue.get(timeout=0.1)
                
                if not self.ensure_connected():
                    print(f"?? [底层驱动] 云台串口不可用，未发送 {servo_id}{angle}")
                    self.cmd_queue.task_done()
                    continue
                    
                safe_angle = max(0, min(180, int(angle)))
                cmd_str = f"${servo_id}{safe_angle:03d}#"
                
                with self.lock:
                    try:
                        self.serial_conn.write(cmd_str.encode('ascii'))
                        # 这里的 sleep 只会阻塞当前后台线程，不会阻塞视觉主线程
                        time.sleep(0.05)
                    except Exception as e:
                        print(f"?? [底层驱动] 发送异常: {e}")
                
                self.cmd_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"?? [底层驱动] 队列处理异常: {e}")

    def _send_cmd(self, servo_id, angle):
        """将指令放入队列，立即返回，不阻塞调用者"""
        try:
            # 如果队列满了，说明串口处理不过来，直接丢弃旧指令，保持最新
            if self.cmd_queue.full():
                try:
                    self.cmd_queue.get_nowait()
                except queue.Empty:
                    pass
            self.cmd_queue.put_nowait((servo_id, angle))
            return True
        except queue.Full:
            return False

    def stop(self):
        self.running = False
        if self.worker_thread.is_alive():
            self.worker_thread.join(timeout=1.0)
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()

    def set_pan(self, angle):
        """左右 (S2 -> B)"""
        safe_angle = max(0, min(180, int(angle)))
        if safe_angle == self.current_pan:
            return True
        if self._send_cmd('B', safe_angle):
            self.current_pan = safe_angle
            return True
        return False

    def set_tilt(self, angle):
        """上下 (S1 -> A)"""
        safe_angle = max(0, min(180, int(angle)))
        if safe_angle == self.current_tilt:
            return True
        if self._send_cmd('A', safe_angle):
            self.current_tilt = safe_angle
            return True
        return False

    def center(self):
        ok_pan = self.set_pan(90)
        ok_tilt = self.set_tilt(90)
        return bool(ok_pan and ok_tilt)

# 必须顶格的全局单例
ptz = PTZController()
