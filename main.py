import os
import sys
import threading
import time
import webview
import yaml
import shutil
import re
from dotenv import load_dotenv, set_key

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
        self.config_path = "data/config.yaml"
        self.env_path = ".env"

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

    def get_work_mode(self):
        """获取当前工作模式"""
        try:
            if not os.path.exists(self.config_path):
                return {"status": "ok", "mode": "auto"}  # 默认自动模式

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            mode = config.get('work_mode', 'auto')
            return {"status": "ok", "mode": mode}
        except Exception as e:
            return {"status": "error", "msg": f"获取工作模式失败: {str(e)}"}

    def set_work_mode(self, mode):
        """设置工作模式"""
        try:
            if mode not in ['auto', 'assist']:
                return {"status": "error", "msg": "无效的工作模式，必须是 'auto' 或 'assist'"}

            if not os.path.exists(self.config_path):
                return {"status": "error", "msg": "配置文件不存在"}

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            config['work_mode'] = mode

            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            return {"status": "ok", "msg": f"已切换到{'自动' if mode == 'auto' else '辅助'}模式"}
        except Exception as e:
            return {"status": "error", "msg": f"设置工作模式失败: {str(e)}"}

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

    def maximize_app(self):
        """最大化/还原窗口"""
        if hasattr(self, '_window') and self._window:
            self._window.toggle_fullscreen()

    def close_app(self):
        """关闭窗口"""
        if hasattr(self, '_window') and self._window:
            self._window.destroy()

    def read_config(self):
        """
        读取当前配置
        返回包含所有配置的字典，坐标值转换为便于理解的格式
        """
        try:
            if not os.path.exists(self.config_path):
                return {"status": "error", "msg": "配置文件不存在，请先运行校准工具"}

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            # 检查坐标是否已校准（所有坐标值不全为0）
            window_cfg = config.get('window', {})
            is_calibrated = all([
                window_cfg.get('session_list_rect', [0, 0, 0, 0])[2] > 0,  # width > 0
                window_cfg.get('chat_content_rect', [0, 0, 0, 0])[2] > 0,  # width > 0
                window_cfg.get('input_box_center', [0, 0])[0] > 0  # x > 0
            ])

            # 读取模型配置
            models = config.get('models', [])
            current_model_id = config.get('current_model_id', '')
            current_model = None
            if models and current_model_id:
                current_model = next((m for m in models if m.get('id') == current_model_id), None)

            # 读取环境变量（如果存在，作为备选）
            env_config = {}
            if os.path.exists(self.env_path):
                load_dotenv(self.env_path)
                env_config = {
                    'api_key': os.environ.get('LLM_API_KEY', ''),
                    'base_url': os.environ.get('LLM_BASE_URL', ''),
                    'model': os.environ.get('LLM_MODEL', '')
                }

            return {
                "status": "ok",
                "config": config,
                "env": env_config,
                "is_calibrated": is_calibrated,
                "models": models,
                "current_model": current_model
            }
        except Exception as e:
            return {"status": "error", "msg": f"读取配置失败: {str(e)}"}

    def update_config(self, config_data):
        """
        更新配置文件
        :param config_data: 前端传来的配置字典（只包含需要更新的字段）
        """
        try:
            # 验证输入
            validation_result = self._validate_config_data(config_data)
            if not validation_result['valid']:
                return {"status": "error", "msg": validation_result['message']}

            # 先读取现有配置
            if not os.path.exists(self.config_path):
                return {"status": "error", "msg": "配置文件不存在"}

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            # 更新配置（递归更新）
            def deep_update(target, update):
                for key, value in update.items():
                    if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                        deep_update(target[key], value)
                    else:
                        target[key] = value

            deep_update(config, config_data)

            # 写回文件
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            return {"status": "ok", "msg": "配置已保存"}
        except Exception as e:
            return {"status": "error", "msg": f"保存配置失败: {str(e)}"}

    def update_env(self, env_data):
        """
        更新 .env 文件
        :param env_data: 包含 api_key, base_url, model 的字典
        """
        try:
            # 验证输入
            validation_result = self._validate_env_data(env_data)
            if not validation_result['valid']:
                return {"status": "error", "msg": validation_result['message']}

            # 确保 .env 文件存在
            if not os.path.exists(self.env_path):
                with open(self.env_path, 'w', encoding='utf-8') as f:
                    f.write("")

            # 使用 python-dotenv 的 set_key 函数更新
            api_key = env_data.get('api_key', '')
            base_url = env_data.get('base_url', '')
            model = env_data.get('model', '')

            if api_key:
                set_key(self.env_path, 'LLM_API_KEY', api_key)
            if base_url:
                set_key(self.env_path, 'LLM_BASE_URL', base_url)
            if model:
                set_key(self.env_path, 'LLM_MODEL', model)

            # 重新加载环境变量
            load_dotenv(self.env_path, override=True)

            return {"status": "ok", "msg": "环境变量已更新"}
        except Exception as e:
            return {"status": "error", "msg": f"更新环境变量失败: {str(e)}"}

    def _validate_env_data(self, env_data):
        """验证环境变量数据"""
        # 验证 API Key（必须提供）
        api_key = env_data.get('api_key', '')
        if not api_key:
            return {'valid': False, 'message': 'API Key 不能为空'}

        # 验证 Base URL（如果提供）
        base_url = env_data.get('base_url', '')
        if base_url and not base_url.startswith(('http://', 'https://')):
            return {'valid': False, 'message': 'Base URL 格式不正确，应以 "http://" 或 "https://" 开头'}

        # 验证模型名称
        model = env_data.get('model', '')
        if not model:
            return {'valid': False, 'message': '模型名称不能为空'}

        return {'valid': True}

    def _validate_config_data(self, config_data):
        """验证配置数据"""
        # 验证 OCR 置信度阈值
        ocr_cfg = config_data.get('ocr', {})
        if 'confidence_threshold' in ocr_cfg:
            threshold = ocr_cfg['confidence_threshold']
            if not isinstance(threshold, (int, float)) or not (0.0 <= threshold <= 1.0):
                return {'valid': False, 'message': 'OCR 置信度阈值必须在 0.0 到 1.0 之间'}

        # 验证防风控配置
        anti_risk_cfg = config_data.get('anti_risk', {})
        if 'global_typo_rate' in anti_risk_cfg:
            typo_rate = anti_risk_cfg['global_typo_rate']
            if not isinstance(typo_rate, (int, float)) or not (0.0 <= typo_rate <= 0.2):
                return {'valid': False, 'message': '错别字率必须在 0.0 到 0.2 之间'}

        if 'sleep_hours' in anti_risk_cfg:
            sleep_hours = anti_risk_cfg['sleep_hours']
            if sleep_hours and not re.match(r'^\d{2}:\d{2}-\d{2}:\d{2}$', sleep_hours):
                return {'valid': False, 'message': '睡眠时间格式不正确，应为 "HH:MM-HH:MM" 格式'}

        return {'valid': True}

    def start_calibration(self):
        """
        启动坐标校准流程
        这个方法会在新的线程中运行校准工具，避免阻塞 UI
        """
        def run_calibration():
            try:
                from core.window_manager import WindowManager
                from core.vision import VisionEngine

                log("🚀 开始坐标校准流程...")
                log("📱 请确保微信客户端已打开且窗口可见")

                config_path = self.config_path

                # 检查 config.yaml 是否存在，不存在则从模板复制
                if not os.path.exists(config_path):
                    example_path = os.path.join("data", "config.example.yaml")
                    if os.path.exists(example_path):
                        shutil.copy2(example_path, config_path)
                        log(f"✅ 已从模板创建配置文件: {config_path}")
                    else:
                        log(f"❌ 找不到配置模板文件: {example_path}")
                        return

                wm = WindowManager()
                if not wm.find_window():
                    log("❌ 未找到微信窗口！请先打开微信客户端。")
                    log("💡 提示：确保微信窗口可见，不要最小化")
                    return

                log("✅ 成功找到微信窗口")
                wm.activate_window()
                rect = wm.get_window_rect()

                vision = VisionEngine(config_path=config_path)
                # 传递 log 函数给校准方法，实现实时进度反馈
                success = vision.interactive_calibration(rect, log_callback=log)

                if success:
                    log("🎉 校准完成！现在可以使用 AI 助手了")
                else:
                    log("⚠️ 校准被取消或失败，请重新尝试")

            except Exception as e:
                log(f"❌ 校准过程出错: {str(e)}")
                log("💡 如果问题持续，请检查微信是否正常运行")

        # 在新线程中运行校准，避免阻塞 UI
        calibration_thread = threading.Thread(target=run_calibration, daemon=True)
        calibration_thread.start()

        return {"status": "ok", "msg": "校准流程已启动"}

    def add_model(self, model_data):
        """
        添加新的AI模型配置
        :param model_data: 包含 id, name, provider, api_key, base_url, model 的字典
        """
        try:
            # 验证输入
            validation_result = self._validate_model_data(model_data)
            if not validation_result['valid']:
                return {"status": "error", "msg": validation_result['message']}

            # 读取现有配置
            if not os.path.exists(self.config_path):
                return {"status": "error", "msg": "配置文件不存在"}

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            # 初始化 models 数组
            if 'models' not in config:
                config['models'] = []

            # 检查 ID 是否已存在
            existing_ids = [m.get('id') for m in config['models']]
            if model_data['id'] in existing_ids:
                return {"status": "error", "msg": f"模型 ID '{model_data['id']}' 已存在，请使用不同的 ID"}

            # 添加新模型
            config['models'].append(model_data)

            # 如果是第一个模型，自动设为当前模型
            if len(config['models']) == 1:
                config['current_model_id'] = model_data['id']

            # 写回文件
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            return {"status": "ok", "msg": "模型添加成功"}
        except Exception as e:
            return {"status": "error", "msg": f"添加模型失败: {str(e)}"}

    def update_model(self, model_id, model_data):
        """
        更新现有模型配置
        :param model_id: 要更新的模型 ID
        :param model_data: 新的模型数据
        """
        try:
            # 验证输入
            validation_result = self._validate_model_data(model_data)
            if not validation_result['valid']:
                return {"status": "error", "msg": validation_result['message']}

            # 读取现有配置
            if not os.path.exists(self.config_path):
                return {"status": "error", "msg": "配置文件不存在"}

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            # 查找并更新模型
            models = config.get('models', [])
            model_index = next((i for i, m in enumerate(models) if m.get('id') == model_id), None)

            if model_index is None:
                return {"status": "error", "msg": f"未找到 ID 为 '{model_id}' 的模型"}

            # 保持原有的 ID
            model_data['id'] = model_id
            models[model_index] = model_data
            config['models'] = models

            # 写回文件
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            return {"status": "ok", "msg": "模型更新成功"}
        except Exception as e:
            return {"status": "error", "msg": f"更新模型失败: {str(e)}"}

    def delete_model(self, model_id):
        """
        删除模型配置
        :param model_id: 要删除的模型 ID
        """
        try:
            # 读取现有配置
            if not os.path.exists(self.config_path):
                return {"status": "error", "msg": "配置文件不存在"}

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            models = config.get('models', [])
            model_count = len(models)

            # 如果只有一个模型，不允许删除
            if model_count <= 1:
                return {"status": "error", "msg": "至少需要保留一个模型配置"}

            # 查找并删除模型
            model_index = next((i for i, m in enumerate(models) if m.get('id') == model_id), None)
            if model_index is None:
                return {"status": "error", "msg": f"未找到 ID 为 '{model_id}' 的模型"}

            # 删除模型
            models.pop(model_index)

            # 如果删除的是当前模型，需要重新设置当前模型
            if config.get('current_model_id') == model_id:
                config['current_model_id'] = models[0].get('id')

            config['models'] = models

            # 写回文件
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            return {"status": "ok", "msg": "模型删除成功"}
        except Exception as e:
            return {"status": "error", "msg": f"删除模型失败: {str(e)}"}

    def set_current_model(self, model_id):
        """
        设置当前使用的模型
        :param model_id: 要设置为当前的模型 ID
        """
        try:
            # 读取现有配置
            if not os.path.exists(self.config_path):
                return {"status": "error", "msg": "配置文件不存在"}

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            # 检查模型是否存在
            models = config.get('models', [])
            model_exists = any(m.get('id') == model_id for m in models)

            if not model_exists:
                return {"status": "error", "msg": f"未找到 ID 为 '{model_id}' 的模型"}

            # 设置当前模型
            config['current_model_id'] = model_id

            # 写回文件
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            return {"status": "ok", "msg": "当前模型已切换"}
        except Exception as e:
            return {"status": "error", "msg": f"设置当前模型失败: {str(e)}"}

    def _validate_model_data(self, model_data):
        """验证模型数据"""
        required_fields = ['id', 'name', 'provider', 'api_key', 'base_url', 'model']
        for field in required_fields:
            if field not in model_data or not model_data[field]:
                return {'valid': False, 'message': f'缺少必要字段: {field}'}

        # 验证 ID 格式（只允许字母、数字、下划线、连字符）
        model_id = model_data['id']
        if not re.match(r'^[a-zA-Z0-9_-]+$', model_id):
            return {'valid': False, 'message': '模型 ID 只能包含字母、数字、下划线和连字符'}

        # 验证 Base URL 格式
        base_url = model_data['base_url']
        if not base_url.startswith(('http://', 'https://')):
            return {'valid': False, 'message': 'Base URL 格式不正确，应以 "http://" 或 "https://" 开头'}

        # 验证 API Key 格式（根据提供商）
        provider = model_data['provider']
        api_key = model_data['api_key']

        if provider == 'deepseek' and not api_key.startswith('sk-'):
            return {'valid': False, 'message': 'DeepSeek API Key 应以 "sk-" 开头'}
        elif provider == 'openai' and not api_key.startswith('sk-'):
            return {'valid': False, 'message': 'OpenAI API Key 应以 "sk-" 开头'}

        return {'valid': True}

    # ============================================================
    # 联系人专属人设管理 API (V1.1 新增)
    # ============================================================

    def get_contact_personas(self):
        """
        获取所有联系人人设配置
        :return: 包含所有人设配置的字典
        """
        try:
            if not os.path.exists(self.config_path):
                return {"status": "error", "msg": "配置文件不存在"}

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            personas = config.get("contacts_personas", {})

            return {
                "status": "ok",
                "personas": personas,
                "count": len(personas) - 1 if "default" in personas else len(personas)  # 不计算default
            }
        except Exception as e:
            return {"status": "error", "msg": f"读取人设配置失败: {str(e)}"}

    def add_contact_persona(self, contact_name, persona_data):
        """
        添加新的联系人人设
        :param contact_name: 联系人名字（作为配置key）
        :param persona_data: 人设数据字典
        """
        try:
            # 验证输入
            validation_result = self._validate_persona_data(persona_data)
            if not validation_result['valid']:
                return {"status": "error", "msg": validation_result['message']}

            # 读取现有配置
            if not os.path.exists(self.config_path):
                return {"status": "error", "msg": "配置文件不存在"}

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            # 初始化 contacts_personas 段
            if 'contacts_personas' not in config:
                config['contacts_personas'] = {}

            # 检查是否已存在
            if contact_name in config['contacts_personas']:
                return {"status": "error", "msg": f"联系人 '{contact_name}' 的人设已存在"}

            # 添加新人设
            persona_data['enabled'] = persona_data.get('enabled', True)
            config['contacts_personas'][contact_name] = persona_data

            # 写回文件
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            return {"status": "ok", "msg": f"已为联系人 '{contact_name}' 添加人设"}
        except Exception as e:
            return {"status": "error", "msg": f"添加人设失败: {str(e)}"}

    def update_contact_persona(self, contact_name, persona_data):
        """
        更新现有联系人人设
        :param contact_name: 联系人名字
        :param persona_data: 新的人设数据
        """
        try:
            # 验证输入
            validation_result = self._validate_persona_data(persona_data)
            if not validation_result['valid']:
                return {"status": "error", "msg": validation_result['message']}

            # 读取现有配置
            if not os.path.exists(self.config_path):
                return {"status": "error", "msg": "配置文件不存在"}

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            # 初始化 contacts_personas 段
            if 'contacts_personas' not in config:
                config['contacts_personas'] = {}

            personas = config['contacts_personas']

            # 特殊处理：对于 default 人设，如果不存在就创建它
            if contact_name == "default":
                if contact_name not in personas:
                    # default 人设不存在，直接创建（不使用 add 方法避免重复检查）
                    persona_data['enabled'] = True
                    config['contacts_personas'][contact_name] = persona_data
                else:
                    # default 人设已存在，只允许更新内容，不允许修改名字
                    persona_data['enabled'] = persona_data.get('enabled', True)
                    config['contacts_personas'][contact_name] = persona_data
            else:
                # 普通联系人：检查是否存在
                if contact_name not in personas:
                    return {"status": "error", "msg": f"未找到联系人 '{contact_name}' 的人设配置"}

                # 更新人设
                persona_data['enabled'] = persona_data.get('enabled', True)
                config['contacts_personas'][contact_name] = persona_data

            # 写回文件
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            return {"status": "ok", "msg": f"已更新联系人 '{contact_name}' 的人设"}
        except Exception as e:
            return {"status": "error", "msg": f"更新人设失败: {str(e)}"}

    def delete_contact_persona(self, contact_name):
        """
        删除联系人人设
        :param contact_name: 要删除的联系人名字
        """
        try:
            # 读取现有配置
            if not os.path.exists(self.config_path):
                return {"status": "error", "msg": "配置文件不存在"}

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            personas = config.get("contacts_personas", {})

            # 保护默认人设
            if contact_name == "default":
                return {"status": "error", "msg": "不能删除默认人设"}

            # 检查是否存在
            if contact_name not in personas:
                return {"status": "error", "msg": f"未找到联系人 '{contact_name}' 的人设配置"}

            # 删除人设
            del config['contacts_personas'][contact_name]

            # 写回文件
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            return {"status": "ok", "msg": f"已删除联系人 '{contact_name}' 的人设"}
        except Exception as e:
            return {"status": "error", "msg": f"删除人设失败: {str(e)}"}

    def set_default_persona(self, persona_data):
        """
        设置默认人设
        :param persona_data: 默认人设数据
        """
        try:
            # 验证输入
            validation_result = self._validate_persona_data(persona_data)
            if not validation_result['valid']:
                return {"status": "error", "msg": validation_result['message']}

            # 读取现有配置
            if not os.path.exists(self.config_path):
                return {"status": "error", "msg": "配置文件不存在"}

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            # 初始化 contacts_personas 段
            if 'contacts_personas' not in config:
                config['contacts_personas'] = {}

            # 设置默认人设
            persona_data['enabled'] = True
            config['contacts_personas']['default'] = persona_data

            # 写回文件
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            return {"status": "ok", "msg": "默认人设已更新"}
        except Exception as e:
            return {"status": "error", "msg": f"更新默认人设失败: {str(e)}"}

    def get_persona_templates(self):
        """
        获取人设模板库
        :return: 预设的人设模板
        """
        try:
            # 预设人设模板
            templates = {
                "professional": {
                    "name": "商务专业",
                    "description": "适用于客户、领导、商务伙伴",
                    "system_prompt": """你正在回复重要的工作伙伴，请注意：
1. 语气要专业、简洁、礼貌，体现职业素养
2. 回复要直接切中要点，避免过多的闲聊
3. 工作相关用语要准确，可以用"好的"、"收到"、"明白"等确认词
4. 适当使用"您"表示尊重，但不要过于正式
5. 只输出回复内容，不要有任何解释性文字"""
                },
                "casual": {
                    "name": "轻松随意",
                    "description": "适用于朋友、同学、熟人",
                    "system_prompt": """你正在回复最好的朋友，请注意：
1. 语气要超级轻松、随意，就像平时聊天一样
2. 可以开玩笑、调侃、使用网络流行语
3. 回复可以简短甚至用表情包式的回复（如"哈哈"、"2333"、"绝了"）
4. 可以适当吐槽、自嘲，不用太客气
5. 纯聊天模式，只输出你想说的话"""
                },
                "warm": {
                    "name": "温暖关怀",
                    "description": "适用于家人、伴侣、亲密关系",
                    "system_prompt": """你正在回复家人，请注意：
1. 语气要温暖、体贴，充满关怀和爱意
2. 可以使用一些亲昵的称呼和表情
3. 关注对方的感受，多体贴和关心
4. 回复可以稍微长一点，表达更多情感
5. 只输出你想说的话，自然亲切"""
                },
                "service": {
                    "name": "客服服务",
                    "description": "适用于客户服务场景",
                    "system_prompt": """你是专业的客服代表，请注意：
1. 语气要友善、专业、耐心
2. 准确理解客户需求，提供有效帮助
3. 使用礼貌用语，如"您好"、"请"、"谢谢"
4. 遇到无法解答的问题，诚实告知并提供替代方案
5. 只输出回复内容，保持专业形象"""
                },
                "tech_geek": {
                    "name": "技术极客",
                    "description": "适用于技术交流、程序员、开发者",
                    "system_prompt": """你是技术达人，请注意：
1. 可以使用技术术语和程序员梗，但不要过度
2. 语气直接、高效，崇尚代码般的简洁
3. 讨论技术问题时要准确，不懂的可以坦诚说需要查一下
4. 适当使用技术圈流行语（如"踩坑"、"填坑"、"最佳实践"）
5. 只输出回复内容，保持技术范儿"""
                },
                "academic": {
                    "name": "学术专业",
                    "description": "适用于学术讨论、研究交流、导师沟通",
                    "system_prompt": """你是学术研究者，请注意：
1. 语气严谨、客观，注重逻辑和证据
2. 讨论学术问题时要求准确，不确定的要用"可能"、"推测"等词汇
3. 可以使用专业术语，但也要保持沟通清晰
4. 对于学术观点要保持开放和谦虚的态度
5. 只输出回复内容，保持学术风范"""
                },
                "humorous": {
                    "name": "幽默搞笑",
                    "description": "适用于喜欢幽默、轻松氛围的场景",
                    "system_prompt": """你是幽默风趣的人，请注意：
1. 诙谐幽默但不失礼貌，适当开玩笑调节气氛
2. 可以用夸张、比喻、反讽等修辞手法
3. 幽默要适度，不开冒犯性的玩笑
4. 用轻松的方式回应，让对话充满乐趣
5. 只输出回复内容，保持幽默感"""
                },
                "concise": {
                    "name": "简洁高冷",
                    "description": "适用于少言寡语、直接高效的风格",
                    "system_prompt": """你是简洁干练的人，请注意：
1. 回复要极简，能用一个字不用两个字
2. 不说废话，不解释，不寒暄
3. 用最简短的语言回应，如"嗯"、"行"、"好"、"可以"
4. 保持高冷的语气，不表达过多情绪
5. 只输出回复内容，保持简洁"""
                },
                "literary": {
                    "name": "文艺青年",
                    "description": "适用于文艺交流、情感表达、文艺圈",
                    "system_prompt": """你是文艺青年，请注意：
1. 用词优雅、诗意，适当引用名言佳句
2. 语气温柔、感性，注重情感表达
3. 可以用比喻、象征等修辞手法
4. 关注生活的美好和情感的细腻
5. 只输出回复内容，保持文艺气息"""
                },
                "enthusiastic": {
                    "name": "热情开朗",
                    "description": "适用于热情活泼、积极向上的性格",
                    "system_prompt": """你是热情开朗的人，请注意：
1. 语气充满活力和正能量，积极向上
2. 多用感叹号和热情的表达，展现激情
3. 对事物保持乐观态度，传递正能量
4. 主动关心，用热情感染对方
5. 只输出回复内容，保持热情"""
                },
                "modest": {
                    "name": "谦虚低调",
                    "description": "适用于谦虚内敛、低调稳重的性格",
                    "system_prompt": """你是谦虚低调的人，请注意：
1. 语气谦和、低调，不张扬不夸耀
2. 多用"可能"、"也许"、"个人觉得"等谦辞
3. 对他人的赞美表示谦虚，不自夸
4. 保持平和稳重的态度
5. 只输出回复内容，保持谦逊"""
                },
                "leadership": {
                    "name": "领导权威",
                    "description": "适用于领导、管理者、上级沟通",
                    "system_prompt": """你是团队领导，请注意：
1. 语气自信、果断，展现领导力
2. 指令清晰明确，不做多余的解释
3. 可以用"好的"、"辛苦了"、"继续"等管理用语
4. 保持专业距离，不过分亲近但也不冷漠
5. 只输出回复内容，保持领导风范"""
                }
            }

            return {"status": "ok", "templates": templates}
        except Exception as e:
            return {"status": "error", "msg": f"获取模板失败: {str(e)}"}

    def _validate_persona_data(self, persona_data):
        """验证人设数据"""
        # 如果使用模板，则不需要 system_prompt
        using_template = 'persona_template' in persona_data and persona_data['persona_template']

        if 'name' not in persona_data or not persona_data['name']:
            return {'valid': False, 'message': '请输入人设名称'}

        if not using_template:
            if 'system_prompt' not in persona_data or not persona_data['system_prompt']:
                return {'valid': False, 'message': '请输入人设 Prompt'}

        # 可选字段
        if 'description' in persona_data and len(persona_data['description']) > 200:
            return {'valid': False, 'message': '人设描述不能超过200字'}

        if 'system_prompt' in persona_data and len(persona_data['system_prompt']) > 5000:
            return {'valid': False, 'message': '人设 Prompt 不能超过5000字'}

        return {'valid': True}

    # ============================================================
    # 人设模板管理 API (V1.1.1 新增)
    # ============================================================

    def get_persona_templates_list(self):
        """获取模板列表（内置模板 + 用户自定义模板）"""
        try:
            # 先获取内置模板
            builtin_result = self.get_persona_templates()
            builtin_templates = builtin_result.get("templates", {}) if builtin_result.get("status") == "ok" else {}

            # 读取用户自定义模板
            custom_templates = {}
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    personas = config.get("contacts_personas", {})
                    custom_templates = personas.get("templates", {})

            # 合并模板：用户自定义模板优先（可以覆盖内置模板）
            merged_templates = {**builtin_templates, **custom_templates}

            return {"status": "ok", "templates": merged_templates}
        except Exception as e:
            return {"status": "error", "msg": f"获取模板失败: {str(e)}"}

    def add_persona_template(self, template_id, template_data):
        """添加人设模板"""
        try:
            # 验证输入
            if 'name' not in template_data or not template_data['name']:
                return {"status": "error", "msg": "请输入模板名称"}

            if 'system_prompt' not in template_data or not template_data['system_prompt']:
                return {"status": "error", "msg": "请输入模板 Prompt"}

            # 读取现有配置
            if not os.path.exists(self.config_path):
                return {"status": "error", "msg": "配置文件不存在"}

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            # 初始化 contacts_personas 和 templates 段
            if 'contacts_personas' not in config:
                config['contacts_personas'] = {}
            if 'templates' not in config['contacts_personas']:
                config['contacts_personas']['templates'] = {}

            templates = config['contacts_personas']['templates']

            # 检查是否已存在
            if template_id in templates:
                return {"status": "error", "msg": f"模板 ID '{template_id}' 已存在"}

            # 添加模板
            templates[template_id] = template_data

            # 写回文件
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            return {"status": "ok", "msg": f"已添加模板 '{template_data.get('name', template_id)}'"}
        except Exception as e:
            return {"status": "error", "msg": f"添加模板失败: {str(e)}"}

    def update_persona_template(self, template_id, template_data):
        """更新人设模板"""
        try:
            # 验证输入
            if 'name' not in template_data or not template_data['name']:
                return {"status": "error", "msg": "请输入模板名称"}

            if 'system_prompt' not in template_data or not template_data['system_prompt']:
                return {"status": "error", "msg": "请输入模板 Prompt"}

            # 读取现有配置
            if not os.path.exists(self.config_path):
                return {"status": "error", "msg": "配置文件不存在"}

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            personas = config.get("contacts_personas", {})
            templates = personas.get("templates", {})

            # 检查是否存在
            if template_id not in templates:
                return {"status": "error", "msg": f"未找到模板 '{template_id}'"}

            # 更新模板
            templates[template_id] = template_data

            # 写回文件
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            return {"status": "ok", "msg": f"已更新模板 '{template_data.get('name', template_id)}'"}
        except Exception as e:
            return {"status": "error", "msg": f"更新模板失败: {str(e)}"}

    def delete_persona_template(self, template_id):
        """删除人设模板"""
        try:
            # 读取现有配置
            if not os.path.exists(self.config_path):
                return {"status": "error", "msg": "配置文件不存在"}

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            personas = config.get("contacts_personas", {})
            templates = personas.get("templates", {})

            # 检查是否存在
            if template_id not in templates:
                return {"status": "error", "msg": f"未找到模板 '{template_id}'"}

            # 删除模板
            del templates[template_id]

            # 写回文件
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            return {"status": "ok", "msg": f"已删除模板 '{template_id}'"}
        except Exception as e:
            return {"status": "error", "msg": f"删除模板失败: {str(e)}"}

if __name__ == "__main__":
    pwd = os.path.dirname(os.path.abspath(__file__))
    ui_path = os.path.join(pwd, "ui", "index.html")
    
    api = AppApi()
    
    # 创建无边框原生窗口（去掉 Windows 默认标题栏）
    window = webview.create_window(
        title="WeChat.AI 控制台",
        url=f"file://{ui_path}",
        js_api=api,
        width=1024,
        height=720,
        resizable=True,
        frameless=True,      # 去掉原生标题栏
        easy_drag=True        # 允许拖拽移动窗口
    )
    
    # 把 window 对象挂到 api 上，方便前端调用最小化/关闭
    api._window = window
    
    # 启动 pywebview（关闭 debug 防止 DevTools 弹窗）
    webview.start(debug=False)
