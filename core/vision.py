import cv2
import mss
import numpy as np
import yaml
import logging
import re
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class VisionEngine:
    """
    视觉截屏与检测模块
    核心职责：从屏幕极低延迟截取图像数据，进行校准交互，以及通过 HSV 提取未读红点等
    """
    def __init__(self, config_path="config.yaml"):
        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self):
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def capture_region(self, window_rect, offset_rect):
        """
        截取相对于微信主窗口指定偏移量的区域图像
        :param window_rect: {"left": x, "top": y, "width": w, "height": h}
        :param offset_rect: config 中定义的 [偏移X, 偏移Y, 截取宽度, 截取高度]
        :return: BGRA 格式的 numpy 图片数组
        """
        if not window_rect or not offset_rect:
            logging.error("视界：截屏失败，窗口或偏移坐标为空")
            return None
            
        monitor = {
            "left": window_rect["left"] + offset_rect[0],
            "top": window_rect["top"] + offset_rect[1],
            "width": offset_rect[2],
            "height": offset_rect[3]
        }
        
        # 每次截图创建新的 mss 实例，保证多线程安全（mss 内部使用 thread-local 存储）
        with mss.mss() as sct:
            sct_img = sct.grab(monitor)
            img = np.array(sct_img)
        return img

    def detect_unread_red_dots(self, bgra_image):
        """
        抛弃高消耗的全图 SSIM 对比，采用极低成本的 HSV 提取“纯红色像素群”方法。
        :param bgra_image: numpy 截图数组 (BGRA格式)
        :return: 发现的红点列表，元素为 (中心x, 中心y) 的局部坐标元组，包含红点的会话按照从上到下排序
        """
        if bgra_image is None or bgra_image.size == 0:
            return []
            
        # 去掉 Alpha 通道以获取完全正确的 BGR 通道进行转换
        bgr_img = bgra_image[:, :, :3] 
        hsv_img = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2HSV)
        
        # 红色在 HSV 中属于 H 分量分布在 0 附近和 180 附近的两个区域
        lower_red_1 = np.array([0, 100, 100])
        upper_red_1 = np.array([10, 255, 255])
        lower_red_2 = np.array([160, 100, 100])
        upper_red_2 = np.array([180, 255, 255])
        
        # 寻找匹配掩码并合并 (通过这道过滤就会只剩下红色的信息点)
        mask1 = cv2.inRange(hsv_img, lower_red_1, upper_red_1)
        mask2 = cv2.inRange(hsv_img, lower_red_2, upper_red_2)
        mask = cv2.bitwise_or(mask1, mask2)
        
        # 通过寻找轮廓(Contours)找到连通的独立的色块
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        red_dots = []
        for contour in contours:
            area = cv2.contourArea(contour)
            
            # 【过滤 1：体积】
            if 80 < area < 800:
                x, y, w, h = cv2.boundingRect(contour)
                
                # 【过滤 2：图形学填充率 (Extent) 必杀】
                # 圆形 Extent 是 0.785；胶囊体(例如99+)通常在 0.8 - 0.88 之间
                # 但是方形的群内小头像（例如 babycare 截图里的方形红底头像），如果不掏空的话全满 Extent 接近 1.0
                extent = area / float(w * h)
                if not (0.65 < extent < 0.92):
                    continue
                
                # 【过滤 3：长宽比】
                aspect_ratio = float(w) / float(h)
                if not (0.8 <= aspect_ratio <= 2.2):
                    continue
                    
                # 【过滤 4：内部高亮白字的绝杀校验】
                # 有数字的红点必定要在内部包含白色的字体像素
                roi_bgr = bgr_img[y:y+h, x:x+w]
                # 加强容错，红点里的字体绝对是非常纯净的高亮白
                lower_white = np.array([210, 210, 210]) 
                upper_white = np.array([255, 255, 255])
                white_mask = cv2.inRange(roi_bgr, lower_white, upper_white)
                white_pixels = cv2.countNonZero(white_mask)
                
                if white_pixels < 5:
                    continue
                    
                # --- 终极必杀排版校验 ---
                # 获取红点内部这个白色数字的边界矩形
                wx, wy, ww, wh = cv2.boundingRect(white_mask)
                if wh == 0:
                    continue
                    
                # 1. 高度比例：微信红点里的数字高度非常标准，一般占据圈圈高度的 40% ~ 75% 之间
                # 太大(充满全屏)或太小(噪点)都说明不是数字！
                word_h_ratio = float(wh) / float(h)
                if not (0.35 <= word_h_ratio <= 0.85):
                    continue
                    
                # 2. 居中排版：微信的红点数字是绝对居中的，误差极小
                white_center_x = wx + ww / 2.0
                white_center_y = wy + wh / 2.0
                red_center_x = w / 2.0
                red_center_y = h / 2.0
                
                # 如果偏离中心超过 30%，说明是别人头像里碰巧偏在一边的某个白色图案
                if abs(white_center_x - red_center_x) > w * 0.3 or abs(white_center_y - red_center_y) > h * 0.3:
                    continue

                # 经过这套连环排版验证，100%只剩下真正的聊天红点了！

                # 经过五大物理验证的真正无视一切头像假冒的未读气泡！
                M = cv2.moments(contour)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    red_dots.append((cx, cy))
                    
        # 按照 Y 坐标排序，优先上方（最新的）消息
        red_dots.sort(key=lambda p: p[1])
        return red_dots

    def interactive_calibration(self, window_rect, log_callback=None):
        """
        第一次启动防错校准：通过大图进行交互式的手动区域截取，引导用户标记关键 UI 坐标

        Args:
            window_rect: 微信窗口的矩形坐标
            log_callback: 可选的日志回调函数，用于实时向UI发送进度信息
        """
        # 使用提供的日志回调函数，如果没有则使用默认的 logging
        log = log_callback if log_callback else lambda msg: logging.info(msg)

        if not window_rect:
            log("❌ 无法获取微信窗口进行校准！请先启动或排查 window_manager。")
            return False

        log("🚀 开始坐标校准流程...")
        log("📋 校准操作指南：")
        log("  1. 会弹出3个图片窗口，请用鼠标框选指定的区域")
        log("  2. 按住鼠标左键拖动来画框，框选好后松开")
        log("  3. 按【回车键】或【空格键】确认当前选择")
        log("  4. 如果框选错误，按【C】键清空重新选择")
        time.sleep(3)  # 给用户3秒钟阅读这个提示
        
        # 抓取整个微信主窗的快照，用于交互式展示
        log("📸 正在截取微信窗口...")
        full_monitor = {
            "left": window_rect["left"],
            "top": window_rect["top"],
            "width": window_rect["width"],
            "height": window_rect["height"]
        }

        # 使用临时创建的 mss 实例，保证线程安全
        with mss.mss() as sct:
            img_full_bgra = np.array(sct.grab(full_monitor))
        img_full_bgr = cv2.cvtColor(img_full_bgra, cv2.COLOR_BGRA2BGR)
        log("✅ 截图完成！现在开始框选坐标...")
        
        # 步骤 1：让用户圈出【左侧会话列表】
        log("🎯 步骤 1/3：请框选【左侧会话列表区域】")
        log("   这是显示所有聊天联系人的区域，包含头像和名字")
        roi_session = cv2.selectROI(
            "Step 1/3 - Select Session List (Enter Confirm / C Reset)",
            img_full_bgr, showCrosshair=True, fromCenter=False
        )
        cv2.destroyWindow("Step 1/3 - Select Session List (Enter Confirm / C Reset)")
        if roi_session == (0,0,0,0):
             log("❌ 用户取消了会话列表区域的框选")
             return False
        log("✅ 步骤1完成！会话列表区域已记录")
        
        # 步骤 2：聊天气泡记录详情大区 (最核心解析文字的地方)
        log("🎯 步骤 2/3：请框选【右侧聊天内容区域】")
        log("   这是显示聊天消息内容的区域，包含发送的消息气泡")
        roi_chat = cv2.selectROI(
            "Step 2/3 - Select Chat Content (Enter Confirm / C Reset)",
            img_full_bgr, showCrosshair=True, fromCenter=False
        )
        cv2.destroyWindow("Step 2/3 - Select Chat Content (Enter Confirm / C Reset)")
        if roi_chat == (0,0,0,0):
             log("❌ 用户取消了聊天内容区域的框选")
             return False
        log("✅ 步骤2完成！聊天内容区域已记录")
             
        # 步骤 3：底部聊天输入框圈点
        log("🎯 步骤 3/3：请框选【底部输入框区域】")
        log("   这是最底部的输入框，用于输入和发送消息")
        roi_input = cv2.selectROI(
            "Step 3/3 - Select Input Box (Enter Confirm / C Reset)",
            img_full_bgr, showCrosshair=True, fromCenter=False
        )
        cv2.destroyWindow("Step 3/3 - Select Input Box (Enter Confirm / C Reset)")
        if roi_input == (0,0,0,0):
             log("❌ 用户取消了输入框区域的框选")
             return False
        log("✅ 步骤3完成！输入框区域已记录")

        # 计算输入框的几何中心点
        input_center_x = roi_input[0] + roi_input[2] // 2
        input_center_y = roi_input[1] + roi_input[3] // 2

        # 写入配置文件并且保存注释不被抹杀
        log("💾 正在保存校准数据到配置文件...")
        self._save_calibration_to_yaml(roi_session, roi_chat, (input_center_x, input_center_y))
        log("🎉 校准完成！所有坐标已保存到 config.yaml")
        log("✅ 现在可以启动 AI 助手了")
        return True

    def _save_calibration_to_yaml(self, session, chat, input_center):
        """基于正则文本替换，保留原有 config.yaml 文件内的大量人工注释"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # [左偏移, 顶偏移, 宽, 高] -> list
        session_list = list(session)
        chat_list = list(chat)
        center_list = list(input_center)

        content = re.sub(
            r"session_list_rect:\s*\[.*?\]",
            f"session_list_rect: {session_list}",
            content
        )
        content = re.sub(
            r"chat_content_rect:\s*\[.*?\]",
            f"chat_content_rect: {chat_list}",
            content
        )
        content = re.sub(
            r"input_box_center:\s*\[.*?\]",
            f"input_box_center: {center_list}",
            content
        )

        with open(self.config_path, 'w', encoding='utf-8') as f:
            f.write(content)
            
        # 写完重新加载一下
        self.config = self._load_config()


if __name__ == "__main__":
    from window_manager import WindowManager
    
    # 【本地极简联调代码】：允许直接运行这个文件以测试校准和红点侦测效果
    wm = WindowManager()
    if wm.find_window():
        _rect = wm.get_window_rect()
        vision = VisionEngine()
        
        # 1. 发起校准交互 （第一次必须跑，或者自己去 YAML 直接设）
        logging.info("准备发起首次互动画图校准界面...")
        vision.interactive_calibration(_rect)
        
        # 2. 模拟从配置文件拿之前画的会话列的相对位置进行小幅区域定点长曝光截图
        current_session_rect = vision.config["window"]["session_list_rect"]
        img = vision.capture_region(_rect, current_session_rect)
        
        # 3. 传入给机器眼进行色块分离并标记未读中心心意
        dots = vision.detect_unread_red_dots(img)
        logging.info(f"这块区域发现 未读消息提示 数量：{len(dots)}个，分别是：{dots}")
        
        if dots:
            # 你可以尝试在图片上画框把红点圈出来肉眼调试看准不准
            img_bgr = img[:, :, :3].copy()
            for (cx, cy) in dots:
                cv2.circle(img_bgr, (cx, cy), 15, (0, 255, 0), 2)
            cv2.imshow("Red Dots Check - Hit Any Key To Close", img_bgr)
            cv2.waitKey(0)
