# RSS监测工具

一个简单而强大的RSS监测工具，可以监控RSS源的变化并通过MoePush发送通知。

## 功能特点

- 支持监控多个RSS源
- 可自定义检查间隔时间
- 支持监控RSS源的不同字段（标题、链接、描述等）
- 通过MoePush发送更新通知
- 自动重试机制
- 详细的日志记录
- 支持本地XML文件测试

## 安装

1. 克隆仓库：
```bash
git clone https://github.com/liyixin21/RssChecker.git
cd rss-checker
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 配置：
- 复制 `config.ini.example` 为 `config.ini`
- 编辑 `config.ini` 文件，设置您的RSS源和MoePush配置

## 使用方法

### 基本用法

```bash
python rss_checker.py
```

### 命令行参数

- `-c, --config`: 指定配置文件路径（默认：config.ini）
- `-o, --once`: 只运行一次检查
- `-d, --debug`: 启用调试模式
- `-f, --file`: 使用本地XML文件代替URL（用于测试）
- `--dump-file`: 解析并打印指定XML文件的内容结构

### 示例

1. 使用自定义配置文件：
```bash
python rss_checker.py -c my_config.ini
```

2. 只运行一次检查：
```bash
python rss_checker.py -o
```

3. 使用本地文件测试：
```bash
python rss_checker.py -f test.xml
```

4. 查看XML文件结构：
```bash
python rss_checker.py --dump-file test.xml
```

## 配置文件说明

配置文件使用INI格式，包含以下部分：

### [main]
- `cache_dir`: 缓存目录路径
- `timeout`: 请求超时时间（秒）
- `max_retries`: 最大重试次数
- `retry_interval`: 重试间隔时间（秒）

### [moepush]
- `webhook_url`: MoePush的webhook URL
- `title`: 通知标题

### [rss:任务名]
- `url`: RSS源的URL
- `field`: 要监控的字段（title, link, description等）
- `interval`: 检查间隔（秒）

## 日志说明

程序会输出以下类型的日志：
- `[INIT]`: 初始化信息
- `[CHECK]`: 检查结果
- `[TASK]`: 任务执行信息
- `[ERROR]`: 错误信息
- `[SYSTEM]`: 系统信息
- `[STATUS]`: 运行状态统计

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request！ 