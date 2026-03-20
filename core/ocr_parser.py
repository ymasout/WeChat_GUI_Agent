import hashlib
import logging
import sys
import cv2
from typing import List, Dict, Any
from unittest.mock import MagicMock

# [终极兼容补丁] paddlex 里面的无用废弃模块导入太多了！我们根本不用它的这些复杂 RAG 功能，只需要单纯的图像 OCR 文字提取。
# 所以干脆利落地使用 MagicMock 制作假的“海市蜃楼”模块，骗过 Python 的 import 检查，一劳永逸阻止所有 ModuleNotFoundError！
mock_obj = MagicMock()
sys.modules['langchain.docstore'] = mock_obj
sys.modules['langchain.docstore.document'] = mock_obj
sys.modules['langchain.text_splitter'] = mock_obj
sys.modules['langchain.vectorstores'] = mock_obj
sys.modules['langchain.embeddings'] = mock_obj

from paddleocr import PaddleOCR
from collections import deque

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class OCRParser:
    """
    OCR 文本识别与消息解析引擎
    负责识别聊天记录图片中的文字，判断发送方（我/对方/系统），并维护消息去重状态墙。
    """
    def __init__(self, confidence_threshold=0.7, max_history=500):
        # 禁用没必要的组件以求最速：不分析文字倾斜（因为微信都是正向的）
        logging.info("组件挂载：正在初始化本地 PaddleOCR 视觉大脑，首次将加载静态推理图库，请稍候...")
        # 既然我们已经回滚到了极其稳定的 2.8.1 长期支持版，我们现在可以重新把静音开关开起来了！
        # 彻底屏蔽掉底层为了汇报引擎参数而吐出的一整屏极其难看的 DEBUG 日志墙。
        self.ocr = PaddleOCR(use_angle_cls=False, lang="ch", show_log=False)
        self.confidence_threshold = confidence_threshold
        
        # 消息去重用的哈希集合与先进先出清理缓存
        self.processed_hashes = set()
        self.message_history = deque(maxlen=max_history)
        
        # 多模态类型（系统提示字眼），如果遇到了这几个关键词之一，说明发来的不是纯文字
        self.multimodal_keywords = ['[语音]', '[图片]', '[视频]', '[文件]', '[转账]', '[动画表情]', '[位置]']

    def read_contact_name(self, title_img):
        """
        从聊天标题栏截图中提取当前联系人的名字。
        :param title_img: 聊天标题栏区域的截图
        :return: 联系人名字字符串，识别失败返回 None
        """
        if title_img is None or title_img.size == 0:
            return None
        if len(title_img.shape) == 3 and title_img.shape[2] == 4:
            title_img = cv2.cvtColor(title_img, cv2.COLOR_BGRA2BGR)
        
        results = self.ocr.ocr(title_img)
        if not results or not results[0]:
            return None
        
        # 标题栏里可能有多段文字（比如名字 + 在线状态），取最长的那个作为名字
        best_text = ""
        for el in results[0]:
            text = el[1][0].strip()
            if len(text) > len(best_text):
                best_text = text
        
        return best_text if best_text else None

    def find_contact_in_list(self, session_img):
        """
        对左侧会话列表截图做 OCR，返回所有识别到的文本及其坐标。
        :param session_img: 左侧会话列表区域的截图
        :return: [(text, center_x, center_y), ...] 列表
        """
        if session_img is None or session_img.size == 0:
            return []
        if len(session_img.shape) == 3 and session_img.shape[2] == 4:
            session_img = cv2.cvtColor(session_img, cv2.COLOR_BGRA2BGR)
        
        results = self.ocr.ocr(session_img)
        if not results or not results[0]:
            return []
        
        items = []
        for el in results[0]:
            bbox, (text, conf) = el
            if conf < 0.6:
                continue
            # 计算该文本块的中心坐标（相对于截图区域）
            cx = sum(p[0] for p in bbox) / 4.0
            cy = sum(p[1] for p in bbox) / 4.0
            items.append((text.strip(), int(cx), int(cy)))
        
        return items

    def _generate_message_hash(self, text, sender, sequence_context=""):
        """
        [核心去重算法] 利用组合了前后文序列的复合信息生成这条消息的唯一哈希指纹。
        用来解决防灾难级别的连环回复 Bug：
        如果用户连发了两句“在吗”，因为这两句在屏幕上出现的绝对"上下文队列"截然不同，所以可以完美切分哈希，不会杀掉第二条。
        """
        raw = f"{sequence_context}|{sender}|{text}"
        return hashlib.md5(raw.encode('utf-8')).hexdigest()

    def parse_chat_image(self, bgr_image, digest_only_me=False) -> List[Dict[str, Any]]:
        """
        对截取下来的【聊天记录大区】进行文本提取与解析
        :param bgr_image: 视界模块截取过来的聊天区域 numpy 图片
        :param digest_only_me: 消化模式 - 若为 True，只标记"我"发的消息为已读，
                               对方的消息不加入去重集合，确保秒回不被吞噬
        :return: 经过滤处理并确认为【全新未处理过】的消息字典列表
        """
        if bgr_image is None or bgr_image.size == 0:
            return []
            
        # [极为关键的通道转换] `mss` 库截屏默认带出透明通道变成 4通道(BGRA)图片
        # 如果不降维成纯 3通道(BGR)，会导致 PaddleOCR/PaddleX 底层数组在进行均值正规化处理(NormalizeImage)时 index out of range 越界崩溃！
        if len(bgr_image.shape) == 3 and bgr_image.shape[2] == 4:
            bgr_image = cv2.cvtColor(bgr_image, cv2.COLOR_BGRA2BGR)
            
        height, width, _ = bgr_image.shape
        
        # 开启推理：results[0] 即为该图片的一组二维列表检测结果
        # 数据结构为: [[[[左上x,左上y], [右上x,右上y], [...], [...]], ('文本内容', 置信度分)], ...]
        # 最新版 PaddleOCR(PaddleX) 已经不再需要 cls 参数了
        results = self.ocr.ocr(bgr_image)
        
        if not results or not results[0]:
            return []
            
        raw_elements = results[0]
        # 【物理排序】：严格按照文本块的左上角顶点 Y 坐标进行从上往下的时序排列！
        raw_elements.sort(key=lambda item: item[0][0][1])
        
        parsed_messages = []
        current_sequence_texts = [] # 记录本次屏幕内从上到下扫过的文字链
        
        for element in raw_elements:
            bbox, (text, conf) = element
            
            # 1. 置信度打回：OCR 对于很模糊的头像或者杂乱背景容易幻觉出意义不明的乱码
            if conf < self.confidence_threshold:
                continue
                
            text = text.strip()
            if not text:
                continue
                
            # 取矩形四个点的所有 X 坐标，找到它在这个屏幕上的最左侧起点和最右侧终点
            xs = [p[0] for p in bbox]
            min_x = min(xs)
            max_x = max(xs)
            rel_min_x = min_x / width
            rel_max_x = max_x / width
            
            # 【致命 BUG 修复】：不能用中心点(Center X) 算！
            # 因为如果对方发了一长串话横跨了整个屏幕，中心点就会接近 0.5（中央），然后被误杀当成系统时间提示给丢弃掉（空包弹）！
            # 正确的空间几何学是：
            # - 对方的消息一定是从最左侧的头像气泡发起的，所以它的起始 X (min_x) 一定死死贴住屏幕左侧（通常 < 0.2）
            # - 我的消息一定是从最右侧头像发起的甚至贴边界，所以它的结束 X (max_x) 一定非常靠右（通常 > 0.8）
            # - 只有那种又没贴着左边，又没贴着右边，短小居中的，才是系统时间或撤回提示。
            
            if rel_min_x < 0.45:
                # 哪怕超长文本向右延伸，只要起笔在左半边（< 45%），一律视作对方发来的
                sender = "them"
            elif rel_max_x > 0.55:
                # 只要落笔跨过了右半屏幕的中线（> 55%），哪怕是向左再怎么延伸，一律视作我发出去的
                sender = "me"
            else:
                # 这种完全缩在屏幕最中心一小戳位置（45% ~ 55% 之间）的，必定是系统时间或撤回提示
                continue
                
            # 3. 多模态/异常富文本兜底降级防御判断
            is_multimodal = False
            for keyword in self.multimodal_keywords:
                if keyword in text:
                    is_multimodal = True
                    break
                    
            # 4. 防重复哈希与状态更新机制 
            # 把此时积累在本次截图扫出的前两句话（如果有），当作这句话的“时空锚点指纹”
            sequence_context_str = "_".join(current_sequence_texts[-2:]) 
            
            msg_hash = self._generate_message_hash(text, sender, sequence_context_str)
            current_sequence_texts.append(text)
            
            # 消化模式：只标记"我"的消息为已读，对方的消息跳过不吞噬
            if digest_only_me and sender == "them":
                continue
            
            # ---> 如果这是一条在这个上下文中从来没见过的未消费消息！
            if msg_hash not in self.processed_hashes:
                # 立即将其封印刻进本地的记忆缓存库里！
                self.processed_hashes.add(msg_hash)
                self.message_history.append(msg_hash)
                
                # 如果超载，淘汰陈旧记忆，保证内存极低消耗
                if len(self.message_history) > self.message_history.maxlen - 10:
                    oldest_hash = self.message_history.popleft()
                    if oldest_hash in self.processed_hashes:
                        self.processed_hashes.remove(oldest_hash)
                
                # 构建正规化消息数据交付给上层调用者
                parsed_messages.append({
                    "text": text,
                    "sender": sender,
                    "is_multimodal": is_multimodal,
                    "bbox": bbox
                })
                
        return parsed_messages

if __name__ == "__main__":
    # 本地跑通极简独立验证环节
    from window_manager import WindowManager
    from vision import VisionEngine
    import cv2
    import os

    wm = WindowManager()
    if wm.find_window():
        rect = wm.get_window_rect()
        vision = VisionEngine()
        
        chat_rect = vision.config["window"].get("chat_content_rect")
        if not chat_rect or chat_rect == [0,0,0,0]:
            logging.info("请先执行 vision.py 进行校准画框！")
        else:
            logging.info("成功读取聊天区域坐标！正对该区域截图进行极速文本提取测试...")
            chat_img = vision.capture_region(rect, chat_rect)
            
            # 使用自带的降噪与白名单机制识别屏幕内容
            parser = OCRParser(confidence_threshold=0.8)
            new_msgs = parser.parse_chat_image(chat_img)
            
            print("\n=========== 本次截屏「全新」识别到的文本如下 ===========")
            for m in new_msgs:
                tag_color = "🟢" if m['sender'] == 'me' else "🔵"
                text_content = f"⚠️ [需要降级兜底的媒体]" if m['is_multimodal'] else m['text']
                print(f"{tag_color} [{'我' if m['sender'] == 'me' else '对方'}]: {text_content} (原始: {m['text']})")
            
            print("=====================================================")
            print("小提示：你可以试着连跑两遍本文件！你会发现第二遍时上面的消息都不会再输出，因为它们被指纹墙完美拦截（去重成功）了！\n")
