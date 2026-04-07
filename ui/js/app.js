let isRunning = false;
        let pollTimer = null;
        const logArea = document.getElementById('logArea');
        const btnLaunch = document.getElementById('btnLaunch');
        const statusLabel = document.getElementById('statusLabel');
        const statusDot = document.getElementById('statusDot');
        const appLogo = document.getElementById('appLogo');

        function switchTab(id, el) {
            document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.tab-item').forEach(t => t.classList.remove('active'));
            document.getElementById(id).classList.add('active');
            el.classList.add('active');

            // 切换到人设页面时重新加载人设配置
            if (id === 'panel-persona') {
                loadTemplates();
                loadContacts();
            }
        }

        function appendLog(raw) {
            let time = '', msg = raw;
            const m = raw.match(/^\[(.*?)\]\s(.*)/s);
            if (m) { time = m[1]; msg = m[2]; }

            const el = document.createElement('div');
            el.className = 'log-entry';

            // 判断类型 & 添加小图标
            let iconClass = 'info', iconText = 'i';
            if (msg.includes('🗣️') || msg.includes('回复')) { iconClass = 'reply'; iconText = '↩'; }
            else if (msg.includes('✅')) { iconClass = 'ok'; iconText = '✓'; }
            else if (msg.includes('🎯') || msg.includes('👤') || msg.includes('🔍')) { iconClass = 'find'; iconText = '!'; }
            else if (msg.includes('⚠️')) { iconClass = 'warn'; iconText = '⚠'; }
            else if (msg.includes('🟢') || msg.includes('[系统]') || msg.includes('最小化')) {
                el.className = 'log-entry type-system';
                el.textContent = msg;
                logArea.appendChild(el);
                if (logArea.children.length > 150) logArea.removeChild(logArea.firstElementChild);
                logArea.scrollTop = logArea.scrollHeight;
                return;
            }

            const icon = document.createElement('span');
            icon.className = 'log-icon ' + iconClass;
            icon.textContent = iconText;
            el.appendChild(icon);

            const txt = document.createTextNode((time ? time + ' ' : '') + msg);
            el.appendChild(txt);

            logArea.appendChild(el);
            if (logArea.children.length > 150) logArea.removeChild(logArea.firstElementChild);
            logArea.scrollTop = logArea.scrollHeight;
        }

        function clearLogs() {
            logArea.innerHTML = '';
            appendLog('[系统] 终端已清理');
        }

        function minimizeApp() {
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.minimize_app();
            }
        }

        function closeApp() {
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.close_app();
            }
        }

        function pollLogs() {
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.get_logs().then(logs => {
                    if (logs && logs.length) logs.forEach(m => appendLog(m));
                });
            }
        }

        function setUI(running) {
            isRunning = running;
            if (running) {
                statusLabel.textContent = '运行中';
                statusDot.classList.add('online');
                appLogo.classList.remove('idle');
                appLogo.classList.add('running');
                btnLaunch.className = 'btn-launch stop';
                btnLaunch.innerHTML = '<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2"/></svg> 停止';
            } else {
                statusLabel.textContent = '等待中';
                statusDot.classList.remove('online');
                appLogo.classList.remove('running');
                appLogo.classList.add('idle');
                btnLaunch.className = 'btn-launch start';
                btnLaunch.innerHTML = '<svg viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg> 启动';
            }
        }

        function toggleEngine() {
            if (!window.pywebview || !window.pywebview.api) return;
            if (!isRunning) {
                window.pywebview.api.start_engine().then(r => {
                    if (r.status === 'ok') {
                        setUI(true);
                        if (!pollTimer) pollTimer = setInterval(pollLogs, 400);
                    }
                });
            } else {
                window.pywebview.api.stop_engine().then(r => {
                    if (r.status === 'ok') setUI(false);
                });
            }
        }

        window.addEventListener('pywebviewready', () => {
            appendLog('[系统] 引擎核心已加载，所有模块待命中。');
            setInterval(pollLogs, 1000);
            // 加载配置
            loadConfig();
            // 加载模板（因为模板区域默认显示）
            loadTemplates();
            // 加载联系人配置
            loadContacts();
        });

        // ===== 配置管理函数 =====
        let currentConfig = null;
        let modelsList = [];
        let currentModel = null;
        let editingModelId = null;  // 当前正在编辑的模型ID，null表示添加新模式

        // 主流大模型预设配置
        const MODEL_PRESETS = {
            deepseek: {
                name: 'DeepSeek V3',
                model: 'deepseek-chat',
                base_url: 'https://api.deepseek.com/v1',
                hint: '获取方式：访问 https://platform.deepseek.com',
                key_prefix: 'sk-',
                icon: 'DS'
            },
            openai: {
                name: 'OpenAI GPT-4',
                model: 'gpt-4',
                base_url: 'https://api.openai.com/v1',
                hint: '获取方式：访问 https://platform.openai.com',
                key_prefix: 'sk-',
                icon: 'GPT'
            },
            gemini: {
                name: 'Google Gemini',
                model: 'gemini-pro',
                base_url: 'https://generativelanguage.googleapis.com/v1beta',
                hint: '获取方式：访问 https://ai.google.dev',
                key_prefix: '',
                icon: 'GM'
            },
            zhipu: {
                name: '智谱AI GLM-4',
                model: 'glm-4',
                base_url: 'https://open.bigmodel.cn/api/paas/v4',
                hint: '获取方式：访问 https://open.bigmodel.cn',
                key_prefix: '',
                icon: 'GLM'
            },
            moonshot: {
                name: 'Moonshot Kimi',
                model: 'moonshot-v1-8k',
                base_url: 'https://api.moonshot.cn/v1',
                hint: '获取方式：访问 https://platform.moonshot.cn',
                key_prefix: 'sk-',
                icon: 'MK'
            },
            custom: {
                name: '自定义配置',
                model: '',
                base_url: '',
                hint: '请手动填写 API Base URL 和模型名称',
                key_prefix: '',
                icon: 'API'
            }
        };

        function onModelProviderChange() {
            const provider = document.getElementById('modelProvider').value;
            const preset = MODEL_PRESETS[provider];

            // 清空 API Key（解决用户提出的问题）
            document.getElementById('apiKey').value = '';

            // 更新提示文字
            document.getElementById('apiKeyHint').textContent = preset.hint;

            // 更新当前配置显示
            if (provider !== 'custom') {
                document.getElementById('currentModelConfig').textContent =
                    `${preset.name} (${preset.model})`;
                // 隐藏自定义配置
                document.getElementById('customConfigGroup').style.display = 'none';
                document.getElementById('customModelGroup').style.display = 'none';
            } else {
                document.getElementById('currentModelConfig').textContent = '自定义配置';
                // 显示自定义配置
                document.getElementById('customConfigGroup').style.display = 'block';
                document.getElementById('customModelGroup').style.display = 'block';
            }
        }

        function loadConfig() {
            if (!window.pywebview || !window.pywebview.api) return;

            window.pywebview.api.read_config().then(result => {
                if (result.status === 'ok') {
                    currentConfig = result.config;
                    modelsList = result.models || [];
                    currentModel = result.current_model;

                    populateForm(result.config, result.env, result.is_calibrated);
                    updateCalibrationStatus(result.is_calibrated);
                    renderModelsList();
                    updateMonitorModelDisplay();
                    updateWorkModeDisplay();
                } else {
                    console.error('加载配置失败:', result.msg);
                }
            });
        }

        function populateForm(config, env, isCalibrated) {
            // 填充 OCR 配置
            const ocrThreshold = config.ocr?.confidence_threshold || 0.7;
            document.getElementById('ocrThreshold').value = ocrThreshold;
            document.getElementById('ocrValue').textContent = ocrThreshold;

            // 填充防风控配置
            const typoRate = config.anti_risk?.global_typo_rate || 0.02;
            const typoPercent = Math.round(typoRate * 100);
            document.getElementById('typoRate').value = typoPercent;
            document.getElementById('typoValue').textContent = typoPercent + '%';

            const sleepHours = config.anti_risk?.sleep_hours || '00:00-07:00';
            document.getElementById('sleepHours').value = sleepHours;
        }

        function updateCalibrationStatus(isCalibrated) {
            const icon = document.getElementById('calibIcon');
            const title = document.getElementById('calibTitle');
            const desc = document.getElementById('calibDesc');

            if (isCalibrated) {
                icon.className = 'status-icon ok';
                icon.textContent = '✓';
                title.textContent = '坐标已校准';
                desc.textContent = '窗口坐标配置已完成，可以正常使用';
            } else {
                icon.className = 'status-icon error';
                icon.textContent = '!';
                title.textContent = '坐标未校准';
                desc.textContent = '请先进行坐标校准，否则无法正常使用';
            }
        }

        // ===== 模型列表渲染 =====
        function renderModelsList() {
            const container = document.getElementById('modelsList');

            if (!modelsList || modelsList.length === 0) {
                container.innerHTML = `
                    <div class="empty-models">
                        <svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
                        <div class="empty-text">还没有配置任何模型</div>
                        <div class="empty-hint">点击上方"添加模型"按钮开始配置</div>
                    </div>
                `;
                return;
            }

            let html = '';
            modelsList.forEach(model => {
                const preset = MODEL_PRESETS[model.provider] || MODEL_PRESETS.custom;
                const isCurrent = currentModel && currentModel.id === model.id;

                html += `
                    <div class="model-item ${isCurrent ? 'current' : ''}">
                        <div class="model-icon">${preset.icon}</div>
                        <div class="model-info">
                            <div class="model-name">${escapeHtml(model.name)}</div>
                            <div class="model-provider">${preset.name}</div>
                        </div>
                        ${isCurrent ? '<div class="model-badge">当前</div>' : ''}
                        <div class="model-actions">
                            ${!isCurrent ? `
                                <button class="btn-icon-small" onclick="setCurrentModel('${escapeHtml(model.id)}')" title="设为当前">
                                    <svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>
                                </button>
                            ` : ''}
                            <button class="btn-icon-small" onclick="editModel('${escapeHtml(model.id)}')" title="编辑">
                                <svg viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                            </button>
                            <button class="btn-icon-small delete" onclick="deleteModel('${escapeHtml(model.id)}')" title="删除">
                                <svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                            </button>
                        </div>
                    </div>
                `;
            });

            container.innerHTML = html;
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // ===== 模型表单操作 =====
        function showAddModelForm() {
            editingModelId = null;
            document.getElementById('modelFormTitle').textContent = '添加新模型';
            document.getElementById('modelName').value = '';
            document.getElementById('modelId').value = '';
            document.getElementById('modelProvider').value = 'deepseek';
            document.getElementById('apiKey').value = '';
            document.getElementById('baseUrl').value = '';
            document.getElementById('model').value = '';
            document.getElementById('customConfigGroup').style.display = 'none';
            document.getElementById('customModelGroup').style.display = 'none';
            onModelProviderChange();

            document.getElementById('modelsList').style.display = 'none';
            document.getElementById('modelForm').style.display = 'block';
        }

        function hideModelForm() {
            document.getElementById('modelForm').style.display = 'none';
            document.getElementById('modelsList').style.display = 'block';
            editingModelId = null;
        }

        function editModel(modelId) {
            const model = modelsList.find(m => m.id === modelId);
            if (!model) return;

            editingModelId = modelId;
            document.getElementById('modelFormTitle').textContent = '编辑模型';
            document.getElementById('modelName').value = model.name;
            document.getElementById('modelId').value = model.id;
            document.getElementById('modelProvider').value = model.provider;
            document.getElementById('apiKey').value = model.api_key;
            document.getElementById('baseUrl').value = model.base_url;
            document.getElementById('model').value = model.model;

            const preset = MODEL_PRESETS[model.provider];
            if (model.provider === 'custom') {
                document.getElementById('customConfigGroup').style.display = 'block';
                document.getElementById('customModelGroup').style.display = 'block';
                document.getElementById('currentModelConfig').textContent = '自定义配置';
            } else {
                document.getElementById('customConfigGroup').style.display = 'none';
                document.getElementById('customModelGroup').style.display = 'none';
                document.getElementById('currentModelConfig').textContent =
                    `${preset.name} (${model.model})`;
            }

            document.getElementById('modelsList').style.display = 'none';
            document.getElementById('modelForm').style.display = 'block';
        }

        function saveModel() {
            if (!window.pywebview || !window.pywebview.api) return;

            // 收集表单数据
            const modelData = {
                name: document.getElementById('modelName').value.trim(),
                id: document.getElementById('modelId').value.trim(),
                provider: document.getElementById('modelProvider').value,
                api_key: document.getElementById('apiKey').value.trim(),
                base_url: document.getElementById('baseUrl').value.trim(),
                model: document.getElementById('model').value.trim()
            };

            // 根据提供商预设值
            const provider = modelData.provider;
            const preset = MODEL_PRESETS[provider];

            if (provider !== 'custom') {
                modelData.base_url = preset.base_url;
                modelData.model = preset.model;
            }

            // 验证
            if (!modelData.name) {
                showCustomAlert('请输入模型名称');
                return;
            }
            if (!modelData.id) {
                showCustomAlert('请输入模型 ID');
                return;
            }
            if (!modelData.api_key) {
                showCustomAlert('请输入 API Key');
                return;
            }

            // 调用后端 API
            if (editingModelId) {
                // 更新现有模型
                window.pywebview.api.update_model(editingModelId, modelData).then(result => {
                    if (result.status === 'ok') {
                        showCustomAlert('模型更新成功');
                        hideModelForm();
                        loadConfig(); // 重新加载配置
                    } else {
                        showCustomAlert('更新失败: ' + result.msg);
                    }
                });
            } else {
                // 添加新模型
                window.pywebview.api.add_model(modelData).then(result => {
                    if (result.status === 'ok') {
                        showCustomAlert('模型添加成功');
                        hideModelForm();
                        loadConfig(); // 重新加载配置
                    } else {
                        showCustomAlert('添加失败: ' + result.msg);
                    }
                });
            }
        }

        function deleteModel(modelId) {
            showConfirmDialog('确定要删除这个模型配置吗？此操作不可撤销。', () => {
                window.pywebview.api.delete_model(modelId).then(result => {
                    if (result.status === 'ok') {
                        showCustomAlert('模型已删除');
                        loadConfig(); // 重新加载配置
                    } else {
                        showCustomAlert('删除失败: ' + result.msg);
                    }
                });
            });
        }

        function setCurrentModel(modelId) {
            window.pywebview.api.set_current_model(modelId).then(result => {
                if (result.status === 'ok') {
                    showCustomAlert('已切换到该模型');
                    loadConfig(); // 重新加载配置
                    updateMonitorModelDisplay(); // 更新监控页面显示
                } else {
                    showCustomAlert('切换失败: ' + result.msg);
                }
            });
        }

        function updateMonitorModelDisplay() {
            // 更新监控页面的模型显示
            const modelChip = document.querySelector('.chip');
            const modelNameElement = document.getElementById('currentModelName');
            if (currentModel && modelNameElement) {
                modelNameElement.textContent = currentModel.name;
            }
        }

        function updateWorkModeDisplay() {
            // 更新监控页面的工作模式显示
            if (!window.pywebview || !window.pywebview.api) return;

            window.pywebview.api.get_work_mode().then(result => {
                if (result.status === 'ok') {
                    const modeToggle = document.getElementById('workModeToggle');
                    if (modeToggle) {
                        // 移除所有模式类
                        modeToggle.classList.remove('auto', 'assist');
                        // 添加当前模式类
                        modeToggle.classList.add(result.mode);
                    }
                }
            });
        }

        function toggleWorkMode() {
            if (!window.pywebview || !window.pywebview.api) return;

            // 先获取当前模式，然后切换到另一种模式
            window.pywebview.api.get_work_mode().then(result => {
                if (result.status === 'ok') {
                    const newMode = result.mode === 'auto' ? 'assist' : 'auto';

                    // 直接切换，不需要确认对话框
                    window.pywebview.api.set_work_mode(newMode).then(setResult => {
                        if (setResult.status === 'ok') {
                            // 更新显示
                            updateWorkModeDisplay();

                            // 输出提示信息到日志区域
                            const timestamp = new Date().toLocaleTimeString('zh-CN', { hour12: false });
                            if (newMode === 'assist') {
                                appendLog(`[${timestamp}] [模式切换] 已切换到辅助模式 - AI将生成回复内容并粘贴到输入框，等待您手动发送`);
                            } else {
                                appendLog(`[${timestamp}] [模式切换] 已切换到自动模式 - AI将自动识别并回复消息，期间请勿操作鼠标键盘`);
                            }
                        } else {
                            appendLog(`[${timestamp}] [错误] 切换失败: ${setResult.msg}`);
                        }
                    });
                }
            });
        }

        // ===== 模型选择器 =====
        function showModelSelector() {
            if (!modelsList || modelsList.length === 0) {
                showCustomAlert('请先在配置页面添加模型');
                return;
            }

            // 渲染模型列表
            const container = document.getElementById('modelSelectorList');
            let html = '';

            modelsList.forEach(model => {
                const preset = MODEL_PRESETS[model.provider] || MODEL_PRESETS.custom;
                const isSelected = currentModel && currentModel.id === model.id;

                html += `
                    <div class="model-selector-item ${isSelected ? 'selected' : ''}"
                         onclick="selectModelFromSelector('${escapeHtml(model.id)}')">
                        <div class="selector-icon">${preset.icon}</div>
                        <div class="selector-info">
                            <div class="selector-name">${escapeHtml(model.name)}</div>
                            <div class="selector-provider">${preset.name}</div>
                        </div>
                        ${isSelected ? '<div class="selector-badge">当前</div>' : ''}
                        <div class="selector-check">
                            ${isSelected ? '<svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>' : ''}
                        </div>
                    </div>
                `;
            });

            container.innerHTML = html;
            document.getElementById('modelSelectorModal').classList.add('active');
        }

        function closeModelSelector() {
            document.getElementById('modelSelectorModal').classList.remove('active');
        }

        function selectModelFromSelector(modelId) {
            // 如果点击的是当前模型，直接关闭
            if (currentModel && currentModel.id === modelId) {
                closeModelSelector();
                return;
            }

            // 切换模型
            setCurrentModel(modelId);
            closeModelSelector();
        }

        function updateOcrValue(value) {
            document.getElementById('ocrValue').textContent = value;
        }

        function updateTypoValue(value) {
            document.getElementById('typoValue').textContent = value + '%';
        }

        function togglePasswordVisibility(inputId) {
            const input = document.getElementById(inputId);
            if (input.type === 'password') {
                input.type = 'text';
            } else {
                input.type = 'password';
            }
        }

        function saveConfig() {
            if (!window.pywebview || !window.pywebview.api) return;

            // 收集配置数据（只保存OCR和防风控配置）
            const configData = {
                ocr: {
                    confidence_threshold: parseFloat(document.getElementById('ocrThreshold').value)
                },
                anti_risk: {
                    global_typo_rate: parseInt(document.getElementById('typoRate').value) / 100,
                    sleep_hours: document.getElementById('sleepHours').value.trim()
                }
            };

            // 保存配置
            window.pywebview.api.update_config(configData).then(result => {
                if (result.status === 'ok') {
                    showCustomAlert('配置已保存！');
                    loadConfig(); // 重新加载配置
                } else {
                    showCustomAlert('保存配置失败: ' + result.msg);
                }
            }).catch(error => {
                showCustomAlert('保存失败: ' + error.message);
            });
        }

        function resetConfig() {
            if (!confirm('确定要重置为默认配置吗？（模型配置不会被重置）')) return;

            // 只重置OCR和防风控配置
            document.getElementById('ocrThreshold').value = 0.7;
            document.getElementById('ocrValue').textContent = '0.7';
            document.getElementById('typoRate').value = 2;
            document.getElementById('typoValue').textContent = '2%';
            document.getElementById('sleepHours').value = '00:00-07:00';

            appendLog('[系统] 配置已重置为默认值，请点击保存按钮生效。');
        }

        function startCalibration() {
            if (!window.pywebview || !window.pywebview.api) return;

            const calibInstructions =
                '📋 坐标校准操作指南：\n\n' +
                '1. 请确保微信客户端已打开且窗口可见\n' +
                '2. 点击"确定"后，会依次弹出3个图片窗口\n' +
                '3. 按住鼠标左键拖动来画框，框选指定区域\n' +
                '4. 按回车键确认选择，按C键重置\n' +
                '5. 完成所有步骤后，校准自动保存\n\n' +
                '是否开始校准？';

            showConfirmDialog(calibInstructions, () => {
                // 切换到监控Tab，方便用户看到实时进度
                switchTab('panel-monitor', document.querySelector('.tab-item'));

                window.pywebview.api.start_calibration().then(result => {
                    if (result.status === 'ok') {
                        appendLog('[系统] 校准流程已启动，请查看日志窗口的详细指导...');
                    } else {
                        showCustomAlert('启动校准失败: ' + result.msg);
                    }
                });
            });
        }

        // ===== 自定义弹窗函数 =====
        function showCustomAlert(message, title = '提示') {
            document.getElementById('modalTitle').textContent = title;
            document.getElementById('modalMessage').textContent = message;
            document.getElementById('customModal').classList.add('active');
        }

        function showConfirmDialog(message, onConfirm) {
            const modal = document.getElementById('customModal');
            const modalMessage = document.getElementById('modalMessage');
            const modalButtons = document.querySelector('.modal-buttons');

            modalMessage.textContent = message;

            // 清空按钮并重新创建
            modalButtons.innerHTML = '';

            const cancelBtn = document.createElement('button');
            cancelBtn.className = 'modal-btn secondary';
            cancelBtn.textContent = '取消';
            cancelBtn.onclick = () => {
                modal.classList.remove('active');
                // 重置按钮
                setTimeout(() => {
                    modalButtons.innerHTML = '<button class="modal-btn primary" onclick="closeModal()">确定</button>';
                }, 200);
            };

            const confirmBtn = document.createElement('button');
            confirmBtn.className = 'modal-btn primary';
            confirmBtn.textContent = '确定';
            confirmBtn.onclick = () => {
                modal.classList.remove('active');
                onConfirm();
                // 重置按钮
                setTimeout(() => {
                    modalButtons.innerHTML = '<button class="modal-btn primary" onclick="closeModal()">确定</button>';
                }, 200);
            };

            modalButtons.appendChild(cancelBtn);
            modalButtons.appendChild(confirmBtn);
            modal.classList.add('active');
        }

        function closeModal() {
            document.getElementById('customModal').classList.remove('active');
        }

        // ============================================================
        // 联系人专属人设管理 (V1.1.1 更新：模板+联系人分离管理)
        // ============================================================

        let personasList = [];
        let personaTemplates = {};
        let editingTemplateId = null;  // 当前正在编辑的模板ID
        let editingContactName = null;  // 当前正在编辑的联系人

        // 模式切换
        function switchPersonaMode(mode) {
            const templatesBtn = document.getElementById('btnTemplatesTab');
            const contactsBtn = document.getElementById('btnContactsTab');
            const templatesArea = document.getElementById('personaTemplatesArea');
            const contactsArea = document.getElementById('personaContactsArea');

            if (mode === 'templates') {
                templatesBtn.className = 'btn-save';
                contactsBtn.className = 'btn-reset';
                templatesArea.style.display = 'block';
                contactsArea.style.display = 'none';
                loadTemplates();
            } else {
                templatesBtn.className = 'btn-reset';
                contactsBtn.className = 'btn-save';
                templatesArea.style.display = 'none';
                contactsArea.style.display = 'block';
                loadContacts();
            }
        }

        // 加载模板配置
        function loadTemplates() {
            console.log('loadTemplates() 被调用');
            if (!window.pywebview || !window.pywebview.api) {
                console.log('pywebview API 还未准备好，等待...');
                return;
            }

            console.log('开始调用 get_persona_templates_list API...');
            window.pywebview.api.get_persona_templates_list().then(result => {
                console.log('API 返回结果:', result);
                if (result.status === 'ok') {
                    personaTemplates = result.templates || {};
                    console.log('加载的模板:', Object.keys(personaTemplates));
                    renderTemplatesList();
                } else {
                    console.error('加载模板失败:', result.msg);
                    const container = document.getElementById('templatesList');
                    container.innerHTML = `<div style="padding: 20px; color: red; text-align: center;">加载失败: ${result.msg}</div>`;
                }
            }).catch(error => {
                console.error('API 调用异常:', error);
                const container = document.getElementById('templatesList');
                container.innerHTML = `<div style="padding: 20px; color: red; text-align: center;">API 调用异常: ${error}</div>`;
            });
        }

        // 渲染模板列表
        function renderTemplatesList() {
            const container = document.getElementById('templatesList');

            if (!personaTemplates || Object.keys(personaTemplates).length === 0) {
                container.innerHTML = `
                    <div class="empty-models">
                        <svg viewBox="0 0 24 24"><rect x="2" y="3" width="20" height="14" rx="2"/></svg>
                        <div class="empty-text">还没有配置任何人设模板</div>
                        <div class="empty-hint">模板可以被多个联系人引用，实现批量配置</div>
                    </div>
                `;
                return;
            }

            let html = '';
            Object.entries(personaTemplates).forEach(([templateId, template]) => {
                html += `
                    <div class="model-item">
                        <div class="model-icon" style="background: var(--accent-purple);">
                            ${templateId.charAt(0).toUpperCase()}
                        </div>
                        <div class="model-info">
                            <div class="model-name">${escapeHtml(template.name || templateId)}</div>
                            <div class="model-provider">${escapeHtml(template.description || '无描述')}</div>
                        </div>
                        <div class="model-actions">
                            <button class="btn-icon-small" onclick="editTemplate('${escapeHtml(templateId)}')" title="编辑">
                                <svg viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                            </button>
                            <button class="btn-icon-small delete" onclick="deleteTemplate('${escapeHtml(templateId)}')" title="删除">
                                <svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                            </button>
                        </div>
                    </div>
                `;
            });

            container.innerHTML = html;
        }

        // 加载联系人配置
        function loadContacts() {
            if (!window.pywebview || !window.pywebview.api) return;

            window.pywebview.api.get_contact_personas().then(result => {
                if (result.status === 'ok') {
                    personasList = result.personas || {};
                    renderContactsList();
                    updateDefaultPersonaDisplay();
                } else {
                    console.error('加载联系人配置失败:', result.msg);
                }
            });
        }

        // 渲染联系人列表
        function renderContactsList() {
            const container = document.getElementById('contactsList');

            // 过滤出真正的联系人配置（排除 default 和 templates）
            const contacts = Object.entries(personasList).filter(([key]) =>
                key !== 'default' && key !== 'templates'
            );

            if (contacts.length === 0) {
                container.innerHTML = `
                    <div class="empty-models">
                        <svg viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/></svg>
                        <div class="empty-text">还没有配置任何联系人</div>
                        <div class="empty-hint">添加联系人并选择模板或自定义人设</div>
                    </div>
                `;
                return;
            }

            let html = '';
            contacts.forEach(([contactName, contact]) => {
                const isEnabled = contact.enabled !== false;
                const usesTemplate = contact.persona_template;
                const templateId = usesTemplate || null;
                const template = templateId ? (personaTemplates[templateId] || {}) : {};

                let aliasesText = '';
                if (contact.aliases) {
                    const aliasesArr = Array.isArray(contact.aliases) ? contact.aliases : typeof contact.aliases === 'string' ? contact.aliases.split(',').map(s=>s.trim()) : [];
                    const aliasesStr = aliasesArr.length > 0 ? aliasesArr.join(', ') : contact.aliases;
                    aliasesText = `<div style="font-size: 11px; color: var(--text-muted); margin-top: 2px; text-overflow: ellipsis; overflow: hidden; white-space: nowrap; max-width: 180px;" title="${escapeHtml(aliasesStr)}">👥 别名: ${escapeHtml(aliasesStr)}</div>`;
                }

                html += `
                    <div class="model-item ${!isEnabled ? 'disabled' : ''}">
                        <div class="model-icon" style="background: ${isEnabled ? 'var(--accent-blue)' : 'var(--text-muted)'};">
                            ${contactName.charAt(0).toUpperCase()}
                        </div>
                        <div class="model-info" style="flex: 1; min-width: 0;">
                            <div class="model-name">${escapeHtml(contactName)}</div>
                            <div class="model-provider">
                                ${usesTemplate ?
                                    `<span style="color: var(--accent-purple);">📋 ${escapeHtml(template.name || templateId)}</span>` :
                                    `<span>${escapeHtml(contact.name || '自定义')}</span>`
                                }
                            </div>
                            ${aliasesText}
                        </div>
                        <div class="model-actions">
                            <button class="btn-icon-small" onclick="copyContact('${escapeHtml(contactName)}')" title="复制配置到新联系人">
                                <svg viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                            </button>
                            <button class="btn-icon-small" onclick="editContact('${escapeHtml(contactName)}')" title="编辑">
                                <svg viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                            </button>
                            <button class="btn-icon-small delete" onclick="deleteContact('${escapeHtml(contactName)}')" title="删除">
                                <svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                            </button>
                        </div>
                    </div>
                `;
            });

            container.innerHTML = html;
        }

        // 更新默认人设显示
        function updateDefaultPersonaDisplay() {
            const defaultPersona = personasList['default'] || {};
            const descEl = document.getElementById('defaultPersonaDesc');
            descEl.textContent = defaultPersona.description || '适用于所有未配置特定人设的联系人';
        }

        // ===== 模板管理功能 =====

        function showAddTemplateForm() {
            editingTemplateId = null;
            document.getElementById('templateFormTitle').textContent = '添加新模板';
            document.getElementById('templateId').value = '';
            document.getElementById('templateId').disabled = false;
            document.getElementById('templateName').value = '';
            document.getElementById('templateDescription').value = '';
            document.getElementById('templatePrompt').value = '';
            updateTemplateCharCount();

            document.getElementById('templatesList').style.display = 'none';
            document.getElementById('templateForm').style.display = 'block';
        }

        function editTemplate(templateId) {
            const template = personaTemplates[templateId];
            if (!template) return;

            editingTemplateId = templateId;
            document.getElementById('templateFormTitle').textContent = '编辑模板';
            document.getElementById('templateId').value = templateId;
            document.getElementById('templateId').disabled = true;
            document.getElementById('templateName').value = template.name || '';
            document.getElementById('templateDescription').value = template.description || '';
            document.getElementById('templatePrompt').value = template.system_prompt || '';
            updateTemplateCharCount();

            document.getElementById('templatesList').style.display = 'none';
            document.getElementById('templateForm').style.display = 'block';
        }

        function hideTemplateForm() {
            document.getElementById('templateForm').style.display = 'none';
            document.getElementById('templatesList').style.display = 'block';
            editingTemplateId = null;
        }

        function saveTemplate() {
            if (!window.pywebview || !window.pywebview.api) return;

            const templateId = document.getElementById('templateId').value.trim();
            const templateData = {
                name: document.getElementById('templateName').value.trim(),
                description: document.getElementById('templateDescription').value.trim(),
                system_prompt: document.getElementById('templatePrompt').value.trim()
            };

            if (!templateId) {
                showCustomAlert('请输入模板ID');
                return;
            }

            if (!templateData.name) {
                showCustomAlert('请输入模板名称');
                return;
            }

            if (!templateData.system_prompt) {
                showCustomAlert('请输入 System Prompt');
                return;
            }

            if (editingTemplateId) {
                // 更新模板
                window.pywebview.api.update_persona_template(templateId, templateData).then(result => {
                    if (result.status === 'ok') {
                        showCustomAlert('模板更新成功');
                        hideTemplateForm();
                        loadTemplates(); // 重新加载
                    } else {
                        showCustomAlert('更新失败: ' + result.msg);
                    }
                });
            } else {
                // 添加新模板
                window.pywebview.api.add_persona_template(templateId, templateData).then(result => {
                    if (result.status === 'ok') {
                        showCustomAlert('模板添加成功');
                        hideTemplateForm();
                        loadTemplates(); // 重新加载
                    } else {
                        showCustomAlert('添加失败: ' + result.msg);
                    }
                });
            }
        }

        function deleteTemplate(templateId) {
            showConfirmDialog(`确定要删除模板 '${templateId}' 吗？使用该模板的联系人将自动切换到默认人设。`, () => {
                window.pywebview.api.delete_persona_template(templateId).then(result => {
                    if (result.status === 'ok') {
                        showCustomAlert('模板已删除');
                        loadTemplates();
                        loadContacts(); // 更新联系人显示
                    } else {
                        showCustomAlert('删除失败: ' + result.msg);
                    }
                });
            });
        }

        function updateTemplateCharCount() {
            const prompt = document.getElementById('templatePrompt').value;
            const count = prompt.length;
            const countEl = document.getElementById('templateCharCount');
            countEl.textContent = `${count} / 5000 字符`;

            if (count > 5000) {
                countEl.style.color = 'var(--accent-red)';
            } else if (count > 4000) {
                countEl.style.color = 'var(--accent-orange)';
            } else {
                countEl.style.color = 'var(--text-muted)';
            }
        }

        // ===== 联系人配置功能 =====

        function showAddContactForm() {
            editingContactName = null;
            document.getElementById('contactFormTitle').textContent = '添加新联系人';
            document.getElementById('contactName').value = '';
            document.getElementById('contactName').disabled = false;
            document.getElementById('contactAliases').value = '';
            document.querySelector('input[name="personaMode"][value="template"]').checked = true;
            onContactModeChange();

            document.getElementById('contactsList').style.display = 'none';
            document.getElementById('contactForm').style.display = 'block';
        }

        function editContact(contactName) {
            const contact = personasList[contactName];
            if (!contact) return;

            editingContactName = contactName;
            document.getElementById('contactFormTitle').textContent = '编辑联系人';
            document.getElementById('contactName').value = contactName;
            document.getElementById('contactName').disabled = true;

            let aliases = contact.aliases || '';
            if (Array.isArray(aliases)) {
                aliases = aliases.join(', ');
            }
            document.getElementById('contactAliases').value = aliases;

            // 根据配置方式设置界面
            const usesTemplate = 'persona_template' in contact;
            if (usesTemplate) {
                document.querySelector('input[name="personaMode"][value="template"]').checked = true;
                document.getElementById('contactTemplateSelect').value = contact.persona_template || '';
                onContactTemplateChange();
            } else {
                document.querySelector('input[name="personaMode"][value="custom"]').checked = true;
                document.getElementById('contactPersonaName').value = contact.name || '';
                document.getElementById('contactDescription').value = contact.description || '';
                document.getElementById('contactPrompt').value = contact.system_prompt || '';
                updateContactCharCount();
            }

            document.querySelector(`input[name="contactEnabled"][value="${contact.enabled !== false ? 'true' : 'false'}"]`).checked = true;

            document.getElementById('contactsList').style.display = 'none';
            document.getElementById('contactForm').style.display = 'block';
        }

        function hideContactForm() {
            document.getElementById('contactForm').style.display = 'none';
            document.getElementById('contactsList').style.display = 'block';
            editingContactName = null;
        }

        function onContactModeChange() {
            const mode = document.querySelector('input[name="personaMode"]:checked').value;
            const templateMode = document.getElementById('contactTemplateMode');
            const customMode = document.getElementById('contactCustomMode');

            if (mode === 'template') {
                templateMode.style.display = 'block';
                customMode.style.display = 'none';
                // 加载模板选项
                loadTemplateOptions();
            } else {
                templateMode.style.display = 'none';
                customMode.style.display = 'block';
            }
        }

        function loadTemplateOptions() {
            const select = document.getElementById('contactTemplateSelect');
            select.innerHTML = '<option value="">-- 请选择模板 --</option>';

            Object.entries(personaTemplates).forEach(([templateId, template]) => {
                const option = document.createElement('option');
                option.value = templateId;
                option.textContent = `${template.name || templateId} - ${template.description || '无描述'}`;
                select.appendChild(option);
            });
        }

        function onContactTemplateChange() {
            const templateId = document.getElementById('contactTemplateSelect').value;
            const descEl = document.getElementById('selectedTemplateDesc');

            if (templateId && personaTemplates[templateId]) {
                const template = personaTemplates[templateId];
                descEl.textContent = template.description || '选择一个模板后，该联系人将使用模板的人设配置';
            } else {
                descEl.textContent = '选择一个模板后，该联系人将使用模板的人设配置';
            }
        }

        function saveContact() {
            if (!window.pywebview || !window.pywebview.api) return;

            const contactName = document.getElementById('contactName').value.trim();
            const contactAliases = document.getElementById('contactAliases').value.trim();
            const mode = document.querySelector('input[name="personaMode"]:checked').value;
            const isEnabled = document.querySelector('input[name="contactEnabled"]:checked').value === 'true';

            let contactData = {
                enabled: isEnabled
            };

            if (contactAliases) {
                // 将逗号分隔的字符串存入
                contactData.aliases = contactAliases.split(',').map(s => s.trim()).filter(s => s);
            } else {
                // 如果为空，明确清空 aliases 字段
                contactData.aliases = [];
            }

            if (mode === 'template') {
                // 引用模板模式：name字段使用联系人名称
                contactData.name = contactName;
                const templateId = document.getElementById('contactTemplateSelect').value;
                if (!templateId) {
                    showCustomAlert('请选择一个模板');
                    return;
                }
                contactData.persona_template = templateId;
            } else {
                // 自定义人设模式：name字段使用人设名称
                const personaName = document.getElementById('contactPersonaName').value.trim();
                if (!personaName) {
                    showCustomAlert('请输入人设名称');
                    return;
                }
                contactData.name = personaName;
                contactData.description = document.getElementById('contactDescription').value.trim();
                contactData.system_prompt = document.getElementById('contactPrompt').value.trim();
            }

            // 验证
            if (!contactName) {
                showCustomAlert('请输入联系人名称');
                return;
            }

            if (mode === 'custom' && !contactData.system_prompt) {
                showCustomAlert('请输入 System Prompt');
                return;
            }

            // 调用后端 API
            if (editingContactName) {
                // 编辑模式：使用原始联系人名称作为key
                window.pywebview.api.update_contact_persona(editingContactName, contactData).then(result => {
                    if (result.status === 'ok') {
                        showCustomAlert('联系人配置更新成功');
                        hideContactForm();
                        loadContacts(); // 重新加载
                    } else {
                        showCustomAlert('更新失败: ' + result.msg);
                    }
                });
            } else {
                // 添加模式：使用新的联系人名称作为key
                window.pywebview.api.add_contact_persona(contactName, contactData).then(result => {
                    if (result.status === 'ok') {
                        showCustomAlert('联系人配置添加成功');
                        hideContactForm();
                        loadContacts(); // 重新加载
                    } else {
                        showCustomAlert('添加失败: ' + result.msg);
                    }
                });
            }
        }

        function deleteContact(contactName) {
            showConfirmDialog(`确定要删除联系人 '${contactName}' 的配置吗？`, () => {
                window.pywebview.api.delete_contact_persona(contactName).then(result => {
                    if (result.status === 'ok') {
                        showCustomAlert('联系人配置已删除');
                        loadContacts();
                    } else {
                        showCustomAlert('删除失败: ' + result.msg);
                    }
                });
            });
        }

        function copyContact(sourceContactName) {
            // 显示一个简单的输入对话框
            const newContactName = prompt(`请输入新联系人名称，将复制 '${sourceContactName}' 的配置：`);
            if (!newContactName || !newContactName.trim()) {
                return; // 用户取消或输入为空
            }

            const trimmedName = newContactName.trim();

            // 检查是否与源联系人名称相同
            if (trimmedName === sourceContactName) {
                showCustomAlert('新联系人名称不能与源联系人相同');
                return;
            }

            // 获取源联系人配置
            const sourceContact = personasList[sourceContactName];
            if (!sourceContact) {
                showCustomAlert('源联系人配置不存在');
                return;
            }

            // 准备新的配置数据（深拷贝）
            const newContactData = JSON.parse(JSON.stringify(sourceContact));

            // 调用后端API添加新联系人
            window.pywebview.api.add_contact_persona(trimmedName, newContactData).then(result => {
                if (result.status === 'ok') {
                    showCustomAlert(`已将 '${sourceContactName}' 的配置复制到 '${trimmedName}'`);
                    loadContacts(); // 重新加载列表
                } else {
                    showCustomAlert('复制失败: ' + result.msg);
                }
            });
        }

        function updateContactCharCount() {
            const prompt = document.getElementById('contactPrompt').value;
            const count = prompt.length;
            const countEl = document.getElementById('contactCharCount');
            countEl.textContent = `${count} / 5000 字符`;

            if (count > 5000) {
                countEl.style.color = 'var(--accent-red)';
            } else if (count > 4000) {
                countEl.style.color = 'var(--accent-orange)';
            } else {
                countEl.style.color = 'var(--text-muted)';
            }
        }

        // 默认人设编辑
        function showDefaultPersonaForm() {
            const defaultPersona = personasList['default'] || {};

            editingContactName = 'default';
            document.getElementById('contactFormTitle').textContent = '编辑默认人设';
            document.getElementById('contactName').value = 'default';
            document.getElementById('contactName').disabled = true;
            document.querySelector('input[name="personaMode"][value="custom"]').checked = true;
            onContactModeChange();

            document.getElementById('contactPersonaName').value = defaultPersona.name || '默认人设';
            document.getElementById('contactDescription').value = defaultPersona.description || '';
            document.getElementById('contactPrompt').value = defaultPersona.system_prompt || '';
            updateContactCharCount();

            document.getElementById('contactsList').style.display = 'none';
            document.getElementById('contactForm').style.display = 'block';
        }

        // 监听输入变化
        document.addEventListener('DOMContentLoaded', function() {
            const templatePrompt = document.getElementById('templatePrompt');
            const contactPrompt = document.getElementById('contactPrompt');
            if (templatePrompt) {
                templatePrompt.addEventListener('input', updateTemplateCharCount);
            }
            if (contactPrompt) {
                contactPrompt.addEventListener('input', updateContactCharCount);
            }
        });