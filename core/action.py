import time
import logging
from pynput.keyboard import Controller as KeyboardController, Key
from pynput.mouse import Controller as MouseController, Button
import pyperclip

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ActionExecutor:
    """
    终端物理执行器模块 (Action)
    负责将大模型生成的回复文本，以近乎人类操作电脑的方式安全地「注入」到微信输入框并发送。
    因为我们走的纯粹是系统顶层的硬件中断截获模拟，所以绝不会触碰微信底层的内存协议，安全性极高。
    """
    def __init__(self):
        self.keyboard = KeyboardController()
        # 扩展物理鼠标接口，强力防阻风控
        self.mouse = MouseController()
        
    def click_target(self, abs_window_x, abs_window_y, relative_x, relative_y):
        """
        强行接管你的物理鼠标，把指针瞬间甩到红点上点爆它！
        """
        target_x = int(abs_window_x + relative_x)
        target_y = int(abs_window_y + relative_y)
        
        logging.info(f"👆 物理执行层：鼠标指针正瞬移至屏幕 [{target_x}, {target_y}] 进行确认击杀...")
        self.mouse.position = (target_x, target_y)
        time.sleep(0.15) # 人类的延迟
        self.mouse.click(Button.left)
        
    def double_click_target(self, abs_window_x, abs_window_y, relative_x, relative_y):
        """
        双击指定位置。用于双击左侧导航栏的聊天图标以自动滚动未读消息。
        """
        target_x = int(abs_window_x + relative_x)
        target_y = int(abs_window_y + relative_y)
        
        logging.info(f"✌️ 物理执行层：鼠标指针正瞬移至 [{target_x}, {target_y}] 进行双击...")
        self.mouse.position = (target_x, target_y)
        time.sleep(0.15)
        self.mouse.click(Button.left, 2)
        
    def send_message(self, text: str):
        """
        向当前「已处于聚焦状态」的微信输入框砸入一段回答。
        完美链路设计：文本压入剪贴板 -> Ctrl+V 粘贴 -> Enter 回车
        （为什么不能直接用 keyboard 输出一个个字母？因为中文和 emoji 以及特殊排版用按键精灵容易造成乱码）
        """
        if not text:
            return
            
        logging.info("👊 物理执行层：接到任务！准备接管剪贴板并释放指令...")
        
        # 1. 记忆倾印：把大脑产出的回复压入操作系统的底层剪贴板
        pyperclip.copy(text)
        
        # 留白时间 0.3 秒，模拟人类目光正在从聊天记录往下看输入框的眼动空隙
        time.sleep(0.3)
        
        # 2. 经典连招组合拳：Ctrl + V
        with self.keyboard.pressed(Key.ctrl):
            self.keyboard.press('v')
            self.keyboard.release('v')
            
        # 留白时间 0.4 秒，模拟人类打完字大脑核对内容有没有病句的短暂停顿（强行防风控）
        time.sleep(0.4)
        
        # 3. 敲下回车键，让这一切物理发生！
        self.keyboard.press(Key.enter)
        self.keyboard.release(Key.enter)
        
        logging.info(f"👊 物理执行层：一套连招 (Ctrl+V + Enter) 已成功命中输入框！字数统计：{len(text)}")

    def press_escape(self):
        """
        按下 Esc 键，用于从当前聊天界面撤退回到主会话列表。
        """
        self.keyboard.press(Key.esc)
        self.keyboard.release(Key.esc)
        logging.info("👊 物理执行层：已按下 Esc 键，正在撤退回主列表...")

if __name__ == "__main__":
    # 极度危险的独立验证环节（请小心，一旦启动，你的手需要立刻切到你想测试的输入框上！）
    # 它盲打是不看你是谁的哈哈！
    executor = ActionExecutor()
    print("⚠️【极度危险】倒计时 3 秒后程序将强制接管键盘粘贴并敲下回车，请迅速将你的 Windows 窗口切到记事本或某个人的聊天界面上！")
    time.sleep(3)
    executor.send_message("你看得出来这是我编写的机器人强行写入的测试文字吗？[旺柴]")
    print("\n✅ 回车敲击成功，程序安全退出。")
