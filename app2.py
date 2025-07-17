# 较 app1 添加了飞书通知的功能

from flask import Flask, jsonify, render_template, send_file, request
import os
import cv2
import time
import threading
import glob
from detector.model import load_model, run_inference
from detector.postprocess import estimate_areas
from saveImage import saveImage
import mysql.connector
from mysql.connector import Error
import requests
import json


# 飞书应用配置
FEISHU_APP_ID = "cli_a8e897b12f27500e"  # 替换为你的飞书应用ID
FEISHU_APP_SECRET = "bQtAu5D4DuECIa4t5zK0je3QNqK4e5m8"  # 替换为你的飞书应用密钥
FEISHU_USER_ID = "10407843"  # 要通知的具体用户ID

# 缓存访问令牌和过期时间
feishu_token_cache = {
    "token": None,
    "expire_time": 0
}

def get_feishu_access_token():
    """获取并缓存飞书访问令牌"""
    # 检查缓存中是否有未过期的令牌
    if feishu_token_cache["token"] and time.time() < feishu_token_cache["expire_time"]:
        return feishu_token_cache["token"]
    
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json"}
    data = {
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        token_data = response.json()
        # 缓存令牌，提前5分钟过期
        feishu_token_cache["token"] = token_data.get("tenant_access_token")
        feishu_token_cache["expire_time"] = time.time() + token_data.get("expire", 7200) - 300
        return feishu_token_cache["token"]
    except Exception as e:
        print(f"获取飞书访问令牌失败: {e}")
        return None

def send_feishu_message(result):
    """使用飞书消息API发送个人通知"""
    access_token = get_feishu_access_token()
    if not access_token:
        print("无法获取飞书访问令牌")
        return False

    # 构建详情链接，指向原始图片
    base_url = "http://10.60.208.29:8080"  # 替换为实际服务器地址
    detail_url = f"{base_url}/original-image/{result.get('file_name','')}"
    
    # 构建消息内容
    message_content = {
        "msg_type": "interactive",
        "card": {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "title": {
                    "content": "🚨 仓库空间容量告警",
                    "tag": "plain_text"
                },
                "template": "red"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "content": f"**文件**: {result.get('file_name','未知')}\n"
                                  f"**货物占比**: {result.get('cargo_ratio_percent','未知')}%\n"
                                  f"**时间**: {result.get('timestamp','未知')}",
                        "tag": "lark_md"
                    }
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "content": "查看详情",
                                "tag": "plain_text"
                            },
                            "type": "primary",
                            "multi_url": {
                                "url": detail_url,
                                "pc_url": detail_url,
                                "android_url": detail_url,
                                "ios_url": detail_url
                            }
                        }
                    ]
                }
            ]
        }
    }
    
    # 发送消息
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    params = {
        "receive_id_type": "user_id"
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    data = {
        "receive_id": FEISHU_USER_ID,
        "content": json.dumps(message_content["card"]),
        "msg_type": "interactive"
    }
    
    try:
        response = requests.post(url, params=params, headers=headers, json=data)
        if response.status_code == 200:
            print("飞书消息发送成功")
            return True
        print(f"飞书消息发送失败: {response.status_code} - {response.text}")
        return False
    except Exception as e:
        print(f"发送飞书消息时出错: {e}")
        return False


# 最大保留文件数
MAX_FILES = 200

app = Flask(__name__)
UPLOAD_FOLDER = './uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 指定自动检测的文件夹路径
AUTO_DETECT_FOLDER = './auto_detect/'
os.makedirs(AUTO_DETECT_FOLDER, exist_ok=True)

# 结果图像文件夹
RESULT_FOLDER = './static/result/'
os.makedirs(RESULT_FOLDER, exist_ok=True)

# 支持的图片格式
IMAGE_EXTENSIONS = ['*.jpg', '*.jpeg', '*.png', '*.webp']

model = load_model()

# MySQL数据库配置
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '123456',
    'database': 'warehouse_analysis'
}


def create_db_connection():
    """创建数据库连接"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print(f"数据库连接错误: {e}")
        return None


def save_to_database(result):
    """将分析结果保存到数据库"""
    connection = create_db_connection()
    if connection is None:
        print("无法连接到数据库")
        return False

    try:
        cursor = connection.cursor()
        query = """
        INSERT INTO analysis_results (
            file_name, file_path, timestamp, cargo_ratio_percent, error_message
        ) VALUES (%s, %s, %s, %s, %s)
        """

        # 准备数据
        data = (
            result.get("file_name"),
            result.get("file_path"),
            result.get("timestamp"),
            result.get("cargo_ratio_percent"),
            result.get("error")
        )

        cursor.execute(query, data)
        connection.commit()
        print(f"结果已保存到数据库: {result['file_name']}")
        return True
    except Error as e:
        print(f"数据库保存错误: {e}")
        return False
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


class FolderMonitorThread(threading.Thread):
    def __init__(self, folder_path, check_interval=5):
        super().__init__()
        self.folder_path = folder_path
        self.check_interval = check_interval  # 检查间隔（秒）
        self.running = False
        self.processed_files = {}  # 记录已处理文件及其修改时间
        self.current_file = None  # 当前正在处理的文件
        self.results = {}  # 存储所有文件的分析结果（文件名 -> 结果）
        self.current_result = None  # 当前结果
        self.status = "初始化中"  # 当前状态
        self.file_order = []  # 文件处理顺序
        self.result_path_map = {}  # 映射：原始文件路径 -> 结果文件路径

    def run(self):
        self.running = True
        while self.running:
            try:
                self.status = "监控中"
                self.check_for_new_files()
                # 每次检查后清理旧文件
                self.cleanup_old_files()
            except Exception as e:
                self.status = f"错误: {str(e)}"
                print(f"文件夹监控错误: {e}")
            time.sleep(self.check_interval)

    def check_for_new_files(self):
        """检查文件夹中是否有新的或修改过的图片文件"""
        # 获取所有支持的图片文件
        all_files = []
        for ext in IMAGE_EXTENSIONS:
            all_files.extend(glob.glob(os.path.join(self.folder_path, ext)))

        # 按修改时间排序，最新的文件排在后面
        all_files.sort(key=lambda x: os.path.getctime(x))

        for file_path in all_files:
            try:
                # 获取文件的修改时间
                current_modified = os.path.getmtime(file_path)

                # 检查文件是否是新的或已修改
                if file_path not in self.processed_files or current_modified > self.processed_files[file_path]:
                    self.processed_files[file_path] = current_modified

                    # 确保每个文件只处理一次
                    if file_path not in self.file_order:
                        self.file_order.append(file_path)

                    self.analyze_file(file_path)

                    # 添加延迟，给前端足够的时间显示当前图片
                    time.sleep(2)  # 延迟2秒
            except Exception as e:
                print(f"处理文件 {file_path} 时出错: {e}")
                self.results[file_path] = {"error": f"处理文件时出错: {str(e)}"}

    def analyze_file(self, file_path):
        """分析单个图片文件"""
        try:
            self.status = f"正在分析: {os.path.basename(file_path)}"
            self.current_file = file_path
            print("----------------------------------------------------------")
            print(f"开始分析文件: {file_path}")

            img = cv2.imread(file_path)
            if img is None:
                raise Exception("无法读取图像文件")

            masks, labels, scores, shape = run_inference(model, img)
            result, vis_img = estimate_areas(masks, labels, shape, scores)

            # 保存结果图像
            result_path = saveImage(file_path)
            cv2.imwrite(result_path, vis_img)

            # 添加文件信息
            result["file_name"] = os.path.basename(file_path)
            result["file_path"] = file_path
            result["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
            result["result_image_path"] = result_path  # 保存结果图像路径

            # 保存原始文件到结果文件的映射
            self.result_path_map[file_path] = result_path

            # 保存分析结果
            self.results[file_path] = result
            self.current_result = result

            # 保存到数据库
            save_to_database(result)

            # 如果触发了告警，发送飞书通知
            if result.get("alarm", False):
                send_feishu_message(result)

            print(f"分析完成，货物占比: {result.get('cargo_ratio_percent', '未知')}%")
        except Exception as e:
            print(f"文件分析错误: {e}")
            error_result = {
                "error": f"分析失败: {str(e)}",
                "file_name": os.path.basename(file_path),
                "file_path": file_path,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            self.results[file_path] = error_result
            self.current_result = error_result
            save_to_database(error_result)

    def cleanup_old_files(self):
        """删除旧文件，保持文件数量不超过最大值"""
        try:
            # 获取所有原始文件（按创建时间排序）
            all_original_files = []
            for ext in IMAGE_EXTENSIONS:
                all_original_files.extend(glob.glob(os.path.join(self.folder_path, ext)))
            all_original_files.sort(key=os.path.getctime)  # 按创建时间排序

            # 计算需要删除的文件数量
            num_to_delete = max(0, len(all_original_files) - MAX_FILES)

            # 删除最早的原始文件及其对应的结果文件
            for i in range(num_to_delete):
                try:
                    original_file = all_original_files[i]

                    # 确保不删除当前正在处理的文件
                    if original_file == self.current_file:
                        continue

                    # 删除原始文件
                    os.remove(original_file)
                    print(f"已删除旧原始文件: {original_file}")

                    # 删除对应的结果文件
                    result_file = self.result_path_map.get(original_file)
                    if result_file and os.path.exists(result_file):
                        os.remove(result_file)
                        print(f"已删除对应的结果文件: {result_file}")

                    # 从已处理记录中移除
                    if original_file in self.processed_files:
                        del self.processed_files[original_file]
                    if original_file in self.results:
                        del self.results[original_file]
                    if original_file in self.result_path_map:
                        del self.result_path_map[original_file]

                except Exception as e:
                    print(f"删除文件失败: {e}")

        except Exception as e:
            print(f"清理旧文件时出错: {e}")

    def get_latest_result(self):
        """获取最新的分析结果"""
        return self.current_result

    def get_all_results(self):
        """获取所有分析结果（按时间排序，最新的在后）"""
        # 转换为列表并按时间排序
        results_list = list(self.results.values())
        results_list.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return results_list

    def get_result_by_filename(self, filename):
        """根据文件名获取分析结果"""
        for file_path, result in self.results.items():
            if os.path.basename(file_path) == filename:
                return result
        return None

    def get_status(self):
        """获取当前状态"""
        return {
            "status": self.status,
            "current_file": self.current_file,
            "processed_count": len(self.processed_files),
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    def stop(self):
        self.running = False


# 初始化文件夹监控线程
folder_monitor = FolderMonitorThread(AUTO_DETECT_FOLDER)
folder_monitor.daemon = True
folder_monitor.start()


@app.route('/')
def index():
    return render_template('index3.html')


@app.route('/detect', methods=['GET'])
def auto_detect():
    """获取最新的分析结果"""
    result = folder_monitor.get_latest_result()
    if result:
        return jsonify(result)
    else:
        return jsonify({
            "message": "等待文件夹中出现图片文件或首次分析中...",
            "status": folder_monitor.get_status()
        }), 202


@app.route('/results', methods=['GET'])
def get_all_results():
    """获取所有分析结果"""
    return jsonify(folder_monitor.get_all_results())


@app.route('/result/<filename>', methods=['GET'])
def get_result_by_filename(filename):
    """根据文件名获取分析结果"""
    result = folder_monitor.get_result_by_filename(filename)
    if result:
        return jsonify(result)
    else:
        return jsonify({"error": "未找到该文件的分析结果"}), 404


@app.route('/status', methods=['GET'])
def get_status():
    """获取系统状态"""
    return jsonify(folder_monitor.get_status())


@app.route('/result-image/<filename>', methods=['GET'])
def get_result_image(filename):
    """获取指定文件的结果图像"""
    result = folder_monitor.get_result_by_filename(filename)
    if result and "result_image_path" in result:
        result_path = result["result_image_path"]
        if os.path.exists(result_path):
            return send_file(result_path, mimetype='image/jpg')

    return send_file('./static/default.jpg', mimetype='image/jpg')

@app.route('/original-image/<filename>', methods=['GET'])
def get_original_image(filename):
    """获取指定文件的原始图像"""
    result = folder_monitor.get_result_by_filename(filename)
    if result and "file_path" in result:
        if os.path.exists(result["file_path"]):
            return send_file(result["file_path"], mimetype='image/jpg')

    return send_file('./static/default.jpg', mimetype='image/jpg')

@app.route('/has_new_results', methods=['GET'])
def has_new_results():
    """检查是否有新的分析结果"""
    try:
        # 获取上次请求的时间戳
        last_checked = request.args.get('timestamp')

        # 获取所有结果并按时间排序
        results_list = folder_monitor.get_all_results()

        if not results_list:
            return jsonify({"has_new": False, "timestamp": None})

        # 获取最新的结果时间戳
        latest_result = results_list[0]
        latest_timestamp = latest_result.get("timestamp", "")

        # 如果客户端没有提供时间戳，或者最新时间戳比客户端的新
        if not last_checked or latest_timestamp > last_checked:
            return jsonify({"has_new": True, "timestamp": latest_timestamp})
        else:
            return jsonify({"has_new": False, "timestamp": latest_timestamp})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

