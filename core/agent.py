import os
import yaml
import logging
from openai import OpenAI

# 自动加载 .env 文件到环境变量（如果安装了 python-dotenv）
try:
    from dotenv import load_dotenv
    # 从项目根目录加载 .env
    _env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    load_dotenv(_env_path)
except ImportError:
    pass  # 没装 dotenv 也不影响，直接用系统环境变量或 YAML 兜底

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class AgentBrain:
    """
    智能体大脑模块 (LLM)
    抛弃复杂的原生逻辑代码，通过兼容 OpenAI 的封装直连各大模型 API (DeepSeek/GPT 等)
    构造拥有“灵魂人设”的上下文并指挥它吐出神似人类的聊天回复
    """
    def __init__(self, config_path="config.yaml"):
        self.config = self._load_config(config_path)
        llm_cfg = self.config.get("llm", {})
        
        # 优先级：环境变量(.env) > config.yaml > 默认值
        api_key = os.environ.get("LLM_API_KEY") or llm_cfg.get("api_key", "")
        base_url = os.environ.get("LLM_BASE_URL") or llm_cfg.get("base_url", "")
        self.model = os.environ.get("LLM_MODEL") or llm_cfg.get("model", "deepseek-chat")
        
        # 使用官方原生极简的 openai sdk，只要换了 base_url 它就能无缝对接包括 DeepSeek 甚至本地 Ollama 的任何模型
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )
        
        # 预设的基础 Persona 面具（你可以在这里自定义你的聊天风格和性格画像）
        self.system_prompt = (
            "你是微信的主人本人。你正在通过自动化程序代替主人和他的朋友、家人、同事聊天。\n"
            "你必须严格遵守以下行为准则，确保不被发现是机器代聊：\n"
            "1. 语气要温暖、自然、口语化，像朋友之间轻松聊天，绝对不能用'您'、'你好'、'很高兴为您服务'等机器味词汇。\n"
            "2. 回复要简短精炼，一般控制在一两句话以内（10~20个字最佳），不要长篇大论。\n"
            "3. 表达要积极友善，适当配合语气词（嗯、哈哈、好嘞、行、好的呀），像真实的人在手机上随手打字。\n"
            "4. 如果对方发表情包或开玩笑，你要配合气氛回应，保持幽默但不要攻击性的回复。\n"
            "5. 如果对方说的话涉及情绪（生气、难过、撒娇），你要安抚、共情、体贴回应，绝对不能怼回去。\n"
            "6. 如果上下文里有特殊的例如 '[图片]' '[语音]' 等标志，委婉地说你不方便看或听，让对方发文字。\n"
            "7. 只输出你想发送的纯文本内容，不要包裹任何多余的解释、标点符号堆砌和 xml 代码块标记。"
        )

    def _load_config(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def think_and_reply(self, new_messages_context: list) -> str:
        """
        接收一批从 ocr_parser 过来的增量上下文信息，推给大模型进行阅读理解和自动回复生成
        :param new_messages_context: 形如 [{"text": "在吗", "sender": "them", "is_multimodal": False}, ...]
        :return: 决定发出去的最终文字
        """
        if not new_messages_context:
            return ""

        # 构建标准的聊天列阵
        messages_prompt = [{"role": "system", "content": self.system_prompt}]
        
        has_new_them_msg = False
        
        for msg in new_messages_context:
            role = "user" if msg["sender"] == "them" else "assistant"
            if role == "user":
                has_new_them_msg = True
                
            content = msg["text"]
            if msg.get("is_multimodal"):
                # 如果这个包是张贴图，我们要在传给大模型的话底下打个小报告强行降级它
                content = f"[{content}] (系统上帝视角提示：对方发来了一条包含你不支持的媒体格式消息，你要找借口告诉他你现在的这台设备处理不了)"
                
            messages_prompt.append({"role": role, "content": content})

        # 核心防卡死机制：如果这段历史里根本没有对方 ('them') 发来的新消息（全是历史的自己的留言等）
        # 完全没有必要调用大模型思考浪费 Token 甚至让它强行抢话
        if not has_new_them_msg:
            logging.info("大脑：队列里没有需要回复对方的增量话语，进入假死待机...")
            return ""
            
        try:
            logging.info(f"大脑：正在向远端云节点 ({self.model}) 发送 {len(messages_prompt)} 条记忆碎片进行思考演算...")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages_prompt,
                temperature=0.7, # 根据大模型厂商的最佳聊天口语化体验值，不能太严谨
                max_tokens=150
            )
            reply_text = response.choices[0].message.content.strip()
            logging.info(f"大脑：电火花演算完毕，产出文字指令 ➡️ 【{reply_text}】")
            return reply_text
            
        except Exception as e:
            logging.error(f"大脑：脑卒中崩溃！连接大模型 API 端点失败 - 原因: {e}")
            return "..." # 如果网络崩了，回复三个点避免微信对话挂住或者出错

if __name__ == "__main__":
    # 本地跑通极简独立验证环节，直接调取 deepseek 的接口看它有没联网反应过来
    brain = AgentBrain()
    
    # 模拟构建一条 ocr 传过来的假测试消息列阵
    mock_msg = [{"text": "晚上一起去吃个那家铁板烧么，感觉很久没聚了", "sender": "them", "is_multimodal": False}]
    
    reply = brain.think_and_reply(mock_msg)
    print(f"\n======================================")
    print(f"📥 收到模拟消息: {mock_msg[0]['text']}")
    print(f"🤖 Agent 大脑极速生成的拟人回复: {reply}")
    print(f"======================================\n")
