import os
def saveImage(ImagePath):
    result_dir = './static/result/'
    os.makedirs(result_dir, exist_ok=True)
    # 生成动态文件名
    # 提取原始文件名（不含扩展名）
    original_filename = os.path.splitext(os.path.basename(ImagePath))[0]
    # 构建新文件名：原始名_result.jpg
    result_filename = f"{original_filename}_result.jpg"
    result_path = os.path.join(result_dir, result_filename)

    return result_path