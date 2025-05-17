#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import configparser
import feedparser
import hashlib
import json
import logging
import os
import requests
import sys
import time
import socket
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union


# 设置日志记录
class CustomFormatter(logging.Formatter):
    """自定义日志格式化器"""
    def format(self, record):
        # 添加日志类型标签
        if not hasattr(record, 'log_type'):
            record.log_type = 'INFO'
        # 格式化时间戳
        record.asctime = datetime.now().strftime('[%Y-%m-%d %H:%M:%S]')
        return f"{record.asctime} [{record.log_type}] {record.getMessage()}"

# 设置日志记录
logger = logging.getLogger('rss_checker')
logger.setLevel(logging.INFO)

# 创建控制台处理器
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(CustomFormatter())
logger.addHandler(console_handler)


class RSSChecker:
    """RSS监测器，检查RSS feed中的更新并发送通知"""

    def __init__(self, config_file: str = 'config.ini'):
        """
        初始化RSS监测器
        
        Args:
            config_file: 配置文件路径
        """
        self.config_file = config_file
        self.config = self._load_config()
        self.cache_dir = self.config.get('main', 'cache_dir', fallback='cache')
        self.timeout = int(self.config.get('main', 'timeout', fallback='30'))
        self.max_retries = int(self.config.get('main', 'max_retries', fallback='3'))  # 最大重试次数
        self.retry_interval = int(self.config.get('main', 'retry_interval', fallback='10'))  # 重试间隔（秒）
        self.retry_counts = {}  # 用于存储每个任务的重试次数
        
        # 创建缓存目录
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
            
        # 记录初始化完成
        logger.info(f"liyixin21/RssChecker")
        rss_sections = [s for s in self.config.sections() if s.startswith('rss:')]
        logger.info(f"RSS检查器初始化成功 | 加载{len(rss_sections)}个监测任务", extra={'log_type': 'INIT'})
        
        # 显示任务列表
        if rss_sections:
            logger.info("任务列表:", extra={'log_type': 'INIT'})
            for section in rss_sections:
                interval = int(self.config.get(section, 'interval', fallback='3600'))
                field = self.config.get(section, 'field', fallback='title')
                task_name = section.split(':', 1)[1] if ':' in section else section
                logger.info(f"  {task_name} -> 间隔: {interval}秒", extra={'log_type': 'INIT'})
        
        logger.info(f"开始监测", extra={'log_type': 'INIT'})

    def _load_config(self) -> configparser.ConfigParser:
        """
        加载配置文件
        
        Returns:
            ConfigParser对象
        """
        # 检查配置文件是否存在
        if not os.path.exists(self.config_file):
            # 如果不存在，创建默认配置
            self._create_default_config()
            
        config = configparser.ConfigParser()
        config.read(self.config_file, encoding='utf-8')
        return config

    def _create_default_config(self) -> None:
        """创建默认配置文件"""
        config = configparser.ConfigParser()
        
        # 主配置
        config['main'] = {
            'cache_dir': 'cache',
            'timeout': '30',  # 超时时间（秒）
            'max_retries': '3',  # 最大重试次数
            'retry_interval': '10'  # 重试间隔（秒）
        }
        
        # MoePush配置
        config['moepush'] = {
            'webhook_url': 'https://moepush.app/api/push/你的推送KEY',
            'title': 'RSS监测通知'
        }
        
        # 示例RSS监测配置
        config['rss:example'] = {
            'url': 'https://example.com/feed.xml',
            'field': 'title',  # 监测的字段：title, link, description, pubDate
            'interval': '3600'  # 检查间隔（秒）
        }
        
        
        # 写入配置文件
        with open(self.config_file, 'w', encoding='utf-8') as f:
            config.write(f)
            
        logger.info(f"已创建默认配置文件: {self.config_file}")
        print(f"请编辑配置文件 '{self.config_file}' 设置RSS监测和MoePush推送参数")
        sys.exit(0)

    def _get_cache_file(self, section: str) -> str:
        """
        获取缓存文件路径
        
        Args:
            section: 配置部分名称
            
        Returns:
            缓存文件路径
        """
        # 使用配置部分的名称作为缓存文件名，让文件名更易读
        readable_name = section.replace(':', '_')
        return os.path.join(self.cache_dir, f"{readable_name}.json")

    def _load_cache(self, section: str) -> Dict:
        """
        加载缓存数据
        
        Args:
            section: 配置部分名称
            
        Returns:
            缓存数据字典
        """
        cache_file = self._get_cache_file(section)
        
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    # 确保关键字段存在
                    if 'last_check' not in data:
                        data['last_check'] = 0
                    if 'content' not in data:
                        data['content'] = None
                    
                    return data
            except Exception as e:
                logger.error(f"加载缓存文件失败: {str(e)}")
                
        # 如果缓存不存在或加载失败，返回空字典
        return {'last_check': 0, 'content': None, 'last_entry': None}

    def _save_cache(self, section: str, data: Dict) -> None:
        """
        保存缓存数据
        
        Args:
            section: 配置部分名称
            data: 要保存的数据
        """
        cache_file = self._get_cache_file(section)
        
        try:
            # 将RSS条目对象转换为可序列化的字典
            serializable_data = data.copy()
            
            # 如果有last_entry，需要转换为可保存的格式
            if 'last_entry' in serializable_data and serializable_data['last_entry']:
                entry = serializable_data['last_entry']
                
                # 处理不同类型的entry
                if isinstance(entry, dict):
                    # 只保存常见的必要字段
                    serializable_data['last_entry'] = {
                        'item': entry.get('item', ''),
                        'title': entry.get('title', ''),
                        'link': entry.get('link', ''),
                        'description': entry.get('description', ''),
                        'published': entry.get('published', ''),
                        'summary': entry.get('summary', '')
                    }
                elif isinstance(entry, list):
                    # 如果是列表(如条目列表)，只保存标题和链接
                    serializable_data['last_entry'] = [
                        {'title': item.get('title', ''), 'link': item.get('link', '')}
                        for item in entry[:5]  # 只保存前5项
                    ]
                else:
                    # 如果不是字典类型，直接转换为字符串
                    serializable_data['last_entry'] = str(entry)
            
            # 内容可能也是复杂对象，需要序列化
            if 'content' in serializable_data:
                content = serializable_data['content']
                if isinstance(content, dict):
                    # 字典内容保留
                    pass
                elif isinstance(content, list):
                    # 列表内容，只保留前5项和总数信息
                    if len(content) > 5:
                        serializable_data['content'] = {
                            'total_items': len(content),
                            'first_5_items': content[:5]
                        }
                elif not isinstance(content, (str, int, float, bool, type(None))):
                    # 其他不可直接序列化的类型，转换为字符串
                    serializable_data['content'] = str(content)
            
            # 添加人类可读的时间
            if 'last_check' in serializable_data:
                serializable_data['last_check_readable'] = datetime.fromtimestamp(
                    serializable_data['last_check']
                ).strftime('%Y-%m-%d %H:%M:%S')
                
            # 添加下次检查时间
            if 'last_check' in serializable_data and 'next_check_interval' in serializable_data:
                next_check_time = serializable_data['last_check'] + serializable_data['next_check_interval']
                serializable_data['next_check_time'] = next_check_time
                serializable_data['next_check_readable'] = datetime.fromtimestamp(
                    next_check_time
                ).strftime('%Y-%m-%d %H:%M:%S')
                
            # 保存为JSON格式
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(serializable_data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"保存缓存文件失败: {str(e)}")
            logger.debug(f"无法序列化的数据: {str(data)}")

    def _get_field_value(self, feed, field_path: str):
        """
        获取feed中指定路径的字段值
        
        Args:
            feed: feedparser解析的feed对象
            field_path: 字段路径，支持点号分隔的多级路径，如'channel.title'
            
        Returns:
            字段值，如果路径不存在则返回None
        """
        # 处理特殊情况
        if field_path == 'channel':
            # 返回整个channel对象
            return {k: getattr(feed.feed, k) for k in dir(feed.feed) 
                  if not k.startswith('_') and not callable(getattr(feed.feed, k))}
        elif field_path == 'channel.item' or field_path == 'channel.items':
            # 返回所有条目
            return feed.entries
        elif field_path == 'channel.title':
            return feed.feed.title
        elif field_path == 'channel.link':
            return feed.feed.link
        elif field_path == 'channel.description':
            return feed.feed.description if hasattr(feed.feed, 'description') else None
        elif field_path == 'channel.language':
            return feed.feed.language if hasattr(feed.feed, 'language') else None
        elif field_path == 'channel.lastBuildDate':
            return feed.feed.updated if hasattr(feed.feed, 'updated') else None
        elif field_path == 'channel.generator':
            return feed.feed.generator if hasattr(feed.feed, 'generator') else None
        elif field_path.startswith('channel.'):
            # 处理其他channel字段
            sub_field = field_path.split('.')[1]
            return getattr(feed.feed, sub_field) if hasattr(feed.feed, sub_field) else None
        elif field_path.startswith('entry.'):
            # 处理entry字段
            if not feed.entries:
                return None
            sub_field = field_path.split('.')[1]
            return feed.entries[0].get(sub_field)
        else:
            # 默认处理，假设是entry的字段
            if not feed.entries:
                return None
            return feed.entries[0].get(field_path)

    def check_rss(self, section: str) -> Tuple[bool, Optional[Dict]]:
        """
        检查RSS feed是否有更新
        
        Args:
            section: 配置部分名称
            
        Returns:
            Tuple(是否有更新, 更新的条目)
        """
        if not self.config.has_section(section):
            logger.error(f"配置中不存在部分: {section}", extra={'log_type': 'ERROR'})
            return False, None
            
        rss_url = self.config.get(section, 'url')
        field = self.config.get(section, 'field', fallback='title')
        cache = self._load_cache(section)
        last_check = cache.get('last_check', 0)
        now = time.time()
        elapsed_time = now - last_check
        
        # 获取重试次数（从内存中获取）
        retry_count = self.retry_counts.get(section, 0)
        
        try:
            feed = feedparser.parse(rss_url)
            
            if hasattr(feed, 'status') and feed.status != 200:
                error_msg = f"获取RSS失败: {feed.status}"
                return self._handle_retry(section, error_msg, cache, retry_count)
                
            content = self._get_field_value(feed, field)
            
            if content is None:
                error_msg = f"无法获取字段: {field}"
                return self._handle_retry(section, error_msg, cache, retry_count)
                
            if cache.get('content') == content:
                task_name = section.split(':', 1)[1] if ':' in section else section
                logger.info(f"{task_name} -> 内容未更新", extra={'log_type': 'CHECK'})
                # 重置重试计数
                self.retry_counts[section] = 0
                return False, None
                
            # 检测到内容更新
            task_name = section.split(':', 1)[1] if ':' in section else section
            logger.info(f"{task_name} -> 检测到内容更新", extra={'log_type': 'CHECK'})
            
            # 更新缓存并重置重试计数
            cache['content'] = content
            cache['last_check'] = now
            cache['last_entry'] = feed.entries[0] if feed.entries else {}
            self.retry_counts[section] = 0
            self._save_cache(section, cache)
            
            return True, feed.entries[0] if feed.entries else {'field': field, 'value': content}
            
        except Exception as e:
            error_msg = f"连接异常（{str(e)}）"
            return self._handle_retry(section, error_msg, cache, retry_count)

    def _handle_retry(self, section: str, error_msg: str, cache: Dict, retry_count: int) -> Tuple[bool, Optional[Dict]]:
        """处理重试逻辑"""
        task_name = section.split(':', 1)[1] if ':' in section else section
        
        if retry_count < self.max_retries:
            retry_count += 1
            self.retry_counts[section] = retry_count
            
            logger.error(f"{task_name} -> {error_msg} | 重试剩余：{self.max_retries - retry_count}", 
                        extra={'log_type': 'ERROR'})
            time.sleep(self.retry_interval)
            return self.check_rss(section)
        else:
            # 超过最大重试次数，重置重试计数
            self.retry_counts[section] = 0
            logger.error(f"{task_name} -> {error_msg} | 已达到最大重试次数", 
                        extra={'log_type': 'ERROR'})
            return False, None

    def send_notification(self, section: str, entry: Dict) -> bool:
        """
        发送MoePush通知
        
        Args:
            section: 配置部分名称
            entry: RSS条目
            
        Returns:
            是否发送成功
        """
        if not self.config.has_section('moepush'):
            logger.error("配置中不存在MoePush部分")
            return False
            
        webhook_url = self.config.get('moepush', 'webhook_url')
        default_title = self.config.get('moepush', 'title', fallback='RSS更新通知')
        
        # 获取需要监测的字段
        field = self.config.get(section, 'field', fallback='title')
        
        # 准备通知内容
        section_name = section.split(':', 1)[1] if ':' in section else section
        title = f"{default_title}: {section_name}"
        
        # 判断是channel字段还是entry字段
        if field == 'channel':
            # 监测整个channel
            content = "监测到RSS频道整体更新\n\n"
            # 添加channel主要信息
            if 'value' in entry and isinstance(entry['value'], dict):
                channel_info = entry['value']
                if 'title' in channel_info:
                    content += f"标题: {channel_info['title']}\n"
                if 'description' in channel_info:
                    content += f"描述: {channel_info['description']}\n"
                if 'updated' in channel_info:
                    content += f"更新时间: {channel_info['updated']}\n"
            else:
                content += "频道信息已更新"
        elif field == 'channel.item' or field == 'channel.items':
            # 监测所有条目
            content = "监测到RSS条目列表更新\n\n"
            # 如果有条目，显示前几个条目的标题
            if 'value' in entry and isinstance(entry['value'], list):
                items = entry['value']
                content += f"共有 {len(items)} 个条目\n\n"
                for i, item in enumerate(items[:3]):  # 只显示前3个
                    content += f"{i+1}. {item.get('title', '无标题')}\n"
                if len(items) > 3:
                    content += f"... 等 {len(items)} 个条目"
            else:
                content += "条目列表已更新"
        elif field.startswith('channel.'):
            content = f"监测到RSS频道更新\n\n{field}: {entry.get('value', '未知')}"
        else:
            # 尝试获取字段内容
            field_value = entry.get(field.split('.')[-1], '未获取到内容')
            content = f""
            
            # 如果条目有链接，添加到内容中
            if 'link' in entry:
                content += f"链接: {entry['link']}"
            
        try:
            # 发送MoePush通知
            data = {
                'title': title,
                'content': content
            }
            
            logger.debug(f"发送通知内容: {data}")
            response = requests.post(webhook_url, json=data, timeout=self.timeout)
            
            if response.status_code == 200:
                logger.info(f"MoePush通知发送成功: {section_name}")
                return True
            else:
                logger.error(f"MoePush通知发送失败: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"发送MoePush通知时出错: {str(e)}")
            return False
     
    def get_next_check_task(self) -> Tuple[Optional[str], int]:
        """
        获取下一个需要检查的任务及等待时间
        
        Returns:
            Tuple(任务名称, 等待时间)，如果没有任务则返回(None, 默认等待时间)
        """
        default_wait = 60  # 默认等待时间（秒）
        now = time.time()
        
        # 获取所有RSS配置部分
        rss_sections = [s for s in self.config.sections() if s.startswith('rss:')]
        if not rss_sections:
            return None, default_wait
            
        next_section = None
        next_check_time = float('inf')
        
        # 找出最早需要检查的任务
        for section in rss_sections:
            try:
                cache = self._load_cache(section)
                last_check = cache.get('last_check', 0)
                interval = int(self.config.get(section, 'interval', fallback='3600'))
                check_time = last_check + interval
                
                if check_time < next_check_time:
                    next_check_time = check_time
                    next_section = section
            except Exception as e:
                logger.error(f"检查任务 {section} 的下次执行时间出错: {str(e)}", extra={'log_type': 'ERROR'})
                
        # 计算等待时间
        wait_time = next_check_time - now
        
        # 如果已经超过了检查时间，立即检查
        if wait_time <= 0:
            wait_time = 0
        # 设置一个最长等待时间，避免长时间无响应
        elif wait_time > 3600:
            wait_time = 3600
            
        return next_section, int(wait_time)
              
    def run_once(self) -> None:
        """运行一次所有RSS监测任务"""
        # 获取所有RSS配置部分
        rss_sections = [s for s in self.config.sections() if s.startswith('rss:')]
        
        if not rss_sections:
            logger.warning("没有配置RSS监测任务", extra={'log_type': 'WARNING'})
            return
            
        for section in rss_sections:
            try:
                # 获取配置的检查间隔
                interval = int(self.config.get(section, 'interval', fallback='3600'))
                
                # 获取上次检查时间
                cache = self._load_cache(section)
                last_check = cache.get('last_check', 0)
                now = time.time()
                
                # 计算距离上次检查的时间
                elapsed_time = now - last_check
                
                # 检查是否到达检查间隔
                if elapsed_time < interval:
                    continue
                    
                # 检查RSS更新
                has_update, entry = self.check_rss(section)
                
                if has_update and entry:
                    # 发送通知
                    self.send_notification(section, entry)
                else:
                    # 仅更新最后检查时间
                    cache['last_check'] = now
                    cache['next_check_interval'] = interval
                    self._save_cache(section, cache)
            except Exception as e:
                logger.error(f"处理任务 {section} 时出错: {str(e)}", extra={'log_type': 'ERROR'})
     
    def run_task(self, section: str) -> None:
        """
        运行单个任务
        
        Args:
            section: 任务名称
        """
        if not section or not self.config.has_section(section):
            logger.error(f"任务不存在: {section}", extra={'log_type': 'ERROR'})
            return
            
        try:
            # 检查RSS更新
            has_update, entry = self.check_rss(section)
            
            if has_update and entry:
                # 发送通知
                self.send_notification(section, entry)
            else:
                # 仅更新最后检查时间
                cache = self._load_cache(section)
                cache['last_check'] = time.time()
                cache['next_check_interval'] = int(self.config.get(section, 'interval', fallback='3600'))
                self._save_cache(section, cache)
        except Exception as e:
            logger.error(f"执行任务 {section} 出错: {str(e)}", extra={'log_type': 'ERROR'})
                
    def run_forever(self) -> None:
        """持续运行RSS监测任务"""
        start_time = time.time()
        success_count = 0
        fail_count = 0
        pending_count = 0
        
        try:
            # 首次启动时检查所有任务
            self.run_once()
            
            while True:
                next_task, wait_time = self.get_next_check_task()
                
                if wait_time > 0:
                    time.sleep(wait_time)
                
                if next_task:
                    task_name = next_task.split(':', 1)[1] if ':' in next_task else next_task
                    logger.info(f"{task_name} -> 开始检查", extra={'log_type': 'TASK'})
                    try:
                        # 检查RSS更新
                        has_update, entry = self.check_rss(next_task)
                        
                        if has_update and entry:
                            # 发送通知
                            if self.send_notification(next_task, entry):
                                success_count += 1
                            else:
                                fail_count += 1
                        else:
                            pending_count += 1
                            
                        # 更新最后检查时间
                        cache = self._load_cache(next_task)
                        cache['last_check'] = time.time()
                        cache['next_check_interval'] = int(self.config.get(next_task, 'interval', fallback='3600'))
                        self._save_cache(next_task, cache)
                        
                    except Exception as e:
                        logger.error(f"执行任务 {next_task} 出错: {str(e)}", extra={'log_type': 'ERROR'})
                        fail_count += 1
                else:
                    time.sleep(60)
                
                # 重新加载配置
                self.config = self._load_config()
                
        except KeyboardInterrupt:
            run_time = int(time.time() - start_time)
            logger.info(f"收到终止信号，正在关闭...", extra={'log_type': 'SYSTEM'})
            logger.info(f"运行时长：{run_time}s | 成功：{success_count} | 失败：{fail_count} | 未更新：{pending_count}", 
                       extra={'log_type': 'STATUS'})
        except Exception as e:
            logger.error(f"程序运行出错: {str(e)}", extra={'log_type': 'ERROR'})


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='RSS监测工具')
    parser.add_argument('-c', '--config', default='config.ini', help='配置文件路径')
    parser.add_argument('-o', '--once', action='store_true', help='只运行一次')
    parser.add_argument('-d', '--debug', action='store_true', help='打印调试信息')
    parser.add_argument('-f', '--file', help='使用本地文件代替URL（用于测试）')
    parser.add_argument('--dump-file', help='直接解析并打印指定的XML文件内容结构')
    args = parser.parse_args()
    
    # 设置日志级别
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    # 直接打印文件内容结构
    if args.dump_file:
        try:
            logger.info(f"解析文件: {args.dump_file}")
            with open(args.dump_file, 'r', encoding='utf-8') as f:
                content = f.read()
            feed = feedparser.parse(content)
            
            print("\n===== Feed结构 =====")
            print(f"Feed版本: {feed.get('version', '未知')}")
            print(f"状态码: {feed.get('status', '未知')}")
            
            # 打印feed.feed (channel)信息
            print("\n===== Channel信息 =====")
            channel_attrs = [attr for attr in dir(feed.feed) if not attr.startswith('_') and not callable(getattr(feed.feed, attr))]
            for attr in sorted(channel_attrs):
                value = getattr(feed.feed, attr)
                print(f"channel.{attr}: {value}")
            
            # 打印条目信息
            print(f"\n===== 条目信息 (共{len(feed.entries)}个) =====")
            if feed.entries:
                # 打印第一个条目的所有字段
                entry = feed.entries[0]
                print("\n第一个条目字段:")
                for key, value in entry.items():
                    print(f"entry.{key}: {value}")
            
            sys.exit(0)
        except Exception as e:
            logger.error(f"解析文件失败: {str(e)}")
            sys.exit(1)
        
    # 添加本地文件支持
    if args.file:
        # 修改feedparser以使用本地文件
        old_parse = feedparser.parse
        
        def parse_wrapper(url, *args, **kwargs):
            if url == args.file or url == 'file://' + args.file:
                logger.debug(f"使用本地文件: {args.file}")
                with open(args.file, 'r', encoding='utf-8') as f:
                    content = f.read()
                return old_parse(content)
            return old_parse(url, *args, **kwargs)
            
        feedparser.parse = parse_wrapper
    
    # 创建RSS检查器
    checker = RSSChecker(config_file=args.config)
    
    # 运行任务
    if args.once:
        checker.run_once()
    else:
        checker.run_forever()


if __name__ == '__main__':
    main() 