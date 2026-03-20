"""
微信 AI 助手 - 首次使用坐标校准工具

使用方法：
    python calibrate.py

运行后会自动：
1. 查找并激活微信窗口
2. 弹出三个画框界面，依次用鼠标框选：
   - 左侧会话列表区域
   - 右侧聊天内容区域
   - 底部输入框区域
3. 框选完成后坐标自动保存到 data/config.yaml

注意：请确保微信窗口已打开且为浅色模式
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.window_manager import WindowManager
from core.vision import VisionEngine


def main():
    print("""
    ========================================================
     微信 AI 助手 - 首次使用坐标校准工具
    ========================================================
    [操作指引]
    1. 请先打开微信并保持窗口可见
    2. 程序会弹出微信的截图,请用鼠标框选指定区域
    3. 框选好后按【回车/空格】确认，按【C】重画
    """)

    config_path = os.path.join("data", "config.yaml")

    # 检查 config.yaml 是否存在，不存在则从模板复制
    if not os.path.exists(config_path):
        example_path = os.path.join("data", "config.example.yaml")
        if os.path.exists(example_path):
            import shutil
            shutil.copy2(example_path, config_path)
            print(f"✅ 已从模板创建配置文件: {config_path}")
        else:
            print(f"❌ 找不到配置模板文件: {example_path}")
            sys.exit(1)

    wm = WindowManager()
    if not wm.find_window():
        print("❌ 未找到微信窗口！请先打开微信客户端。")
        sys.exit(1)

    wm.activate_window()
    rect = wm.get_window_rect()

    vision = VisionEngine(config_path=config_path)
    success = vision.interactive_calibration(rect)

    if success:
        print("\n🎉 校准完成！坐标已保存到 data/config.yaml")
        print("现在可以运行 python main.py 启动图形控制台了！")
    else:
        print("\n⚠️ 校准被取消或失败，请重新运行本脚本。")


if __name__ == "__main__":
    main()
