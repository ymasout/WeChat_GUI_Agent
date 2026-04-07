import time
import logging
import sys
import os
import hashlib
import json

# 压制 PaddleOCR 的 WARNING 日志
logging.getLogger('ppocr').setLevel(logging.ERROR)
logging.getLogger('paddle').setLevel(logging.ERROR)
os.environ['GLOG_minloglevel'] = '2'

from .window_manager import WindowManager
from .vision import VisionEngine
from .ocr_parser import OCRParser
from .agent import AgentBrain
from .action import ActionExecutor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] %(message)s')

import queue

log_queue = queue.Queue()

def log(msg):
    """用 print 强制输出日志，不被第三方库吞没，同时输送到界面队列"""
    from datetime import datetime
    ts = datetime.now().strftime('%H:%M:%S')
    log_line = f"[{ts}] {msg}"
    print(log_line, flush=True)
    log_queue.put(log_line)

class WeChatEngine:
    def __init__(self, config_path="data/config.yaml"):
        self.config_path = config_path
        self.wm = WindowManager()
        self.vision = VisionEngine(config_path=self.config_path)
        self.parser = OCRParser(confidence_threshold=0.7)
        self.brain = AgentBrain(config_path=self.config_path)
        self.action = ActionExecutor()
        self.is_running = False

        # P1 阶段新增：防鞭尸机制 - 存储每个联系人的最后回复消息哈希
        self.last_replied_hash = {}  # 格式: {contact_name: hash_value}
        self._hash_cache_file_path = "data/reply_hash_cache.json"  # 使用简单字符串，避免 Path 初始化问题
        self._hash_cache_loaded = False  # 标记缓存是否已加载（延迟加载）

        # 读取工作模式配置
        import yaml
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                self.work_mode = config.get('work_mode', 'auto')  # 默认自动模式
                log(f"[工作模式] {'自动' if self.work_mode == 'auto' else '辅助'}")
        except Exception as e:
            log(f"[警告] 读取工作模式配置失败，使用默认自动模式: {e}")
            self.work_mode = 'auto'

    def stop(self):
        """通知引擎准备挂起（在本次循环结束后停止）"""
        self.is_running = False
        log("🔴 引擎收到暂停指令，当前巡逻周期结束后将待机...")
        # P1 阶段新增：停止时保存哈希缓存
        self._save_hash_cache()

    def _calculate_messages_hash(self, messages: list) -> str:
        """
        P1 阶段新增：计算消息列表的哈希值，用于检测重复触发
        :param messages: 消息列表
        :return: MD5 哈希字符串
        """
        try:
            # 将消息转换为统一的字符串格式
            content = "|".join([f"{m['sender']}:{m['text']}" for m in messages])
            # 计算 MD5 哈希
            return hashlib.md5(content.encode('utf-8')).hexdigest()
        except Exception as e:
            logging.error(f"❌ 安全防线：计算消息哈希失败 - {e}")
            return ""

    def _check_duplicate_reply(self, contact_name: str, messages: list) -> bool:
        """
        P1 阶段新增：检查是否为重复触发（防鞭尸机制）
        :param contact_name: 联系人名字
        :param messages: 当前消息列表
        :return: True 表示重复，应跳过；False 表示新消息，应回复
        """
        try:
            if not contact_name or not messages:
                return False

            # 延迟加载哈希缓存（首次使用时才加载）
            if not self._hash_cache_loaded:
                self._load_hash_cache()

            # 计算当前消息哈希
            current_hash = self._calculate_messages_hash(messages)
            if not current_hash:
                return False  # 计算失败时不阻止

            # 获取该联系人的上次回复哈希
            last_hash = self.last_replied_hash.get(contact_name)

            if last_hash == current_hash:
                logging.warning(f"🚨 安全防线：检测到重复触发（防鞭尸），跳过对「{contact_name}」的回复")
                logging.warning(f"   哈希值: {current_hash[:8]}...")
                return True

            return False

        except Exception as e:
            logging.error(f"❌ 安全防线：重复检测失败 - {e}")
            return False  # 出错时不阻止

    def _record_reply_hash(self, contact_name: str, messages: list):
        """
        P1 阶段新增：记录已回复的消息哈希
        :param contact_name: 联系人名字
        :param messages: 消息列表
        """
        try:
            if not contact_name or not messages:
                return

            current_hash = self._calculate_messages_hash(messages)
            if current_hash:
                self.last_replied_hash[contact_name] = current_hash
                logging.debug(f"💾 安全防线：已记录「{contact_name}」的回复哈希: {current_hash[:8]}...")

        except Exception as e:
            logging.error(f"❌ 安全防线：记录哈希失败 - {e}")

    def _load_hash_cache(self):
        """P1 阶段新增：从文件加载哈希缓存（延迟加载，避免初始化时递归）"""
        try:
            # 避免重复加载
            if self._hash_cache_loaded:
                return

            # 使用简单的字符串路径，完全避免 Path 对象
            cache_file_path = self._hash_cache_file_path

            # 检查文件是否存在
            try:
                if os.path.exists(cache_file_path):
                    with open(cache_file_path, 'r', encoding='utf-8') as f:
                        self.last_replied_hash = json.load(f)
                    log(f"💾 安全防线：已加载哈希缓存，包含 {len(self.last_replied_hash)} 个联系人记录")
                else:
                    log("💾 安全防线：哈希缓存文件不存在，将创建新缓存")
            except Exception as file_error:
                logging.debug(f"缓存文件检查失败: {file_error}")

            self._hash_cache_loaded = True

        except Exception as e:
            logging.error(f"❌ 安全防线：加载哈希缓存失败 - {e}")
            self.last_replied_hash = {}
            self._hash_cache_loaded = True  # 即使失败也标记为已加载，避免重复尝试

    def _save_hash_cache(self):
        """P1 阶段新增：保存哈希缓存到文件"""
        try:
            # 使用简单的字符串路径，完全避免 Path 对象
            cache_file_path = self._hash_cache_file_path

            # 提取目录部分并确保存在
            cache_dir = os.path.dirname(cache_file_path)
            if cache_dir and not os.path.exists(cache_dir):
                os.makedirs(cache_dir, exist_ok=True)

            # 写入文件
            with open(cache_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.last_replied_hash, f, ensure_ascii=False, indent=2)

            log(f"💾 安全防线：已保存哈希缓存，包含 {len(self.last_replied_hash)} 个联系人记录")
        except Exception as e:
            # 避免在异常处理中触发递归
            try:
                logging.error(f"❌ 安全防线：保存哈希缓存失败 - {str(e)}")
            except Exception:
                pass  # 如果连日志都失败了，就静默处理

    def _interruptible_sleep(self, seconds):
        """可被 stop() 中断的休眠：每秒检查一次 is_running"""
        for _ in range(int(seconds)):
            if not self.is_running:
                return
            time.sleep(1)
        
    def start(self):
        print("""
        ========================================================
         微信纯视觉 AI 自动回复助手 (V3核心引擎)
        ========================================================
        [运行须知]
        - 请保持微信窗口可见（不要遮挡或最小化）
        - 程序每 60 秒扫描一次红点
        - 回复后蹲守 15 秒，超时后自动关闭聊天窗口
        - 按 Ctrl+C 随时安全退出
        """)

        session_rect = self.vision.config["window"].get("session_list_rect")
        nav_icon_rect = self.vision.config["window"].get("nav_chat_icon_rect")
        chat_rect = self.vision.config["window"].get("chat_content_rect")
        title_rect = self.vision.config["window"].get("chat_title_rect")

        if not session_rect or not chat_rect or session_rect == [0, 0, 0, 0]:
            log("致命错误：坐标未校准！请先运行 python vision.py 进行画框校准。")
            sys.exit(1)

        log("✅ 所有组件加载完毕，进入主巡逻循环...")

        SCAN_INTERVAL = 60      # 巡逻间隔（秒）
        FOLLOW_UP_TIMEOUT = 15  # 蹲守超时（秒）
        FOLLOW_UP_INTERVAL = 3  # 蹲守内每次 OCR 间隔（秒）
        scan_count = 0
        self.is_running = True

        try:
            while self.is_running:
                # 1. 强制唤醒微信到最前方
                if not self.wm.activate_window():
                    log("⚠️ 微信窗口未找到，60 秒后重试...")
                    self._interruptible_sleep(SCAN_INTERVAL)
                    continue

                time.sleep(0.3)
                abs_rect = self.wm.get_window_rect()

                # 2. 扫描红点
                session_img = self.vision.capture_region(abs_rect, session_rect)
                red_dots = self.vision.detect_unread_red_dots(session_img)
            
                scan_count += 1

                if not red_dots:
                    # 列表区域没看到红点，检查左侧导航栏图标是否有提示
                    if nav_icon_rect:
                        nav_img = self.vision.capture_region(abs_rect, nav_icon_rect)
                        nav_red_dots = self.vision.detect_unread_red_dots(nav_img)
                        if nav_red_dots:
                            log("👀 发现侧边栏聊天图标有未读信息（隐藏在下方），执行双击滚动...")
                            nav_cx, nav_cy = nav_red_dots[0]
                            nav_click_x = nav_icon_rect[0] + nav_cx
                            nav_click_y = nav_icon_rect[1] + nav_cy
                            self.action.double_click_target(abs_rect['left'], abs_rect['top'], nav_click_x, nav_click_y)
                            time.sleep(1) # 等待列表自动滚动完成
                            continue # 直接重新跑一次外循环扫描！

                    log("🟢 无未读信息。最小化微信，60 秒后再来。")
                    self.wm.minimize_window()
                    self._interruptible_sleep(SCAN_INTERVAL)
                    continue

                # 3. 发现红点！记住点击坐标（后面关闭聊天要用）
                log(f"🎯 发现 {len(red_dots)} 个未读信息！")
                target_cx, target_cy = red_dots[0]
                click_rel_x = session_rect[0] + target_cx
                click_rel_y = session_rect[1] + target_cy

                # 单击打开聊天
                self.wm.activate_window()
                time.sleep(0.3)
                self.action.click_target(abs_rect['left'], abs_rect['top'], click_rel_x, click_rel_y)
                time.sleep(1.2)

                # 3.5 识别当前聊天的联系人名字（用于后续关闭聊天窗口）
                current_contact = None
                if title_rect:
                    abs_rect = self.wm.get_window_rect()
                    title_img = self.vision.capture_region(abs_rect, title_rect)
                    current_contact = self.parser.read_contact_name(title_img)
                    if current_contact:
                        log(f"👤 识别到当前联系人：「{current_contact}」")
                    else:
                        log("⚠️ 未能识别联系人名字，关闭聊天时将使用原始坐标。")

                # 4. 进入跟踪模式：截图 → 识别 → 回复 → 全量缓存 → 蹲守
                log("🔁 进入跟踪模式，蹲守 %d 秒..." % FOLLOW_UP_TIMEOUT)
                follow_up_start = time.time()
                assist_mode_triggered = False

                # 第一次扫描聊天内容
                abs_rect = self.wm.get_window_rect()
                if abs_rect:
                    chat_img = self.vision.capture_region(abs_rect, chat_rect)
                    new_msgs = self.parser.parse_chat_image(chat_img)

                    # 过滤出对方发来的消息
                    their_msgs = [m for m in new_msgs if m['sender'] == 'them']

                    if their_msgs:
                        # P1 阶段新增：防鞭尸检查 - 检测是否重复触发
                        if self._check_duplicate_reply(current_contact, new_msgs):
                            log("🔄 检测到重复消息，跳过本次回复，等待新消息...")
                            time.sleep(3)
                            continue

                        # P1 阶段增强：LLM 生成回复前的安全检查（检测用户是否在等待期间干预）
                        try:
                            if self.action._check_mouse_hijack():
                                log("🚨 安全防线：检测到用户干预，等待用户操作完成...")
                                self.action._wait_for_user_idle(check_interval=1.0, retry_interval=5.0)
                                log("✅ 安全防线：用户操作已完成，继续生成回复...")
                        except KeyboardInterrupt:
                            log("⚠️ 用户中断操作，跳过本次回复...")
                            time.sleep(3)
                            continue
                        except Exception as e:
                            log(f"⚠️ 安全防线：LLM 前检查失败，继续执行 - {e}")

                        log("🧠 连线大模型...")
                        reply_text = self.brain.think_and_reply(new_msgs, current_contact)

                        if reply_text and "..." not in reply_text[:3]:
                            log(f"🗣️ 回复：「{reply_text}」")
                            # 根据工作模式决定是否自动发送
                            auto_send = (self.work_mode == 'auto')
                            self.action.send_message(reply_text, auto_send=auto_send)

                            # P1 阶段新增：记录已回复的消息哈希
                            self._record_reply_hash(current_contact, new_msgs)

                            if auto_send:
                                log("✅ 已发送，冷却 3 秒...")
                                time.sleep(3)
                            else:
                                log("✨ 辅助模式：草稿已备好，等待您检阅补充并手动发送...")
                                assist_mode_triggered = True

                            # 【关键】立刻全量截图，把屏幕上所有内容（包括对方的回复）全部缓存为"已读"
                            abs_rect_refresh = self.wm.get_window_rect()
                            if abs_rect_refresh:
                                digest_img = self.vision.capture_region(abs_rect_refresh, chat_rect)
                                self.parser.parse_chat_image(digest_img)
                                log("🔄 全量缓存完毕，屏幕已标记为已读。")

                            if assist_mode_triggered:
                                log("⏳ 辅助模式将为您预留 15 秒检查时间，随后自动关闭当前聊天框。")
                                self._interruptible_sleep(15)
                                # 此处原有的 continue 已移除，允许程序顺流而下自动执行第 5 步关闭操作

                            follow_up_start = time.time()
                        else:
                            log("🧠 大模型判断无需回复。")
                    else:
                        log("⚠️ 空包弹：未提取到对方的新消息。")

                # 蹲守循环：每 3 秒扫一次，发现新消息就回复，否则超时退出
                while not assist_mode_triggered:
                    if not self.is_running:
                        break

                    elapsed = time.time() - follow_up_start
                    if elapsed > FOLLOW_UP_TIMEOUT:
                        log(f"⏰ 蹲守超时（{int(elapsed)} 秒），准备关闭聊天窗口。")
                        break

                    remaining = max(0, int(FOLLOW_UP_TIMEOUT - elapsed))
                    log(f"👀 蹲守中... 剩余 {remaining} 秒")
                    time.sleep(FOLLOW_UP_INTERVAL)

                    abs_rect = self.wm.get_window_rect()
                    if not abs_rect:
                        break

                    chat_img = self.vision.capture_region(abs_rect, chat_rect)
                    new_msgs = self.parser.parse_chat_image(chat_img)

                    # 只关心对方发来的新消息
                    their_msgs = [m for m in new_msgs if m['sender'] == 'them']
                    if not their_msgs:
                        continue

                    # P1 阶段新增：蹲守模式下的防鞭尸检查
                    if self._check_duplicate_reply(current_contact, new_msgs):
                        log("🔄 蹲守模式：检测到重复消息，跳过本次回复...")
                        time.sleep(FOLLOW_UP_INTERVAL)
                        continue

                    # P1 阶段增强：蹲守模式下 LLM 生成回复前的安全检查
                    try:
                        if self.action._check_mouse_hijack():
                            log("🚨 安全防线：蹲守模式检测到用户干预，等待用户操作完成...")
                            self.action._wait_for_user_idle(check_interval=1.0, retry_interval=5.0)
                            log("✅ 安全防线：用户操作已完成，继续生成回复...")
                    except KeyboardInterrupt:
                        log("⚠️ 用户中断操作，跳过本次回复...")
                        time.sleep(FOLLOW_UP_INTERVAL)
                        continue
                    except Exception as e:
                        log(f"⚠️ 安全防线：蹲守模式检查失败，继续执行 - {e}")

                    log("🧠 检测到新回复，连线大模型...")
                    reply_text = self.brain.think_and_reply(new_msgs, current_contact)

                    if reply_text and "..." not in reply_text[:3]:
                        log(f"🗣️ 回复：「{reply_text}」")
                        # 根据工作模式决定是否自动发送
                        auto_send = (self.work_mode == 'auto')
                        self.action.send_message(reply_text, auto_send=auto_send)

                        # P1 阶段新增：记录已回复的消息哈希
                        self._record_reply_hash(current_contact, new_msgs)

                        if auto_send:
                            log("✅ 已发送，冷却 3 秒...")
                            time.sleep(3)
                        else:
                            log("✨ 辅助模式：草稿已备好，等待您检阅补充并手动发送...")
                            assist_mode_triggered = True

                        # 再次全量缓存
                        abs_rect_refresh = self.wm.get_window_rect()
                        if abs_rect_refresh:
                            digest_img = self.vision.capture_region(abs_rect_refresh, chat_rect)
                            self.parser.parse_chat_image(digest_img)
                            log("🔄 全量缓存完毕，屏幕已标记为已读。")

                        if assist_mode_triggered:
                            log("⏳ 辅助模式将为您预留 15 秒检查时间，随后自动关闭当前聊天框。")
                            self._interruptible_sleep(15)
                            break # 跳出蹲守，进入下方的关闭聊天操作

                        follow_up_start = time.time()


                # 5. 蹲守结束，在会话列表中找到该联系人并点击关闭聊天
                # （辅助模式现在也将执行关闭聊天，以防随后扫描红点时因未失焦而误关闭）

                abs_rect = self.wm.get_window_rect()
                if abs_rect and current_contact:
                    log(f"🔍 正在会话列表中搜索「{current_contact}」的位置...")
                    session_img = self.vision.capture_region(abs_rect, session_rect)
                    list_items = self.parser.find_contact_in_list(session_img)
                
                    # 模糊匹配：联系人在列表中名字太长可能会被截断并加上 "..." 
                    found = False
                    # 去除省略号进行匹配
                    clean_target = current_contact.replace('...', '').replace('…', '').strip()
                    for text, cx, cy in list_items:
                        clean_text = text.replace('...', '').replace('…', '').strip()
                        
                        # 只要有交集（列表文本在目标内，或目标在列表文本内），或者前置几个字符一样（应对极致截断）
                        if (clean_text and clean_text in clean_target) or \
                           (clean_target and clean_target in clean_text) or \
                           (len(clean_target) >= 3 and clean_text.startswith(clean_target[:3])):
                            close_x = session_rect[0] + cx
                            close_y = session_rect[1] + cy
                            log(f"✅ 找到「{current_contact}」在列表中的位置，点击关闭聊天...")
                            self.action.click_target(abs_rect['left'], abs_rect['top'], close_x, close_y)
                            found = True
                            break
                
                    if not found:
                        log(f"⚠️ 未在列表中找到「{current_contact}」，保底最小化微信。")
                        self.wm.minimize_window()
                elif abs_rect:
                    log("⚠️ 未识别到联系人名字，保底最小化微信。")
                    self.wm.minimize_window()
            
                time.sleep(0.5)
                log("✅ 聊天窗口已关闭，恢复未读信息扫描。")

        except KeyboardInterrupt:
            print("\n\n👋 安全退出。")
            sys.exit(0)

    # 去除 __main__ 块，交由根目录 main.py 调用
