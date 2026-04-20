"""
记忆管理模块 (Memory Manager)
P2 阶段：记忆流与上下文摘要引擎
使用 SQLite 实现轻量级本地聊天记录存储，支持历史上下文检索和隐私保护
"""

import sqlite3
import os
import base64
import logging
import json
from datetime import datetime
from typing import List, Dict, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class MemoryManager:
    """
    记忆管理器：负责存储和检索聊天历史记录
    - 使用 SQLite 本地数据库存储
    - 支持按联系人维度管理上下文
    - 实现滑动窗口机制自动清理旧记录
    - 提供基础混淆保护隐私
    """

    def __init__(self, db_path: str = "data/memory.db", enable_encryption: bool = True):
        """
        初始化记忆管理器
        :param db_path: 数据库文件路径
        :param enable_encryption: 是否启用内容混淆（base64）
        """
        self.db_path = db_path
        self.enable_encryption = enable_encryption
        self.max_records_per_contact = 100  # 滑动窗口：每个联系人最多保留 100 条记录

        # 确保 data 目录存在
        self._ensure_data_directory()

        # 初始化数据库表结构
        self._initialize_database()

        logging.info(f"💾 记忆管理器已初始化：{self.db_path} (混淆: {self.enable_encryption})")

    def _ensure_data_directory(self):
        """确保数据目录存在"""
        data_dir = os.path.dirname(self.db_path)
        if data_dir and not os.path.exists(data_dir):
            try:
                os.makedirs(data_dir, exist_ok=True)
                logging.info(f"💾 记忆管理器：创建数据目录 {data_dir}")
            except Exception as e:
                logging.error(f"❌ 记忆管理器：创建数据目录失败 - {e}")

    def _initialize_database(self):
        """初始化数据库表结构"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # 创建消息表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        contact_name TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        created_at INTEGER DEFAULT (strftime('%s', 'now'))
                    )
                ''')

                # 创建索引：按联系人和时间查询优化
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_contact_timestamp
                    ON messages (contact_name, created_at DESC)
                ''')

                conn.commit()
                logging.debug("💾 记忆管理器：数据库表结构初始化完成")

        except sqlite3.Error as e:
            logging.error(f"❌ 记忆管理器：数据库初始化失败 - {e}")
            raise

    def _encrypt_content(self, content: str) -> str:
        """
        内容混淆（基础保护）
        使用 base64 编码简单混淆，防止明文存储
        :param content: 原始内容
        :return: 混淆后的内容
        """
        if not self.enable_encryption:
            return content

        try:
            # 转换为字节并 base64 编码
            content_bytes = content.encode('utf-8')
            encrypted_bytes = base64.b64encode(content_bytes)
            return encrypted_bytes.decode('utf-8')
        except Exception as e:
            logging.warning(f"⚠️ 记忆管理器：内容混淆失败，使用明文存储 - {e}")
            return content

    def _decrypt_content(self, encrypted_content: str) -> str:
        """
        内容解混淆
        :param encrypted_content: 混淆后的内容
        :return: 原始内容
        """
        if not self.enable_encryption:
            return encrypted_content

        try:
            # base64 解码
            encrypted_bytes = encrypted_content.encode('utf-8')
            decrypted_bytes = base64.b64decode(encrypted_bytes)
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            logging.warning(f"⚠️ 记忆管理器：内容解混淆失败，返回原始内容 - {e}")
            return encrypted_content

    def add_message(self, contact_name: str, role: str, content: str) -> bool:
        """
        添加新的聊天记录
        :param contact_name: 联系人名字
        :param role: 角色（"user" 表示对方，"assistant" 表示 AI）
        :param content: 消息内容
        :return: 是否成功添加
        """
        if not contact_name or not content:
            logging.warning("⚠️ 记忆管理器：联系人名字或内容为空，跳过存储")
            return False

        if role not in ["user", "assistant"]:
            logging.warning(f"⚠️ 记忆管理器：无效的角色类型 '{role}'，跳过存储")
            return False

        try:
            # 内容混淆
            encrypted_content = self._encrypt_content(content)

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # 插入新记录
                cursor.execute('''
                    INSERT INTO messages (contact_name, role, content, timestamp)
                    VALUES (?, ?, ?, ?)
                ''', (contact_name, role, encrypted_content, datetime.now()))

                conn.commit()

                # 检查并执行滑动窗口清理
                self._cleanup_old_records(cursor, contact_name)

                conn.commit()
                logging.debug(f"💾 记忆管理器：已保存 {contact_name} 的 {role} 消息")
                return True

        except sqlite3.Error as e:
            logging.error(f"❌ 记忆管理器：添加消息失败 - {e}")
            return False

    def _cleanup_old_records(self, cursor, contact_name: str):
        """
        滑动窗口机制：清理最旧的记录
        :param cursor: 数据库游标
        :param contact_name: 联系人名字
        """
        try:
            # 查询当前记录数
            cursor.execute('''
                SELECT COUNT(*) FROM messages WHERE contact_name = ?
            ''', (contact_name,))

            count = cursor.fetchone()[0]

            if count > self.max_records_per_contact:
                # 计算需要删除的数量
                delete_count = count - self.max_records_per_contact

                # 删除最旧的记录（按 created_at 升序，保留最新的）
                cursor.execute('''
                    DELETE FROM messages
                    WHERE id IN (
                        SELECT id FROM messages
                        WHERE contact_name = ?
                        ORDER BY created_at ASC
                        LIMIT ?
                    )
                ''', (contact_name, delete_count))

                deleted_count = cursor.rowcount
                logging.info(f"🗑️ 记忆管理器：滑动窗口清理，删除 {contact_name} 的 {deleted_count} 条旧记录")

        except sqlite3.Error as e:
            logging.error(f"❌ 记忆管理器：清理旧记录失败 - {e}")

    def get_context(self, contact_name: str, limit: int = 20) -> List[Dict]:
        """
        获取指定联系人的最近上下文记录
        :param contact_name: 联系人名字
        :param limit: 获取的记录数量（默认 20 条）
        :return: 按时间正序排列的消息记录列表，格式为 LLM 接受的 dict 列表
        """
        if not contact_name:
            logging.warning("⚠️ 记忆管理器：联系人名字为空，返回空上下文")
            return []

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row  # 支持字典访问
                cursor = conn.cursor()

                # 查询最近的记录（按时间倒序）
                cursor.execute('''
                    SELECT role, content, timestamp
                    FROM messages
                    WHERE contact_name = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (contact_name, limit))

                rows = cursor.fetchall()

                # 解混淆并转换为 LLM 格式
                context = []
                for row in reversed(rows):  # 反转为时间正序
                    try:
                        decrypted_content = self._decrypt_content(row['content'])
                        context.append({
                            "role": row['role'],
                            "content": decrypted_content
                        })
                    except Exception as e:
                        logging.warning(f"⚠️ 记忆管理器：解密消息失败，跳过该条记录 - {e}")
                        continue

                logging.debug(f"💾 记忆管理器：获取 {contact_name} 的 {len(context)} 条历史记录")
                return context

        except sqlite3.Error as e:
            logging.error(f"❌ 记忆管理器：获取上下文失败 - {e}")
            return []

    def get_stats(self) -> Dict:
        """
        获取数据库统计信息
        :return: 统计信息字典
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # 总消息数
                cursor.execute('SELECT COUNT(*) FROM messages')
                total_messages = cursor.fetchone()[0]

                # 联系人数量
                cursor.execute('SELECT COUNT(DISTINCT contact_name) FROM messages')
                total_contacts = cursor.fetchone()[0]

                # 按联系人统计消息数
                cursor.execute('''
                    SELECT contact_name, COUNT(*) as count
                    FROM messages
                    GROUP BY contact_name
                    ORDER BY count DESC
                ''')
                contact_stats = {row[0]: row[1] for row in cursor.fetchall()}

                # 数据库文件大小
                db_size = 0
                if os.path.exists(self.db_path):
                    db_size = os.path.getsize(self.db_path)

                return {
                    "total_messages": total_messages,
                    "total_contacts": total_contacts,
                    "contact_stats": contact_stats,
                    "db_size_bytes": db_size,
                    "db_path": self.db_path
                }

        except sqlite3.Error as e:
            logging.error(f"❌ 记忆管理器：获取统计信息失败 - {e}")
            return {}

    def clear_contact_memory(self, contact_name: str) -> bool:
        """
        清空指定联系人的所有记录
        :param contact_name: 联系人名字
        :return: 是否成功清空
        """
        if not contact_name:
            return False

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM messages WHERE contact_name = ?', (contact_name,))
                deleted_count = cursor.rowcount
                conn.commit()

                logging.info(f"🗑️ 记忆管理器：已清空 {contact_name} 的 {deleted_count} 条记录")
                return True

        except sqlite3.Error as e:
            logging.error(f"❌ 记忆管理器：清空联系人记录失败 - {e}")
            return False

    def export_memory(self, contact_name: Optional[str] = None) -> Optional[str]:
        """
        导出记忆数据为 JSON 格式
        :param contact_name: 联系人名字（为空时导出所有）
        :return: JSON 字符串
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                if contact_name:
                    cursor.execute('''
                        SELECT contact_name, role, content, timestamp
                        FROM messages
                        WHERE contact_name = ?
                        ORDER BY created_at ASC
                    ''', (contact_name,))
                else:
                    cursor.execute('''
                        SELECT contact_name, role, content, timestamp
                        FROM messages
                        ORDER BY contact_name, created_at ASC
                    ''')

                rows = cursor.fetchall()

                # 解混淆并导出
                export_data = []
                for row in rows:
                    try:
                        decrypted_content = self._decrypt_content(row['content'])
                        export_data.append({
                            "contact_name": row['contact_name'],
                            "role": row['role'],
                            "content": decrypted_content,
                            "timestamp": row['timestamp']
                        })
                    except Exception as e:
                        logging.warning(f"⚠️ 记忆管理器：导出时解密失败，跳过该条记录 - {e}")
                        continue

                return json.dumps(export_data, ensure_ascii=False, indent=2)

        except sqlite3.Error as e:
            logging.error(f"❌ 记忆管理器：导出记忆数据失败 - {e}")
            return None


if __name__ == "__main__":
    # 测试记忆管理器功能
    import time
    import sys

    # 设置 Windows 终端兼容
    if sys.platform == 'win32':
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())

    print("记忆管理器功能测试")
    print("=" * 50)

    # 创建测试实例
    memory = MemoryManager("test_memory.db", enable_encryption=True)

    # 测试添加消息
    print("\n[1] 测试添加消息...")
    memory.add_message("张三", "user", "你好，在吗？")
    memory.add_message("张三", "assistant", "在的，有什么事吗？")
    memory.add_message("张三", "user", "晚上有空一起吃饭吗？")
    memory.add_message("李四", "user", "明天开会记得准时到")
    memory.add_message("李四", "assistant", "好的，收到")

    # 测试获取上下文
    print("\n[2] 测试获取上下文...")
    context = memory.get_context("张三", limit=10)
    print(f"张三的上下文记录（{len(context)} 条）：")
    for msg in context:
        print(f"  [{msg['role']}]: {msg['content']}")

    # 测试统计信息
    print("\n[3] 测试统计信息...")
    stats = memory.get_stats()
    print(f"总消息数：{stats['total_messages']}")
    print(f"联系人数量：{stats['total_contacts']}")
    print(f"各联系人消息数：{stats['contact_stats']}")

    # 测试导出
    print("\n[4] 测试导出功能...")
    export_json = memory.export_memory("张三")
    if export_json:
        print("张三的记忆数据（JSON）：")
        print(export_json[:200] + "...")

    # 测试滑动窗口（添加超过 100 条记录）
    print("\n[5] 测试滑动窗口机制...")
    print(f"向王五的记录中添加 105 条消息...")
    for i in range(105):
        memory.add_message("王五", "user", f"测试消息 {i + 1}")

    # 检查王五的记录数
    context_wangwu = memory.get_context("王五", limit=200)
    print(f"王五的实际记录数：{len(context_wangwu)}（应该保持在 100 条以内）")

    # 清理测试文件
    print("\n[6] 清理测试文件...")
    try:
        os.remove("test_memory.db")
        print("测试数据库文件已删除")
    except Exception as e:
        print(f"删除测试文件失败：{e}")

    print("\n记忆管理器功能测试完成！")
