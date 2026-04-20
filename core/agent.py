import os
import yaml
import logging
import re
from openai import OpenAI
from .memory_manager import MemoryManager

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
    def __init__(self, config_path="data/config.yaml"):
        self.config = self._load_config(config_path)

        # P1 阶段新增：输出风控护栏 - 高危词汇黑名单
        self.danger_keywords = self._init_danger_keywords()

        # P2 阶段新增：记忆管理器 - 存储和检索聊天历史
        try:
            db_path = self.config.get("memory", {}).get("db_path", "data/memory.db")
            enable_encryption = self.config.get("memory", {}).get("enable_encryption", True)
            self.memory = MemoryManager(db_path=db_path, enable_encryption=enable_encryption)
            logging.info("🧠 大脑：记忆管理器已就绪")
        except Exception as e:
            logging.error(f"❌ 大脑：记忆管理器初始化失败 - {e}")
            self.memory = None  # 降级模式：无记忆功能

        # 支持新的多模型配置系统
        models = self.config.get("models", [])
        current_model_id = self.config.get("current_model_id", "")

        # 优先使用多模型配置
        if models and current_model_id:
            # 找到当前使用的模型
            current_model = next((m for m in models if m.get("id") == current_model_id), None)
            if current_model:
                api_key = current_model.get("api_key", "")
                base_url = current_model.get("base_url", "")
                self.model = current_model.get("model", "deepseek-chat")
                logging.info(f"大脑：使用多模型配置 [{current_model.get('name', 'Unknown')}]")
            else:
                # 如果找不到指定模型，使用旧配置
                logging.warning(f"大脑：未找到模型 ID '{current_model_id}'，回退到旧配置")
                api_key, base_url, self.model = self._get_legacy_config()
        else:
            # 回退到旧配置方式
            api_key, base_url, self.model = self._get_legacy_config()

        # 使用官方原生极简的 openai sdk，只要换了 base_url 它就能无缝对接包括 DeepSeek 甚至本地 Ollama 的任何模型
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )

        # 加载联系人专属人设配置 (V1.1 新增)
        self.personas = self.config.get("contacts_personas", {})
        self.default_persona = self.personas.get("default", {}).get("system_prompt", "")

        # 预设的基础 Persona 面具（你可以在这里自定义你的聊天风格和性格画像）
        # 注意：现在优先使用配置文件中的人设，如果没有配置则使用这个默认值
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

    def _init_danger_keywords(self) -> list:
        """
        P1 阶段新增：初始化危险关键词黑名单
        :return: 危险关键词列表
        """
        return [
            # 财务类高危词
            r'转账', r'汇款', r'打钱', r'付款', r'支付',
            # 账户安全类
            r'密码', r'验证码', r'账号', r'登录',
            # 个人隐私类
            r'身份证', r'身份证号', r'证件号',
            # 退款类（商业风险）
            r'退款', r'退钱', r'退货', r'赔偿', r'赔款',
            # 承诺类（避免过度承诺）
            r'保证', r'担保', r'承诺',
            # 合同协议类
            r'合同', r'协议', r'签约',
        ]

    def _check_safety_guardrail(self, text: str) -> tuple:
        """
        P1 阶段新增：风控护栏检查，检测高危词汇
        :param text: 待检查的文本
        :return: (is_safe, processed_text, warning_msg)
            - is_safe: True 表示安全，False 表示触发风控
            - processed_text: 处理后的文本（命中风控时为兜底话术）
            - warning_msg: 警告信息
        """
        if not text:
            return True, text, ""

        try:
            # 遍历所有危险关键词模式
            for pattern in self.danger_keywords:
                if re.search(pattern, text):
                    # 命中风控！
                    warning_msg = f"🚨 安全防线：输出风控拦截！检测到高危词汇 '{pattern}'"

                    # 安全的兜底话术
                    fallback_responses = [
                        "这个问题比较敏感，我需要确认一下具体情况，稍后回复你哈。",
                        "涉及到重要操作，建议你直接联系官方客服处理比较稳妥。",
                        "这个事情我需要核实一下，暂时不能直接答复。",
                        "不好意思，这个操作需要本人确认，我没法代劳呢。",
                        "这事儿比较重要，建议你电话联系官方处理更安全。",
                    ]

                    import random
                    safe_response = random.choice(fallback_responses)

                    logging.warning(f"{warning_msg}")
                    logging.warning(f"   原始回复：{text}")
                    logging.warning(f"   已替换为安全话术：{safe_response}")

                    return False, safe_response, warning_msg

            # 未命中任何高危词，通过检查
            return True, text, ""

        except Exception as e:
            logging.error(f"❌ 安全防线：风控检查失败 - {e}")
            # 出错时采用保守策略：允许通过但记录日志
            return True, text, f"风控检查出错: {e}"

    def _get_legacy_config(self):
        """旧的配置读取方式，作为回退方案"""
        llm_cfg = self.config.get("llm", {})
        # 优先级：环境变量 > config.yaml > 默认值
        api_key = os.environ.get("LLM_API_KEY") or llm_cfg.get("api_key", "")
        base_url = os.environ.get("LLM_BASE_URL") or llm_cfg.get("base_url", "")
        model = os.environ.get("LLM_MODEL") or llm_cfg.get("model", "deepseek-chat")
        logging.info(f"大脑：使用旧配置 ({model})")
        return api_key, base_url, model

    def _load_config(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def _get_persona_for_contact(self, contact_name: str = None) -> str:
        """
        根据联系人名字获取对应的系统人设 (V1.1 新增)
        :param contact_name: 联系人名字（支持逗号分隔的多人配置）
        :return: 对应的人设 prompt
        """
        # 优先级：配置文件默认人设 > 代码硬编码默认人设
        base_persona = self.default_persona if self.default_persona else self.system_prompt

        if not contact_name:
            logging.debug("大脑：未提供联系人名字，使用默认人设")
            return base_persona

        # 精确匹配
        if contact_name in self.personas:
            persona_config = self.personas[contact_name]
            if not persona_config.get("enabled", True):
                logging.info(f"大脑：联系人 '{contact_name}' 的人设已禁用，使用默认人设")
                return base_persona

            # 检查是否引用模板
            if "persona_template" in persona_config:
                template_id = persona_config["persona_template"]
                templates = self.personas.get("templates", {})
                if template_id in templates:
                    template = templates[template_id]
                    logging.info(f"大脑：为联系人 '{contact_name}' 使用模板 '{template.get('name', template_id)}'")
                    return template.get("system_prompt", base_persona)
                else:
                    logging.warning(f"大脑：联系人 '{contact_name}' 引用的模板 '{template_id}' 不存在，使用默认人设")
                    return base_persona
            else:
                # 使用自定义人设
                persona = persona_config.get("system_prompt", base_persona)
                logging.info(f"大脑：为联系人 '{contact_name}' 使用专属人设 '{persona_config.get('name', '未知')}'")
                return persona

        # 多人配置匹配：检查是否有人设配置的 aliases 字段包含当前联系人
        import re
        for key, persona_config in self.personas.items():
            if key == "default" or key == "templates":
                continue

            if persona_config.get("enabled", True):
                # 检查 aliases 字段（支持逗号分隔的多个别名）
                aliases = persona_config.get("aliases", [])
                if isinstance(aliases, str):
                    aliases = [a.strip() for a in aliases.split(',')]

                if contact_name in aliases:
                    logging.info(f"大脑：联系人 '{contact_name}' 匹配到别名配置 '{key}'")

                    # 检查是否引用模板
                    if "persona_template" in persona_config:
                        template_id = persona_config["persona_template"]
                        templates = self.personas.get("templates", {})
                        if template_id in templates:
                            template = templates[template_id]
                            return template.get("system_prompt", base_persona)
                    else:
                        return persona_config.get("system_prompt", base_persona)

                # 模糊匹配（OCR可能识别错误）
                # 去除空格和特殊字符进行比较
                clean_contact = re.sub(r'[\s\-_]', '', contact_name)
                clean_key = re.sub(r'[\s\-_]', '', key)

                # 包含关系匹配
                if clean_contact in clean_key or clean_key in clean_contact:
                    # 检查是否引用模板
                    if "persona_template" in persona_config:
                        template_id = persona_config["persona_template"]
                        templates = self.personas.get("templates", {})
                        if template_id in templates:
                            template = templates[template_id]
                            logging.info(f"大脑：使用模糊匹配+模板 '{template.get('name', template_id)}' 对应联系人 '{contact_name}'")
                            return template.get("system_prompt", base_persona)
                    else:
                        persona = persona_config.get("system_prompt", base_persona)
                        logging.info(f"大脑：使用模糊匹配人设 '{key}' 对应联系人 '{contact_name}'")
                        return persona

        # 未找到匹配，使用默认人设
        logging.debug(f"大脑：未找到联系人 '{contact_name}' 的专属人设，使用默认人设")
        return base_persona

    def think_and_reply(self, new_messages_context: list, contact_name: str = None) -> str:
        """
        接收一批从 ocr_parser 过来的增量上下文信息，推给大模型进行阅读理解和自动回复生成
        :param new_messages_context: 形如 [{"text": "在吗", "sender": "them", "is_multimodal": False}, ...]
        :param contact_name: 当前联系人名字（用于选择专属人设）V1.1 新增
        :return: 决定发出去的最终文字
        """
        if not new_messages_context:
            return ""

        # 根据联系人选择对应的 system_prompt (V1.1 新增)
        persona = self._get_persona_for_contact(contact_name)
        messages_prompt = [{"role": "system", "content": persona}]

        # P2 阶段新增：从记忆库中获取历史上下文
        if self.memory and contact_name:
            try:
                # 获取最近的历史记录（默认 20 条）
                history_context = self.memory.get_context(contact_name, limit=20)
                if history_context:
                    messages_prompt.extend(history_context)
                    logging.debug(f"🧠 大脑：从记忆库加载了 {len(history_context)} 条历史记录")
            except Exception as e:
                logging.warning(f"⚠️ 大脑：加载历史记忆失败，继续无记忆模式 - {e}")

        has_new_them_msg = False
        new_user_messages = []  # 存储对方的新消息，用于后续保存到记忆库

        for msg in new_messages_context:
            role = "user" if msg["sender"] == "them" else "assistant"
            if role == "user":
                has_new_them_msg = True
                # 记录对方的新消息内容
                new_user_messages.append(msg["text"])

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
                max_tokens=1024
            )

            # 安全检查：确保响应结构和内容都存在
            if not response or not response.choices or len(response.choices) == 0:
                logging.error("大脑：API 返回空响应，没有生成任何内容")
                return "..."

            if not response.choices[0].message:
                logging.error("大脑：API 返回的响应中没有 message 字段")
                return "..."

            if not response.choices[0].message.content:
                logging.error("大脑：API 返回的 message.content 为空")
                logging.error(f"   完整响应结构：{response}")
                return "..."

            reply_text = response.choices[0].message.content.strip()
            logging.info(f"大脑：电火花演算完毕，产出文字指令 ➡️ 【{reply_text}】")

            # P1 阶段新增：输出风控护栏检查（LLM 生成后、返回前）
            is_safe, processed_text, warning_msg = self._check_safety_guardrail(reply_text)
            if not is_safe:
                logging.warning(f"⚠️ 安全防线：风控已拦截，返回安全话术")
                # 可以在这里选择是否记录到专门的告警日志文件
                # 或者触发通知（如发送邮件/推送给管理员）

            # P2 阶段新增：将对话记录保存到记忆库
            # 选择保存过滤后的安全回答，理由：
            # 1. 数据库中的记录主要用于提供上下文，保存安全话术能保持上下文一致性
            # 2. 如果保存高风险内容，可能会在后续对话中继续引发问题
            # 3. 实际发送给用户的是安全话术，保存安全话术符合真实交互
            # 4. 原始回答已记录在日志中，可用于安全审计
            if self.memory and contact_name:
                try:
                    # 保存对方的新消息
                    for user_msg in new_user_messages:
                        self.memory.add_message(contact_name, "user", user_msg)

                    # 保存 AI 的回答（保存过滤后的安全话术）
                    self.memory.add_message(contact_name, "assistant", processed_text)
                    logging.debug("💾 大脑：对话记录已保存到记忆库")
                except Exception as e:
                    logging.warning(f"⚠️ 大脑：保存对话记录到记忆库失败 - {e}")

            return processed_text

        except Exception as e:
            logging.error(f"大脑：脑卒中崩溃！连接大模型 API 端点失败 - 原因: {e}")
            logging.error(f"   当前模型: {self.model}")
            logging.error(f"   消息数量: {len(messages_prompt)}")
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
