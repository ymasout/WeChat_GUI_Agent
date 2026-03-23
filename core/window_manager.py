import time
import ctypes
import pygetwindow as gw
import pyautogui
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class WindowManager:
    """
    微信窗口管理器
    负责微信窗口的发现、底层激活、前台锁定，及解决 DPI 缩放坐标系问题
    """
    
    def __init__(self, window_title="微信"):
        self.window_title = window_title
        # 初始化时强制处理 DPI 缩放
        self._set_dpi_awareness()
        self.window = None

    def _set_dpi_awareness(self):
        """
        强制调用 Windows DPI 感知 API。
        避免 Windows 系统自带的 125%、150% 缩放导致 pygetwindow 和 OpenCV 抓取的坐标不一致！
        """
        try:
            # PROCESS_PER_MONITOR_DPI_AWARE = 2
            awareness = ctypes.c_int(2)
            ctypes.windll.shcore.SetProcessDpiAwareness(awareness)
            logging.info("系统：成功设置 DPI 感知级别 2 (PROCESS_PER_MONITOR_DPI_AWARE)")
        except AttributeError:
            # 兼容老版 Windows 系统
            try:
                ctypes.windll.user32.SetProcessDPIAware()
                logging.info("系统：成功设置基础 DPI 感知 (SetProcessDPIAware)")
            except Exception as e:
                logging.error(f"异常：设置 DPI 感知时失败 - {e}")
        except Exception as e:
            logging.error(f"异常：调用高阶 DPI API 失败 - {e}")

    def find_window(self):
        """
        查找并获取指定标题（微信）的窗口对象
        并缓存到 self.window
        """
        windows = gw.getWindowsWithTitle(self.window_title)

        # 为了避免匹配到像"微信图片"、"微信读书"等带"微信"的无关窗口
        for w in windows:
            if w.title == self.window_title:
                self.window = w
                logging.info(f"窗口探测：成功找到 '{self.window_title}' 句柄:{w._hWnd}，坐标位置:({w.left}, {w.top}), 宽:{w.width}, 高:{w.height}")
                return True

        # 如果精确匹配失败，尝试模糊匹配包含"微信"的窗口
        all_windows = gw.getAllWindows()
        for w in all_windows:
            if w.title and "微信" in w.title and len(w.title) < 10:  # 限制标题长度，避免匹配到长标题的无关窗口
                self.window = w
                logging.info(f"窗口探测：模糊匹配到窗口 '{w.title}' 句柄:{w._hWnd}，坐标位置:({w.left}, {w.top}), 宽:{w.width}, 高:{w.height}")
                return True

        logging.warning(f"窗口探测：彻底失联！未能找到名为 '{self.window_title}' 的活动窗口")
        logging.warning("提示：请确保微信客户端已打开，并且窗口可见（未最小化）")
        return False

    def activate_window(self):
        """
        尝试激活微信窗口至前台。
        [核心避坑技巧] 解决 Windows 系统下“直接调 activate 只有任务栏闪烁而不置顶”的防弹窗抢占机制。
        """
        if not self.window:
            if not self.find_window():
                return False

        try:
            if self.window.isActive:
                logging.info("窗口控制：微信已在前台并且获取到焦点，无需重复拉起")
                return True

            if self.window.isMinimized:
                logging.info("窗口控制：检测到微信被最小化，尝试恢复...")
                self.window.restore()
                time.sleep(0.1)

            # --- 避坑绝招：利用模拟一次 Alt 按键打破系统的防骚扰前台焦点限制 ---
            logging.info("窗口控制：正在尝试绕过 Windows 拦截抢占顶级焦点...")
            pyautogui.press('alt')
            time.sleep(0.05)

            try:
                # 调用原始包提供的封装方法拉起窗口
                self.window.activate()
            except Exception as e:
                # pygetwindow 有时自带库底层的 SetForegroundWindow 会意外抛错代码 0
                logging.warning(f"窗口控制：由于安全限制 pygetwindow 报错({e})，改为强制调用 ctypes API...")
                ctypes.windll.user32.SetForegroundWindow(self.window._hWnd)
            
            time.sleep(0.1)  # 等待前台动画和焦点真正抢夺完毕

            if self.window.isActive:
                logging.info("窗口控制：✅ 焦点劫持成功，微信已在前台强制锁定")
                return True
            else:
                logging.warning("窗口控制：⚠️ 系统级拦截或正被全屏程序独占，未能完全置于前台！")
                return False
                
        except Exception as e:
            logging.error(f"窗口控制：强制激活窗口时抛出未知异常 - {e}")
            return False

    def minimize_window(self):
        """
        最小化微信窗口到任务栏。
        V3 核心策略：最小化后所有新消息都会产生红点，下次唤醒时即可扫描到。
        """
        if not self.window:
            return False
        try:
            self.window.minimize()
            logging.info("窗口控制：✅ 微信已最小化到任务栏")
            return True
        except Exception as e:
            logging.error(f"窗口控制：最小化失败 - {e}")
            return False

    def get_window_rect(self):
        """
        返回窗口当前最新的物理坐标与宽高
        在 OpenCV 截图时计算真实截图区域需要使用
        """
        if not self.window:
            if not self.find_window():
                return None
        
        return {
            "left": self.window.left,
            "top": self.window.top,
            "right": self.window.right,
            "bottom": self.window.bottom,
            "width": self.window.width,
            "height": self.window.height
        }

if __name__ == "__main__":
    # 本地极简联调代码：单独运行此文件可以测试是否能成功唤起并锁定你的微信
    wm = WindowManager()
    if wm.find_window():
        wm.activate_window()

