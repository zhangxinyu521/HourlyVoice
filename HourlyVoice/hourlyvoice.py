#!/usr/bin/env python3
# encoding:utf-8

import json
import requests
import os
import time
import random
import re
import datetime
import threading
import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from common.tmp_dir import TmpDir
from plugins import *

@plugins.register(
    name="HourlyVoice",
    desire_priority=10,
    desc="整点报时语音插件：发送'整点报时'或'报时 [小时]'，机器人将发送整点报时语音和文字",
    version="1.1",
    author="AI Assistant",
)
class HourlyVoice(Plugin):
    def __init__(self):
        super().__init__()
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        self.config_file = os.path.join(os.path.dirname(__file__), "hourlyvoice_config.json")
        self.config = self.load_config()
        self.temp_files = []  # 用于跟踪临时文件
        self.auto_report_thread = None
        self.stop_thread = False
        
        # 启动自动报时线程（如果已启用）
        if self.config.get("auto_report", {}).get("enabled", False):
            self.start_auto_report_thread()
        
        logger.info("[HourlyVoice] 插件已初始化")

    def load_config(self):
        """
        加载配置文件
        :return: 配置字典
        """
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    logger.info(f"[HourlyVoice] 成功加载配置文件")
                    return config
            else:
                # 创建默认配置
                default_config = {
                    "api": {
                        "url": "https://xiaoapi.cn/API/zs_zdbs.php"
                    },
                    "auto_report": {
                        "enabled": False,
                        "channels": []
                    }
                }
                with open(self.config_file, "w", encoding="utf-8") as f:
                    json.dump(default_config, f, indent=4)
                logger.info(f"[HourlyVoice] 已创建默认配置文件")
                return default_config
        except Exception as e:
            logger.error(f"[HourlyVoice] 加载配置文件失败: {e}")
            return {
                "api": {
                    "url": "https://xiaoapi.cn/API/zs_zdbs.php"
                },
                "auto_report": {
                    "enabled": False,
                    "channels": []
                }
            }
    
    def save_config(self):
        """
        保存配置到文件
        """
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
            logger.info(f"[HourlyVoice] 配置已保存")
            return True
        except Exception as e:
            logger.error(f"[HourlyVoice] 保存配置失败: {e}")
            return False
            
    def start_auto_report_thread(self):
        """
        启动自动报时线程
        """
        if self.auto_report_thread is not None and self.auto_report_thread.is_alive():
            logger.info("[HourlyVoice] 自动报时线程已在运行中")
            return
        
        self.stop_thread = False
        self.auto_report_thread = threading.Thread(target=self.auto_report_task, daemon=True)
        self.auto_report_thread.start()
        logger.info("[HourlyVoice] 自动报时线程已启动")
    
    def stop_auto_report_thread(self):
        """
        停止自动报时线程
        """
        if self.auto_report_thread is None or not self.auto_report_thread.is_alive():
            logger.info("[HourlyVoice] 自动报时线程未在运行")
            return
        
        self.stop_thread = True
        try:
            self.auto_report_thread.join(timeout=5)
            if self.auto_report_thread.is_alive():
                logger.warning("[HourlyVoice] 自动报时线程无法正常停止")
            else:
                logger.info("[HourlyVoice] 自动报时线程已停止")
        except Exception as e:
            logger.error(f"[HourlyVoice] 停止自动报时线程出错: {e}")
    
    def auto_report_task(self):
        """
        自动报时线程的主任务
        """
        logger.info("[HourlyVoice] 自动报时任务已启动")
        
        # 获取下一个整点时间
        now = datetime.datetime.now()
        next_hour = (now.replace(minute=0, second=0, microsecond=0) + 
                     datetime.timedelta(hours=1))
        
        while not self.stop_thread:
            try:
                # 计算距离下一个整点的等待时间
                now = datetime.datetime.now()
                wait_seconds = (next_hour - now).total_seconds()
                
                # 如果等待时间小于0，重新计算下一个整点
                if wait_seconds <= 0:
                    next_hour = next_hour + datetime.timedelta(hours=1)
                    wait_seconds = (next_hour - now).total_seconds()
                
                # 等待到下一个整点（每10秒检查一次以便能够及时响应停止信号）
                wait_count = int(wait_seconds / 10) + 1
                for _ in range(wait_count):
                    if self.stop_thread:
                        return
                    time.sleep(min(10, wait_seconds))
                    wait_seconds -= 10
                    if wait_seconds <= 0:
                        break
                
                # 到达整点，执行报时
                if not self.stop_thread:
                    current_hour = next_hour.hour
                    logger.info(f"[HourlyVoice] 执行整点报时: {current_hour}点")
                    
                    # 获取整点报时语音和文本
                    voice_path, text_msg = self.get_hour_voice(current_hour)
                    
                    # 发送到配置的所有频道
                    channels = self.config.get("auto_report", {}).get("channels", [])
                    if channels:
                        self.send_to_channels(channels, voice_path, text_msg)
                    else:
                        logger.warning("[HourlyVoice] 未配置报时频道，无法发送自动报时")
                    
                    # 更新下一个整点时间
                    next_hour = next_hour + datetime.timedelta(hours=1)
            except Exception as e:
                logger.error(f"[HourlyVoice] 自动报时任务出错: {e}")
                # 出错后休眠一段时间，避免频繁错误消耗资源
                time.sleep(60)
                
                # 重新计算下一个整点
                now = datetime.datetime.now()
                next_hour = (now.replace(minute=0, second=0, microsecond=0) + 
                            datetime.timedelta(hours=1))
        
        logger.info("[HourlyVoice] 自动报时任务已结束")
    
    def send_to_channels(self, channels, voice_path, text_msg):
        """
        向指定频道发送报时消息
        :param channels: 频道ID列表
        :param voice_path: 语音文件路径
        :param text_msg: 文本消息
        """
        if not voice_path:
            logger.warning(f"[HourlyVoice] 语音文件获取失败，仅发送文本消息")
        
        for channel_id in channels:
            try:
                # 先发送文本
                self.send_text_to_channel(channel_id, text_msg)
                
                # 如果有语音，再发送语音
                if voice_path:
                    self.send_voice_to_channel(channel_id, voice_path)
                    
                logger.info(f"[HourlyVoice] 已向频道 {channel_id} 发送整点报时")
            except Exception as e:
                logger.error(f"[HourlyVoice] 向频道 {channel_id} 发送报时失败: {e}")
    
    def send_text_to_channel(self, channel_id, text):
        """
        向特定频道发送文本消息
        """
        try:
            self.bot.send_message(channel_id, text)
        except Exception as e:
            logger.error(f"[HourlyVoice] 发送文本到频道 {channel_id} 失败: {e}")
    
    def send_voice_to_channel(self, channel_id, voice_path):
        """
        向特定频道发送语音消息
        """
        try:
            self.bot.send_voice(channel_id, voice_path)
        except Exception as e:
            logger.error(f"[HourlyVoice] 发送语音到频道 {channel_id} 失败: {e}")

    def get_hour_voice(self, hour=None):
        """
        从API获取整点报时语音文件
        :param hour: 指定的小时数，为None则使用当前小时
        :return: (本地MP3文件路径, 报时文本消息) 或 (None, 错误消息)
        """
        try:
            api_url = self.config["api"]["url"]
            
            # 如果没有指定小时，则获取当前小时
            if hour is None:
                current_hour = datetime.datetime.now().hour
                hour = current_hour
            
            # 验证小时范围是否有效 (1-24)
            try:
                hour_int = int(hour)
                if hour_int < 1 or hour_int > 24:
                    return None, f"小时必须在1到24之间，您输入的是{hour_int}"
                hour = hour_int
            except ValueError:
                return None, f"无效的小时格式: {hour}"
            
            # 构建API请求URL
            request_url = f"{api_url}?h={hour}"
            
            for retry in range(3):
                try:
                    # 发送请求获取数据
                    response = requests.get(request_url, timeout=30)
                    response.raise_for_status()
                    break
                except requests.RequestException as e:
                    if retry == 2:
                        logger.error(f"[HourlyVoice] 报时API请求失败，重试次数已用完: {e}")
                        return None, "抱歉，报时服务暂时不可用，请稍后再试"
                    logger.warning(f"[HourlyVoice] 报时API请求重试 {retry + 1}/3: {e}")
                    time.sleep(1)
            
            try:
                data = response.json()
            except json.JSONDecodeError:
                logger.error(f"[HourlyVoice] 无法解析API返回的JSON数据: {response.text}")
                return None, "抱歉，报时数据格式有误，请稍后再试"
            
            if data.get("code") == 200:
                # 获取MP3 URL和文本消息
                mp3_url = data.get("mp3")
                text_msg = data.get("msg", "未获取到报时文本")
                time_str = data.get("time", "未知时间")
                
                if not mp3_url:
                    logger.error(f"[HourlyVoice] API返回数据中没有MP3 URL: {data}")
                    return None, f"整点报时 ({time_str})：{text_msg}\n\n[语音获取失败]"
                
                # 下载MP3文件
                try:
                    mp3_response = requests.get(mp3_url, timeout=30)
                    mp3_response.raise_for_status()
                except requests.RequestException as e:
                    logger.error(f"[HourlyVoice] 下载MP3失败: {e}")
                    return None, f"整点报时 ({time_str})：{text_msg}\n\n[语音获取失败]"
                
                # 保存MP3文件
                tmp_dir = TmpDir().path()
                timestamp = int(time.time())
                random_str = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz', k=6))
                mp3_path = os.path.join(tmp_dir, f"hourly_voice_{hour}_{timestamp}_{random_str}.mp3")
                
                with open(mp3_path, "wb") as f:
                    f.write(mp3_response.content)
                
                if os.path.getsize(mp3_path) == 0:
                    logger.error("[HourlyVoice] 下载的语音文件大小为0")
                    os.remove(mp3_path)
                    return None, f"整点报时 ({time_str})：{text_msg}\n\n[语音获取失败]"
                
                # 将临时文件添加到跟踪列表
                self.temp_files.append(mp3_path)
                
                logger.info(f"[HourlyVoice] 语音下载完成: {mp3_path}, 大小: {os.path.getsize(mp3_path)/1024:.2f}KB")
                
                # 构建完整的报时消息
                full_msg = f"整点报时 ({time_str})：\n{text_msg}"
                
                return mp3_path, full_msg
            else:
                error_msg = data.get("msg", "未知错误")
                logger.error(f"[HourlyVoice] API返回错误: {data}")
                return None, f"报时获取失败: {error_msg}"
                
        except Exception as e:
            logger.error(f"[HourlyVoice] 获取报时时出错: {e}")
            if 'mp3_path' in locals() and os.path.exists(mp3_path):
                try:
                    os.remove(mp3_path)
                except Exception as clean_error:
                    logger.error(f"[HourlyVoice] 清理失败的语音文件时出错: {clean_error}")
            return None, "抱歉，报时服务出现未知错误，请稍后再试"

    def on_handle_context(self, e_context: EventContext):
        """
        处理上下文事件
        :param e_context: 事件上下文
        """
        if e_context["context"].type != ContextType.TEXT:
            return

        content = e_context["context"].content.strip()
        
        # 匹配"整点报时"关键词
        if content == "整点报时":
            logger.info("[HourlyVoice] 收到整点报时请求")
            
            # 获取当前时间的报时
            voice_path, text_msg = self.get_hour_voice()
            
            # 处理结果
            self._handle_voice_result(e_context, voice_path, text_msg)
            return
        
        # 匹配"报时 [小时]"格式
        hour_match = re.match(r'^报时\s+(\d+)$', content)
        if hour_match:
            hour = hour_match.group(1)
            logger.info(f"[HourlyVoice] 收到指定时间报时请求: {hour}点")
            
            # 获取指定小时的报时
            voice_path, text_msg = self.get_hour_voice(hour)
            
            # 处理结果
            self._handle_voice_result(e_context, voice_path, text_msg)
            return
        
        # 自动报时管理命令
        if content == "开启自动报时":
            # 开启自动报时
            self.config["auto_report"]["enabled"] = True
            self.save_config()
            self.start_auto_report_thread()
            
            reply = Reply()
            reply.type = ReplyType.TEXT
            reply.content = "✅ 自动整点报时已开启"
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            return
        
        elif content == "关闭自动报时":
            # 关闭自动报时
            self.config["auto_report"]["enabled"] = False
            self.save_config()
            self.stop_auto_report_thread()
            
            reply = Reply()
            reply.type = ReplyType.TEXT
            reply.content = "❌ 自动整点报时已关闭"
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            return
        
        elif content == "添加报时频道":
            # 获取当前会话的频道ID
            session_id = e_context["context"].get("session_id")
            if not session_id:
                reply = Reply()
                reply.type = ReplyType.TEXT
                reply.content = "❌ 无法获取当前会话ID"
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            
            # 添加频道到列表
            channels = self.config.get("auto_report", {}).get("channels", [])
            if session_id in channels:
                reply = Reply()
                reply.type = ReplyType.TEXT
                reply.content = "❌ 当前频道已在报时列表中"
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            
            channels.append(session_id)
            self.config["auto_report"]["channels"] = channels
            self.save_config()
            
            reply = Reply()
            reply.type = ReplyType.TEXT
            reply.content = f"✅ 已将当前频道添加到报时列表\n当前报时频道数: {len(channels)}"
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            return
        
        elif content == "删除报时频道":
            # 获取当前会话的频道ID
            session_id = e_context["context"].get("session_id")
            if not session_id:
                reply = Reply()
                reply.type = ReplyType.TEXT
                reply.content = "❌ 无法获取当前会话ID"
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            
            # 从列表中删除频道
            channels = self.config.get("auto_report", {}).get("channels", [])
            if session_id not in channels:
                reply = Reply()
                reply.type = ReplyType.TEXT
                reply.content = "❌ 当前频道不在报时列表中"
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            
            channels.remove(session_id)
            self.config["auto_report"]["channels"] = channels
            self.save_config()
            
            reply = Reply()
            reply.type = ReplyType.TEXT
            reply.content = f"✅ 已将当前频道从报时列表中移除\n当前报时频道数: {len(channels)}"
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            return
        
        elif content == "报时频道列表":
            # 显示当前所有报时频道
            channels = self.config.get("auto_report", {}).get("channels", [])
            enabled = self.config.get("auto_report", {}).get("enabled", False)
            
            status = "✅ 已开启" if enabled else "❌ 已关闭"
            
            if not channels:
                reply_text = f"📢 自动整点报时状态: {status}\n\n未配置任何报时频道，请使用「添加报时频道」命令添加"
            else:
                reply_text = f"📢 自动整点报时状态: {status}\n\n已配置 {len(channels)} 个报时频道:\n"
                for i, channel in enumerate(channels, 1):
                    reply_text += f"{i}. {channel}\n"
            
            reply = Reply()
            reply.type = ReplyType.TEXT
            reply.content = reply_text
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            return

    def _handle_voice_result(self, e_context, voice_path, text_msg):
        """
        处理语音获取结果
        :param e_context: 事件上下文
        :param voice_path: 语音文件路径，如果失败则为None
        :param text_msg: 文本消息
        """
        if voice_path:
            logger.info(f"[HourlyVoice] 已获取语音文件: {voice_path}")
            
            # 只发送语音消息，和 WomenVoice 保持一致
            reply = Reply()
            reply.type = ReplyType.VOICE
            reply.content = voice_path
            e_context["reply"] = reply
            
            # 阻止请求传递给其他插件
            e_context.action = EventAction.BREAK_PASS
        else:
            # 仅发送文本回复
            text_reply = Reply()
            text_reply.type = ReplyType.TEXT
            text_reply.content = text_msg
            e_context["reply"] = text_reply
            e_context.action = EventAction.BREAK_PASS

    def get_help_text(self, **kwargs):
        """
        获取插件帮助文本
        :return: 帮助文本
        """
        help_text = "🕒 整点报时语音插件 🕒\n\n"
        help_text += "基本使用命令：\n"
        help_text += "- 发送「整点报时」获取当前时间的报时\n"
        help_text += "- 发送「报时 [小时]」获取指定小时的报时（1-24）\n\n"
        
        help_text += "自动报时管理命令：\n"
        help_text += "- 发送「开启自动报时」启用自动整点报时\n"
        help_text += "- 发送「关闭自动报时」禁用自动整点报时\n"
        help_text += "- 发送「添加报时频道」将当前频道添加到自动报时列表\n"
        help_text += "- 发送「删除报时频道」将当前频道从自动报时列表中移除\n"
        help_text += "- 发送「报时频道列表」查看当前所有报时频道\n\n"
        
        help_text += "示例：\n"
        help_text += "- 发送「报时 12」获取中午12点的报时\n"
        help_text += "- 发送「报时 18」获取下午6点的报时\n"
        
        return help_text

    def cleanup(self):
        """
        清理插件生成的临时文件和线程
        """
        # 停止自动报时线程
        self.stop_auto_report_thread()
        
        # 清理临时文件
        try:
            for file_path in self.temp_files:
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        logger.debug(f"[HourlyVoice] 已清理临时文件: {file_path}")
                    except Exception as e:
                        logger.error(f"[HourlyVoice] 清理临时文件失败 {file_path}: {e}")
            self.temp_files.clear()
        except Exception as e:
            logger.error(f"[HourlyVoice] 清理任务异常: {e}") 