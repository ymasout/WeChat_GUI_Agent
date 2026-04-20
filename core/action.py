import time
import random
import logging
from pynput.keyboard import Controller as KeyboardController, Key
from pynput.mouse import Controller as MouseController, Button
import pyperclip

# P1 阶段新增：Windows API 用于焦点窗口校验（物理级防冲突中断）
try:
    import win32gui
    import win32process
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    logging.warning("⚠️ pywin32 未安装，焦点窗口校验功能将被禁用。请运行: pip install pywin32")

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

        # P1 阶段新增：物理级防冲突中断机制
        self.wechat_hwnd = None  # 微信窗口句柄缓存
        self.last_mouse_position = None  # 上一次鼠标位置（用于检测用户抢夺）
        self.mouse_jump_threshold = 50  # 降低阈值：50px 足以检测真实用户干预（原100px）
        self._handle_initialized = False  # 标记窗口句柄是否已初始化（延迟初始化）
        self.is_running_checker = None

    def set_running_checker(self, checker_func):
        """设定引擎中断状态校验函数"""
        self.is_running_checker = checker_func

        # 不在初始化时获取窗口句柄，改为首次使用时获取
        # 这样可以避免启动时的潜在问题

    def _refresh_wechat_handle(self):
        """刷新微信窗口句柄缓存"""
        try:
            def enum_windows_callback(hwnd, _):
                """枚举窗口回调函数，查找微信窗口"""
                try:
                    title = win32gui.GetWindowText(hwnd)
                    # 匹配微信窗口标题（包含 "微信"）
                    if title and "微信" in title:
                        self.wechat_hwnd = hwnd
                        return False  # 找到后停止枚举
                except Exception as e:
                    logging.debug(f"枚举窗口时出错: {e}")
                return True  # 继续枚举

            win32gui.EnumWindows(enum_windows_callback, None)
            if self.wechat_hwnd:
                logging.debug(f"🔒 安全防线：已获取微信窗口句柄 {self.wechat_hwnd}")
            else:
                logging.warning("⚠️ 安全防线：未找到微信窗口句柄，焦点校验功能将降级")
        except Exception as e:
            logging.error(f"❌ 安全防线：获取微信窗口句柄失败 - {e}")

    def _verify_foreground_window(self) -> bool:
        """
        P1 阶段新增：验证当前前台窗口是否为微信
        :return: True 表示微信仍在前台，False 表示焦点已丢失
        """
        if not WIN32_AVAILABLE:
            return True  # 降级模式：假设一切正常

        try:
            # 延迟初始化窗口句柄（首次使用时才获取）
            if not self._handle_initialized:
                self._refresh_wechat_handle()
                self._handle_initialized = True

            foreground_hwnd = win32gui.GetForegroundWindow()
            if foreground_hwnd == self.wechat_hwnd:
                return True

            # 如果缓存的句柄失效，尝试重新获取
            if not self.wechat_hwnd:
                self._refresh_wechat_handle()
                return foreground_hwnd == self.wechat_hwnd

            # 检查是否是微信的其他子窗口（如聊天窗口）
            try:
                foreground_title = win32gui.GetWindowText(foreground_hwnd)
                if foreground_title and "微信" in foreground_title:
                    # 更新缓存的句柄为当前前台窗口
                    self.wechat_hwnd = foreground_hwnd
                    logging.debug(f"🔄 安全防线：更新微信窗口句柄为 {foreground_hwnd}")
                    return True
            except Exception:
                pass

            logging.warning(f"🚨 安全防线：焦点已丢失！当前前台窗口不是微信（句柄: {foreground_hwnd}）")
            return False

        except Exception as e:
            logging.error(f"❌ 安全防线：验证前台窗口失败 - {e}")
            return True  # 出错时降级，避免误杀

    def _check_mouse_hijack(self) -> bool:
        """
        P1 阶段新增：检测鼠标是否被用户抢夺
        :return: True 表示检测到抢夺，应中断执行
        """
        try:
            current_position = self.mouse.position

            # 首次记录位置
            if self.last_mouse_position is None:
                self.last_mouse_position = current_position
                return False

            # 计算鼠标移动距离
            dx = abs(current_position[0] - self.last_mouse_position[0])
            dy = abs(current_position[1] - self.last_mouse_position[1])
            distance = (dx ** 2 + dy ** 2) ** 0.5

            # 更新上次位置
            self.last_mouse_position = current_position

            # 检测大幅跳跃（用户正在抢夺鼠标）
            if distance > self.mouse_jump_threshold:
                logging.warning(f"🚨 安全防线：检测到鼠标大幅跳跃 {distance:.1f}px，用户可能在抢夺控制权！")
                return True

            return False

        except Exception as e:
            logging.error(f"❌ 安全防线：鼠标抢夺检测失败 - {e}")
            return False

    def _wait_for_user_idle(self, check_interval: float = 1.0, retry_interval: float = 5.0) -> bool:
        """
        P1 阶段增强：等待用户操作完成（鼠标静止），无限循环直到用户停止操作
        :param check_interval: 检查间隔（秒），每次检查的间隔时间
        :param retry_interval: 重试间隔（秒），每检查一轮后的提示间隔
        :return: True 表示用户已停止操作（总是会返回 True，除非出错）
        """
        try:
            wait_round = 0
            while True:
                if self.is_running_checker and not self.is_running_checker():
                    raise RuntimeError("EngineStopped")

                wait_round += 1

                # 记录当前位置
                start_position = self.mouse.position
                time.sleep(check_interval)

                # 检查鼠标是否移动
                current_position = self.mouse.position
                dx = abs(current_position[0] - start_position[0])
                dy = abs(current_position[1] - start_position[1])
                distance = (dx ** 2 + dy ** 2) ** 0.5

                if distance < 10:  # 10px 以内认为静止
                    total_wait_time = (wait_round - 1) * check_interval
                    logging.info(f"✅ 安全防线：用户操作已完成，等待时间 {total_wait_time:.1f} 秒")
                    self._record_mouse_position()  # 重新记录基准位置
                    return True
                else:
                    # 用户仍在操作，每5秒提示一次
                    if wait_round % int(retry_interval / check_interval) == 0:
                        logging.info(f"⏳ 安全防线：用户仍在操作（鼠标移动 {distance:.1f}px），5秒后重试...")

        except KeyboardInterrupt:
            # 用户主动中断（Ctrl+C）
            logging.warning("⚠️ 安全防线：用户中断等待操作")
            raise
        except Exception as e:
            logging.error(f"❌ 安全防线：等待用户空闲失败 - {e}")
            return True  # 出错时假设用户已停止操作

    def _record_mouse_position(self):
        """记录当前鼠标位置（用于后续抢夺检测）"""
        try:
            self.last_mouse_position = self.mouse.position
        except Exception as e:
            logging.debug(f"记录鼠标位置失败: {e}")

    def _stream_type_text(self, text: str) -> bool:
        """
        拟人流式输出：将文本逐字粘贴到输入框，模拟人类打字行为
        包含防线校验、随机延迟和偶发手误模拟

        :param text: 要输出的文本
        :return: True 表示输出成功，False 表示中断（安全防线触发或出错）
        """
        if not text:
            return True

        logging.info(f"⌨️ 拟人流式输出：开始逐字粘贴，总字数 {len(text)}...")

        # 常见汉字列表，用于手误模拟
        common_chars = "的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说产种面而方后多定行学法所民得经十三之进着等部度家电力里如水化高自二理起小物现实量都两体制机当使点从业本去把性好应开它合还因由其些然前外天政四日那社义事平形相全表间样与关各重新线内数正心反你明看原又么利比或但质气第向道命此变条只没结解问意建月公无系军很情者最立代想已通并提直题党程展五果料象员革位入常文总次品式活设及管特件长求老头基资边流路级少图山统接知较将组见计别她手角期根论运农指几九区强放决西被干做必战先回则任取据处队南给色光门即保治北造百规热领七海口东导器压志世金增争济阶油思术极交受联什认六共权收证改清己美再采转更单风切打白教速花带安场身车例真务具万每目至达走积示议声报斗完类八离华名确才科张信马节话米整空元况今集温传土许步群广石记需段研界拉林律叫且究观越织装影算低持音众书布复容儿须际商非验连断深难近矿千周委素技备半办青省列习响约支般史感劳便团往酸历市克何除消构府称太准精值号率族维划选标写存候毛亲快效斯院查江型眼王按格养易置派层片始却专状育厂京识适属圆包火住调满县局照参红细引听该铁价严首底液官德随病苏失尔死讲配女黄推显谈罪神艺呢席含企望密批营项防举球英氧势告李台落木帮轮杀亚迫职促氧消词"

        try:
            for i, char in enumerate(text):
                if self.is_running_checker and not self.is_running_checker():
                    logging.warning("🔴 拦截：引掣已停止，强制切断流式输出。")
                    return False

                # 安全防线轮询：检查鼠标抢夺
                if self._check_mouse_hijack():
                    logging.warning("🚨 安全防线：流式输出中检测到用户干预，等待用户操作完成...")
                    try:
                        self._wait_for_user_idle(check_interval=1.0, retry_interval=5.0)
                        logging.info("✅ 安全防线：用户操作已完成，继续流式输出...")
                        # 重新记录鼠标位置作为新基准
                        self._record_mouse_position()
                    except KeyboardInterrupt:
                        logging.warning("⚠️ 用户中断流式输出操作")
                        return False
                    except RuntimeError as e:
                        if str(e) == "EngineStopped": return False
                        logging.warning(f"⚠️ 安全防线：等待用户空闲失败，继续执行 - {e}")
                    except Exception as e:
                        logging.warning(f"⚠️ 安全防线：检查失败，继续执行 - {e}")

                # 安全防线轮询：验证焦点窗口
                if not self._verify_foreground_window():
                    logging.error("🚨 安全防线：流式输出中焦点已丢失，中断操作！")
                    return False

                # 手误模拟：2% 的概率触发
                if random.random() < 0.02:
                    # 随机选择一个常见汉字作为错别字
                    typo_char = random.choice(common_chars)
                    try:
                        pyperclip.copy(typo_char)
                        with self.keyboard.pressed(Key.ctrl):
                            self.keyboard.press('v')
                            self.keyboard.release('v')
                        logging.debug(f"🎭 手误模拟：粘贴了错别字 '{typo_char}'")
                        time.sleep(0.5)  # 停顿 0.5 秒模拟发现错误

                        # 模拟按下 Backspace 键删除错别字
                        self.keyboard.press(Key.backspace)
                        self.keyboard.release(Key.backspace)
                        logging.debug(f"🎭 手误模拟：已删除错别字")
                        time.sleep(0.3)  # 停顿后继续
                    except Exception as e:
                        logging.warning(f"⚠️ 手误模拟失败，继续正常输出 - {e}")

                # 正常粘贴当前字符
                try:
                    pyperclip.copy(char)
                    with self.keyboard.pressed(Key.ctrl):
                        self.keyboard.press('v')
                        self.keyboard.release('v')

                    # 物理拟人：随机停顿 0.08-0.25 秒
                    delay = random.uniform(0.08, 0.25)
                    time.sleep(delay)

                    # 每 20 个字符输出一次进度
                    if (i + 1) % 20 == 0:
                        logging.info(f"⌨️ 拟人流式输出：已输出 {i + 1}/{len(text)} 个字符...")

                except Exception as e:
                    logging.error(f"❌ 流式输出失败，在第 {i + 1} 个字符处出错: {e}")
                    return False

            logging.info(f"✅ 拟人流式输出：完成全部 {len(text)} 个字符的输出")
            return True

        except KeyboardInterrupt:
            logging.warning("⚠️ 用户中断流式输出操作")
            return False
        except Exception as e:
            logging.error(f"❌ 流式输出异常中断: {e}")
            return False

    def click_target(self, abs_window_x, abs_window_y, relative_x, relative_y):
        """
        强行接管你的物理鼠标，把指针瞬间甩到红点上点爆它！
        P1 阶段增强：添加用户干预检测，防止点击到错误位置
        """
        target_x = int(abs_window_x + relative_x)
        target_y = int(abs_window_y + relative_y)

        logging.info(f"👆 物理执行层：鼠标指针正瞬移至屏幕 [{target_x}, {target_y}] 进行确认击杀...")

        # P1 阶段增强：在移动鼠标前先等待一小段时间，确保鼠标静止
        try:
            # 记录当前位置作为基准，然后等待一小段时间
            self._record_mouse_position()
            time.sleep(0.2)  # 等待 200ms，确保鼠标静止

            # 再次检查是否有用户干预
            if self._check_mouse_hijack():
                logging.warning("🚨 安全防线：点击前检测到用户干预，等待用户操作完成...")
                self._wait_for_user_idle(check_interval=1.0, retry_interval=5.0)
                logging.info("✅ 安全防线：用户操作已完成，继续点击...")
        except KeyboardInterrupt:
            logging.warning("⚠️ 用户中断操作，取消点击...")
            return
        except RuntimeError as e:
            if str(e) == "EngineStopped": return
        except Exception as e:
            logging.warning(f"⚠️ 安全防线：点击前检查失败，继续执行 - {e}")

        # 现在移动鼠标
        self.mouse.position = (target_x, target_y)
        time.sleep(0.15) # 人类的延迟

        # P1 阶段增强：点击后再次检查（防止在移动过程中用户干预）
        # 注意：这里需要重新记录基准位置为移动后的位置
        self._record_mouse_position()
        time.sleep(0.1)  # 等待一小段时间

        try:
            if self._check_mouse_hijack():
                logging.warning("🚨 安全防线：点击后检测到用户干预，取消本次点击...")
                return
        except Exception as e:
            logging.warning(f"⚠️ 安全防线：点击后检查失败，继续执行 - {e}")

        self.mouse.click(Button.left)

    def double_click_target(self, abs_window_x, abs_window_y, relative_x, relative_y):
        """
        双击指定位置。用于双击左侧导航栏的聊天图标以自动滚动未读消息。
        P1 阶段增强：添加用户干预检测，防止误操作
        """
        target_x = int(abs_window_x + relative_x)
        target_y = int(abs_window_y + relative_y)

        logging.info(f"✌️ 物理执行层：鼠标指针正瞬移至 [{target_x}, {target_y}] 进行双击...")

        # P1 阶段增强：在移动鼠标前先等待一小段时间，确保鼠标静止
        try:
            # 记录当前位置作为基准，然后等待一小段时间
            self._record_mouse_position()
            time.sleep(0.2)  # 等待 200ms，确保鼠标静止

            # 再次检查是否有用户干预
            if self._check_mouse_hijack():
                logging.warning("🚨 安全防线：双击前检测到用户干预，等待用户操作完成...")
                self._wait_for_user_idle(check_interval=1.0, retry_interval=5.0)
                logging.info("✅ 安全防线：用户操作已完成，继续双击...")
        except KeyboardInterrupt:
            logging.warning("⚠️ 用户中断操作，取消双击...")
            return
        except RuntimeError as e:
            if str(e) == "EngineStopped": return
        except Exception as e:
            logging.warning(f"⚠️ 安全防线：双击前检查失败，继续执行 - {e}")

        # 现在移动鼠标
        self.mouse.position = (target_x, target_y)
        time.sleep(0.15)

        # P1 阶段增强：双击动作前再次检查
        # 注意：这里需要重新记录基准位置为移动后的位置
        self._record_mouse_position()
        time.sleep(0.1)  # 等待一小段时间

        try:
            if self._check_mouse_hijack():
                logging.warning("🚨 安全防线：双击动作前检测到用户干预，取消本次双击...")
                return
        except Exception as e:
            logging.warning(f"⚠️ 安全防线：双击前检查失败，继续执行 - {e}")

        self.mouse.click(Button.left, 2)
        
    def send_message(self, text: str, auto_send: bool = True):
        """
        向当前「已处于聚焦状态」的微信输入框拟人化地输出回答。
        升级链路设计：逐字流式粘贴（带防线校验）-> Enter 回车
        拟人流式输出特点：
        - 逐字粘贴模拟人类打字节奏
        - 实时防线校验（鼠标抢夺检测、焦点窗口验证）
        - 随机延迟模拟打字速度变化
        - 偶发手误模拟增加真实性

        :param text: 要发送的消息文本
        :param auto_send: 是否自动发送，True 为自动发送，False 为只粘贴不发送（辅助模式）
        """
        if not text:
            return

        mode_desc = "自动发送" if auto_send else "辅助模式（仅粘贴）"
        logging.info(f"[物理执行层] 接到任务！准备进行拟人流式输出 [{mode_desc}]...")

        # P1 阶段新增：重新记录鼠标位置作为基准（避免之前 click_target 的移动被误判）
        self._record_mouse_position()

        # 留白时间 0.3 秒，模拟人类目光正在从聊天记录往下看输入框的眼动空隙
        time.sleep(0.3)

        # P1 阶段新增：执行前安全检查 - 检测用户是否在抢夺鼠标
        # （这里只检测用户干预，程序自身的移动会在 click_target 后重置基准）
        try:
            if self._check_mouse_hijack():
                logging.warning("🚨 安全防线：检测到用户干预，等待用户操作完成...")
                self._wait_for_user_idle(check_interval=1.0, retry_interval=5.0)
                logging.info("✅ 安全防线：用户操作已完成，继续发送...")
        except KeyboardInterrupt:
            logging.warning("⚠️ 用户中断操作，取消发送...")
            return
        except RuntimeError as e:
            if str(e) == "EngineStopped": return
        except Exception as e:
            logging.warning(f"⚠️ 安全防线：鼠标抢夺检查失败，继续执行 - {e}")

        # P1 阶段新增：执行前安全检查 - 验证焦点窗口
        if not self._verify_foreground_window():
            logging.error("🚨 安全防线：焦点已丢失，中断流式输出操作！")
            return

        # 核心升级：使用拟人流式输出替代一次性粘贴
        stream_success = self._stream_type_text(text)
        if not stream_success:
            logging.error("❌ 拟人流式输出失败或中断，取消发送操作")
            return

        # 如果是辅助模式，只粘贴不发送
        if not auto_send:
            logging.info(f"[物理执行层] 辅助模式 - 内容已流式输出到输入框，等待用户手动发送。字数统计：{len(text)}")
            return

        # 留白时间 0.4 秒，模拟人类打完字大脑核对内容有没有病句的短暂停顿（强行防风控）
        time.sleep(0.4)

        # P1 阶段新增：发送前最后安全检查 - 验证焦点和鼠标
        try:
            if self._check_mouse_hijack():
                logging.warning("🚨 安全防线：发送前检测到用户干预，等待用户操作完成...")
                self._wait_for_user_idle(check_interval=1.0, retry_interval=5.0)
                logging.info("✅ 安全防线：用户操作已完成，继续发送...")
        except KeyboardInterrupt:
            logging.warning("⚠️ 用户中断操作，取消发送...")
            return
        except RuntimeError as e:
            if str(e) == "EngineStopped": return
        except Exception as e:
            logging.warning(f"⚠️ 安全防线：鼠标抢夺检查失败，继续执行 - {e}")

        if not self._verify_foreground_window():
            logging.error("🚨 安全防线：焦点已丢失，中断 Enter 发送操作！")
            return

        # 3. 敲下回车键，让这一切物理发生！
        try:
            self.keyboard.press(Key.enter)
            self.keyboard.release(Key.enter)
        except Exception as e:
            logging.error(f"❌ 回车键操作失败: {e}")
            return

        logging.info(f"[物理执行层] 拟人流式输出 + Enter 发送已完成！字数统计：{len(text)}")

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
