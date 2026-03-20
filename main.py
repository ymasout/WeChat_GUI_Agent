import os
import sys
import threading
import time
import webview

# 扩展路径包含 core
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.engine import WeChatEngine, log_queue, log

class AppApi:
    """
    暴露给前端 JS 调用的后端接口类 (Bridge)
    """
    def __init__(self):
        self.engine = WeChatEngine(config_path="data/config.yaml")
        self.engine_thread = None

    def start_engine(self):
        if self.engine.is_running:
            return {"status": "error", "msg": "引擎已经启动了！"}
        
        log("🚀 物理开关拨动：正在启动 AI 引擎...")
        self.engine_thread = threading.Thread(target=self.engine.start, daemon=True)
        self.engine_thread.start()
        return {"status": "ok", "msg": "引擎启动成功"}

    def stop_engine(self):
        if not self.engine.is_running:
            return {"status": "error", "msg": "引擎尚未启动！"}
        
        self.engine.stop()
        return {"status": "ok", "msg": "已发送挂起指令，当前巡逻周期结束后将待机。"}

    def get_engine_status(self):
        """前端查询引擎是否正在运行"""
        return {"running": self.engine.is_running}

    def get_logs(self):
        """前端网页会疯狂轮询这个接口，把后端的 log 抽过去渲染"""
        logs_to_send = []
        while not log_queue.empty():
            try:
                msg = log_queue.get_nowait()
                logs_to_send.append(msg)
            except:
                break
        return logs_to_send

    def minimize_app(self):
        """最小化窗口"""
        if hasattr(self, '_window') and self._window:
            self._window.minimize()

    def close_app(self):
        """关闭窗口"""
        if hasattr(self, '_window') and self._window:
            self._window.destroy()

if __name__ == "__main__":
    pwd = os.path.dirname(os.path.abspath(__file__))
    ui_path = os.path.join(pwd, "ui", "index.html")
    
    api = AppApi()
    
    # 创建无边框原生窗口（去掉 Windows 默认标题栏）
    window = webview.create_window(
        title="WeChat.AI",
        url=f"file://{ui_path}",
        js_api=api,
        width=400,
        height=780,
        resizable=False,
        frameless=True,      # 去掉原生标题栏
        easy_drag=True        # 允许拖拽移动窗口
    )
    
    # 把 window 对象挂到 api 上，方便前端调用最小化/关闭
    api._window = window
    
    # 启动 pywebview（关闭 debug 防止 DevTools 弹窗）
    webview.start(debug=False)
