#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 1: Search Reviews based on Experimental Description
======================================================
该脚本用于读取实验描述文件，调用 DeepSeek API 提取核心学术检索关键词，
然后使用 Semantic Scholar API 搜索相关的文献综述（Review），
去重后保存为 JSON 格式、纯 DOI 列表（TXT）和 BibTeX 格式（方便 Zotero 导入）。
"""

from __future__ import annotations

import os
import re
import sys
import json
import argparse
import urllib.request
import urllib.error
from datetime import datetime
from typing import Any, Dict, List, Set

# 导入 search_papers 里的 Semantic Scholar 搜索器
try:
    from search_papers import SemanticScholarSearcher
except ImportError:
    print("错误: 无法导入 search_papers.py。请确保 search_papers.py 与本脚本在同一目录下。")
    sys.exit(1)


# =====================================================================
# ⚙️ 核心配置区 (Configuration Section)
# =====================================================================
# DeepSeek API Key 存储文件的绝对路径（默认使用 D:\ARS\deepseek_api_key.txt）
DEEPSEEK_KEY_FILE_PATH = r"D:\ARS\deepseek_api_key.txt"

# Semantic Scholar API Key 存储文件的绝对路径（默认使用 D:\ARS\Semantic_Scholar_API.txt）
SEMANTIC_SCHOLAR_KEY_FILE_PATH = r"D:\ARS\Semantic_Scholar_API.txt"

# 第一轮检索限定的高影响力综述期刊列表 (包含官方全称和 ISO4 缩写，以确保 100% 检索成功)
REVIEW_JOURNALS = [
    "Chemical Reviews,Chem. Rev.",
    "Chemical Society Reviews,Chem. Soc. Rev.", 
    "Accounts of Chemical Research,Acc. Chem. Res.",
    "Nature Reviews Chemistry,Nat. Rev. Chem."
]
# =====================================================================


def read_text_file(filepath: str) -> str:
    """读取文本文件，支持 UTF-8, GBK, UTF-16 编码"""
    for encoding in ("utf-8", "gbk", "utf-16"):
        try:
            with open(filepath, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法解码文本文件 '{filepath}'，请确保其为 UTF-8 或 GBK 编码。")


def read_docx_file(filepath: str) -> str:
    """读取 DOCX 文件内容"""
    try:
        import docx
    except ImportError:
        print("\n" + "=" * 80)
        print(f"错误: 读取 DOCX 文件需要安装 'python-docx' 库。")
        print("请在终端运行以下命令安装:")
        print("    pip install python-docx")
        print("=" * 80 + "\n")
        raise ImportError("Missing dependency: python-docx")
    
    doc = docx.Document(filepath)
    return "\n".join([p.text for p in doc.paragraphs])


def read_pdf_file(filepath: str) -> str:
    """读取 PDF 文件内容"""
    try:
        import pypdf
    except ImportError:
        try:
            import PyPDF2 as pypdf  # 兼容旧版 PyPDF2
        except ImportError:
            print("\n" + "=" * 80)
            print(f"错误: 读取 PDF 文件需要安装 'pypdf' 库。")
            print("请在终端运行以下命令安装:")
            print("    pip install pypdf")
            print("=" * 80 + "\n")
            raise ImportError("Missing dependency: pypdf")
            
    reader = pypdf.PdfReader(filepath)
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text


def extract_text_from_file(filepath: str) -> str:
    """根据 file path 自动选择合适的方法提取文本"""
    if not os.path.exists(filepath):
        print("\n" + "!" * 80)
        print(f"[错误] 找不到指定的实验描述文件: '{filepath}'")
        print("请检查文件路径是否正确，或将实验描述文件放入该路径后再试。")
        print("!" * 80 + "\n")
        sys.exit(1)
        
    ext = os.path.splitext(filepath)[1].lower()
    print(f"正在读取实验描述文件: {filepath} ({ext.upper()} 格式)...")
    
    if ext == ".txt":
        return read_text_file(filepath)
    elif ext == ".docx":
        return read_docx_file(filepath)
    elif ext == ".pdf":
        return read_pdf_file(filepath)
    else:
        raise ValueError(f"不支持的文件格式: {ext}。仅支持 .txt, .docx, .pdf 格式。")


def call_deepseek_api(text: str, api_key: str) -> Dict[str, List[str]]:
    """调用 DeepSeek API 提取学术检索关键词（四维度结构化提取）"""
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    # 构造 Prompt，确保返回结构化 JSON
    prompt = f"""
You are an expert in scientific literature analysis.

Read the following research description and extract keywords from 4 dimensions:

1. **Materials/Systems**: specific compounds, materials, composites
2. **Methods/Techniques**: experimental or characterization methods  
3. **Phenomena/Mechanisms**: physical/chemical processes, effects
4. **Variables/Modulators**: parameters that control the outcome

Extract 2-3 keywords per dimension. Each keyword should be a short phrase (2-5 words).

Output as JSON:
{{
  "materials": [...],
  "methods": [...],
  "phenomena": [...],
  "variables": [...]
}}

Research description:
{text}
"""
    
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a helpful academic assistant that extracts structured search keywords from experimental descriptions. You always output valid JSON objects with four keys: 'materials', 'methods', 'phenomena', and 'variables'."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3
    }
    
    print("正在调用 DeepSeek API (deepseek-v4-flash) 提取结构化关键词...")
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
            content = resp_data["choices"][0]["message"]["content"].strip()
            
            # 清理可能存在的 markdown code block 标记
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            
            structured_keywords = json.loads(content.strip())
            if isinstance(structured_keywords, dict):
                # 规范化 key，确保包含四个维度
                normalized = {}
                for key in ("materials", "methods", "phenomena", "variables"):
                    val = structured_keywords.get(key) or []
                    if isinstance(val, list):
                        normalized[key] = [str(item).strip() for item in val if item]
                    else:
                        normalized[key] = [str(val).strip()] if val else []
                return normalized
            else:
                raise ValueError("API 返回的不是一个 JSON 对象")
    except urllib.error.HTTPError as e:
        print(f"DeepSeek API 请求失败 (HTTP {e.code}): {e.reason}")
        try:
            error_body = e.read().decode("utf-8")
            print(f"错误详情: {error_body}")
        except Exception:
            pass
        raise e
    except Exception as e:
        print(f"调用 DeepSeek API 发生错误: {e}")
        raise e


def generate_bibtex(papers: List[Dict[str, Any]]) -> str:
    """将文献列表转换为标准的 BibTeX 格式，方便 Zotero 导入"""
    bib_entries = []
    for idx, paper in enumerate(papers):
        title = paper.get("title") or "No Title"
        year = paper.get("year") or 2026
        
        # 解析作者
        authors_list = paper.get("authors") or []
        author_names = [auth.get("name") for auth in authors_list if auth.get("name")]
        
        if author_names:
            # 提取第一作者的最后一个单词（通常是姓氏）
            first_author = author_names[0].split()[-1]
            first_author = re.sub(r'[^a-zA-Z]', '', first_author)
            authors_str = " and ".join(author_names)
        else:
            first_author = "Unknown"
            authors_str = "Unknown Authors"
            
        # 提取标题的首单词作为 key 的一部分
        title_words = title.split()
        first_word = title_words[0] if title_words else "Paper"
        first_word = re.sub(r'[^a-zA-Z]', '', first_word)
        
        # 生成唯一的 Citation Key
        cite_key = f"{first_author}{year}{first_word}_{idx+1}"
        
        # 获取 DOI
        external_ids = paper.get("externalIds") or {}
        doi = external_ids.get("DOI") or external_ids.get("doi") or ""
        
        abstract = paper.get("abstract") or ""
        # 转义 BibTeX 中的特殊字符，防止格式损坏
        abstract_escaped = abstract.replace("{", "\\{").replace("}", "\\}").replace('"', "''")
        title_escaped = title.replace("{", "\\{").replace("}", "\\}")
        
        entry = f"@article{{{cite_key},\n"
        entry += f"  title = {{{title_escaped}}},\n"
        entry += f"  author = {{{authors_str}}},\n"
        entry += f"  year = {{{year}}},\n"
        entry += f"  journal = {{Semantic Scholar Review}},\n"
        if doi:
            entry += f"  doi = {{{doi}}},\n"
        if abstract:
            entry += f"  abstract = {{{abstract_escaped}}},\n"
        entry += "}"
        bib_entries.append(entry)
        
    return "\n\n".join(bib_entries)


def get_input_filepath() -> str:
    """获取用户输入的实验描述文件路径，支持手动输入/拖入，或者直接回车打开文件浏览器"""
    print("\n" + "=" * 80)
    print(" 实验描述文件选择：")
    print("  1. 直接输入或拖入文件路径（例如: D:\\ARS\\my_desc.txt）")
    print("  2. 直接按【回车】键，将自动打开文件浏览器供您选择文件")
    print("=" * 80)
    
    user_input = input("请输入路径或直接按回车进行浏览: ").strip()
    
    # 如果用户直接输入了路径，去除可能存在的首尾双引号（拖入文件时常见）
    if user_input:
        path = user_input.strip('"').strip("'")
        if os.path.exists(path):
            return path
        else:
            print(f"\n[错误] 您输入的路径不存在: '{path}'，请重新输入。")
            return get_input_filepath()
            
    # 如果用户直接回车，尝试打开标准 Tkinter 文件选择器
    print("\n正在打开文件选择器，请在弹出的窗口中选择您的实验描述文件...")
    try:
        import tkinter as tk
        from tkinter import filedialog
        
        # 强制初始化 Tkinter 运行环境
        root = tk.Tk()
        # 将窗口大小设为 0x0 并移动到屏幕外，彻底隐藏主窗口
        root.geometry("0x0+0+0")
        root.withdraw()
        
        # 强制让 Tk 窗口获得焦点，防止弹出的对话框被其他窗口（如 Cursor）遮挡
        root.deiconify()
        root.withdraw()
        root.focus_force()
        root.attributes("-topmost", True)
        
        file_path = filedialog.askopenfilename(
            parent=root,
            title="选择实验描述文件",
            filetypes=[
                ("所有支持的格式", "*.txt *.docx *.pdf"),
                ("文本文件 (*.txt)", "*.txt"),
                ("Word 文档 (*.docx)", "*.docx"),
                ("PDF 文档 (*.pdf)", "*.pdf"),
                ("所有文件", "*.*")
            ]
        )
        root.destroy()
        
        if file_path:
            # 转换为绝对路径，避免相对路径混淆
            abs_path = os.path.abspath(file_path)
            print(f"已成功选择文件: {abs_path}")
            return abs_path
        else:
            print("\n[提示] 您取消了文件选择，程序退出。")
            sys.exit(0)
    except Exception as e:
        print(f"\n无法打开图形化文件浏览器: {e}")
        # 如果图形界面报错（例如无 GUI 环境），退回到手动输入
        manual_path = input("请手动输入文件路径: ").strip().strip('"').strip("'")
        if os.path.exists(manual_path):
            return os.path.abspath(manual_path)
        else:
            print(f"\n[错误] 文件不存在: '{manual_path}'，程序退出。")
            sys.exit(1)


def get_deepseek_api_key() -> str:
    """获取 DeepSeek API Key，支持从配置的文件路径读取、环境变量读取，或交互式输入并自动保存"""
    api_file = DEEPSEEK_KEY_FILE_PATH
    
    # 1. 尝试从配置的文件路径读取
    print(f"正在尝试从配置文件路径读取 DeepSeek API Key: '{api_file}'...")
    if os.path.exists(api_file):
        try:
            with open(api_file, "r", encoding="utf-8") as f:
                key = f.read().strip()
                if key:
                    print(f"【读取成功】已成功从 '{api_file}' 读取并配置 DeepSeek API Key")
                    return key
        except Exception as e:
            print(f"读取 '{api_file}' 失败: {e}")
    else:
        print(f"提示: 未在指定路径 '{api_file}' 找到 API Key 文件。")
            
    # 2. 尝试从环境变量读取
    key = os.environ.get("deepseek_api_key") or os.environ.get("DEEPSEEK_API_KEY")
    if key:
        print("【读取成功】已成功从环境变量中读取并配置 DeepSeek API Key")
        return key
        
    # 3. 如果都没有找到，引导用户交互式输入，并自动保存到配置的路径中
    print("\n" + "!" * 80)
    print(" 未检测到 DeepSeek API Key！")
    print(" 为了方便您使用，您可以直接在下方输入您的 Key。")
    print(f" 输入后，程序会自动将其保存在您配置的路径中:\n '{api_file}'\n 下次运行无需重复输入。")
    print("!" * 80 + "\n")
    
    user_key = input("请输入您的 DeepSeek API Key (例如: sk-...): ").strip()
    if not user_key:
        print("\n[错误] API Key 不能为空，程序退出。")
        sys.exit(1)
        
    # 自动保存到配置的路径中
    try:
        # 确保父目录存在
        parent_dir = os.path.dirname(api_file)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(api_file, "w", encoding="utf-8") as f:
            f.write(user_key)
        print(f"【保存成功】您的 Key 已成功写入 '{api_file}'。")
    except Exception as e:
        print(f"警告: 自动保存 Key 到文件 '{api_file}' 失败: {e}")
        
    return user_key


def get_semantic_scholar_api_key() -> str | None:
    """从配置的文件路径读取 Semantic Scholar API Key"""
    api_file = SEMANTIC_SCHOLAR_KEY_FILE_PATH
    print(f"正在尝试从配置文件路径读取 Semantic Scholar API Key: '{api_file}'...")
    if os.path.exists(api_file):
        try:
            with open(api_file, "r", encoding="utf-8") as f:
                key = f.read().strip()
                if key:
                    print(f"【读取成功】已成功从 '{api_file}' 读取并配置 Semantic Scholar API Key")
                    return key
        except Exception as e:
            print(f"读取 '{api_file}' 失败: {e}")
    else:
        print(f"提示: 未在指定路径 '{api_file}' 找到 API Key 文件。")
    return None


def get_manual_keywords() -> List[str]:
    """获取用户手动输入的关键词列表，支持直接输入、拖入文件，或者直接回车打开文件浏览器选择关键词文件"""
    print("\n" + "=" * 80)
    print(" 📥 直接输入关键词模式：")
    print("  - 方式 A：直接输入关键词，多个关键词用【英文逗号】隔开")
    print("            （例如: gold nanoclusters, TEM, fluorescence quenching）")
    print("  - 方式 B：直接输入或拖入一个存有关键词的文本文件路径（支持 .txt）")
    print("  - 方式 C：直接按【回车】键，将自动打开文件浏览器供您选择关键词文本文件")
    print("=" * 80)
    
    user_input = input("请输入关键词/路径，或直接按回车进行浏览: ").strip()
    
    # 如果用户直接回车，尝试打开标准 Tkinter 文件选择器
    if not user_input:
        print("\n正在打开文件选择器，请在弹出的窗口中选择您的关键词文本文件...")
        try:
            import tkinter as tk
            from tkinter import filedialog
            
            root = tk.Tk()
            root.geometry("0x0+0+0")
            root.withdraw()
            
            root.deiconify()
            root.withdraw()
            root.focus_force()
            root.attributes("-topmost", True)
            
            file_path = filedialog.askopenfilename(
                parent=root,
                title="选择关键词文本文件",
                filetypes=[
                    ("文本文件 (*.txt)", "*.txt"),
                    ("所有文件", "*.*")
                ]
            )
            root.destroy()
            
            if file_path:
                abs_path = os.path.abspath(file_path)
                print(f"已成功选择文件: {abs_path}")
                cleaned_input = abs_path
            else:
                print("\n[提示] 您取消了文件选择，程序退出。")
                sys.exit(0)
        except Exception as e:
            print(f"\n无法打开图形化文件浏览器: {e}")
            cleaned_input = input("请手动输入关键词文件路径: ").strip().strip('"').strip("'")
    else:
        # 去除可能存在的首尾双引号（拖入文件时常见）
        cleaned_input = user_input.strip('"').strip("'")
    
    # 检查是否是存在的文件路径
    if os.path.exists(cleaned_input) and os.path.isfile(cleaned_input):
        print(f"\n正在从文件 '{cleaned_input}' 中读取关键词...")
        try:
            raw_kws = []
            with open(cleaned_input, "r", encoding="utf-8") as f:
                for line in f:
                    line_clean = line.strip()
                    if line_clean and not line_clean.startswith("#"):
                        raw_kws.append(line_clean)
            
            # 智能解析文件中的分隔符（支持换行、中英文逗号、中英文分号）
            kws = []
            for item in raw_kws:
                # 使用正则表达式将中文逗号，英文逗号，中文分号，英文分号统一替换为英文逗号
                normalized_item = re.sub(r'[，,；;]', ',', item)
                # 拆分并去除多余空格
                parts = [p.strip() for p in normalized_item.split(',') if p.strip()]
                kws.extend(parts)
                
            if kws:
                print(f"成功从文件中读取并解析出 {len(kws)} 个关键词。")
                return kws
            else:
                print("\n[错误] 文件内容为空，请重新输入。")
                return get_manual_keywords()
        except Exception as e:
            print(f"读取关键词文件失败: {e}")
            return get_manual_keywords()
            
    # 否则，按逗号分割
    kws = [k.strip() for k in cleaned_input.split(",") if k.strip()]
    if kws:
        print(f"成功识别到 {len(kws)} 个关键词。")
        return kws
    else:
        print("\n[错误] 无法识别任何关键词，请重新输入。")
        return get_manual_keywords()


def get_manual_dois() -> List[str]:
    """获取用户手动输入的 DOI 列表，支持直接贴入多个 DOI，或者直接回车打开文件浏览器选择文本文件"""
    print("\n" + "=" * 80)
    print(" 📑 DOI 直接导入模式：")
    print("  - 方式 A：直接贴入多个 DOI（可以用空格、换行或中英文逗号/分号隔开）")
    print("            （例如: 10.1039/c8cs00740c, 10.1021/acs.accounts.0c00706）")
    print("  - 方式 B：输入或拖入一个存有 DOI 的文本文件路径（支持 .txt）")
    print("  - 方式 C：直接按【回车】键，将自动打开文件浏览器供您选择关键词文本文件")
    print("=" * 80)
    
    user_input = input("请输入 DOI 列表/路径，或直接按回车进行浏览: ").strip()
    
    # 如果用户直接回车，尝试打开 standard Tkinter 文件选择器
    if not user_input:
        print("\n正在打开文件选择器，请在弹出的窗口中选择您的 DOI 文本文件...")
        try:
            import tkinter as tk
            from tkinter import filedialog
            
            root = tk.Tk()
            root.geometry("0x0+0+0")
            root.withdraw()
            
            root.deiconify()
            root.withdraw()
            root.focus_force()
            root.attributes("-topmost", True)
            
            file_path = filedialog.askopenfilename(
                parent=root,
                title="选择 DOI 文本文件",
                filetypes=[
                    ("文本文件 (*.txt)", "*.txt"),
                    ("所有文件", "*.*")
                ]
            )
            root.destroy()
            
            if file_path:
                abs_path = os.path.abspath(file_path)
                print(f"已成功选择文件: {abs_path}")
                cleaned_input = abs_path
            else:
                print("\n[提示] 您取消了文件选择，程序退出。")
                sys.exit(0)
        except Exception as e:
            print(f"\n无法打开图形化文件浏览器: {e}")
            cleaned_input = input("请手动输入 DOI 文件路径: ").strip().strip('"').strip("'")
    else:
        # 去除可能存在的首尾双引号（拖入文件时常见）
        cleaned_input = user_input.strip('"').strip("'")
    
    # 检查是否是存在的文件路径
    if os.path.exists(cleaned_input) and os.path.isfile(cleaned_input):
        print(f"\n正在从文件 '{cleaned_input}' 中读取 DOI...")
        try:
            raw_dois = []
            with open(cleaned_input, "r", encoding="utf-8") as f:
                for line in f:
                    line_clean = line.strip()
                    if line_clean and not line_clean.startswith("#"):
                        raw_dois.append(line_clean)
            
            # 智能解析文件中的分隔符
            dois = []
            for item in raw_dois:
                # 统一替换中英文逗号、中英文分号、换行，拆分
                normalized_item = re.sub(r'[，,；;\s]+', ',', item)
                parts = [p.strip() for p in normalized_item.split(',') if p.strip()]
                dois.extend(parts)
                
            if dois:
                print(f"成功从文件中读取并解析出 {len(dois)} 个 DOI。")
                return dois
            else:
                print("\n[错误] 文件内容为空，请重新输入。")
                return get_manual_dois()
        except Exception as e:
            print(f"读取 DOI 文件失败: {e}")
            return get_manual_dois()
            
    # 否则，智能解析直接输入的文本
    normalized_input = re.sub(r'[，,；;\s]+', ',', cleaned_input)
    dois = [d.strip() for d in normalized_input.split(",") if d.strip()]
    if dois:
        print(f"成功识别到 {len(dois)} 个 DOI。")
        return dois
    else:
        print("\n[错误] 无法识别任何 DOI，请重新输入。")
        return get_manual_dois()


def main() -> None:
    # 1. 命令行参数解析
    parser = argparse.ArgumentParser(description="Step 1: 实验描述文献自动检索与去重工具")
    parser.add_argument(
        "--input", "-i", 
        type=str, 
        default=None, 
        help="实验描述文件路径 (支持 .txt, .docx, .pdf，若不指定且未指定 --keywords 则进入交互式选择)"
    )
    parser.add_argument(
        "--keywords", "-k",
        type=str,
        nargs="+",
        default=None,
        help="直接指定检索关键词列表（用空格隔开，例如: -k 'gold nanoclusters' 'TEM'。指定此参数将跳过 DeepSeek 提取）"
    )
    parser.add_argument(
        "--limit", "-l", 
        type=int, 
        default=2, 
        help="每个关键词检索的文献篇数 (默认: 2 篇)"
    )
    parser.add_argument(
        "--pub-types", "-t", 
        type=str, 
        nargs="+", 
        default=["Review"], 
        help="过滤文献类型 (例如: Review, Journal, Conference，默认: Review)"
    )
    parser.add_argument(
        "--output", "-o", 
        type=str, 
        default="./output", 
        help="输出文件保存目录 (默认: ./output)"
    )
    
    args = parser.parse_args()

    print("=" * 80)
    print("                Step 1: 文献综述自动检索与去重工具")
    print("=" * 80)

    keywords = []
    dois = []
    structured_keywords = None
    input_file = args.input
    run_mode = "1"  # 默认智能模式
    
    # 优先检查命令行是否直接传入了关键词
    if args.keywords:
        # 如果传入的是单个元素且是存在的文件路径，则从文件中读取
        if len(args.keywords) == 1 and os.path.exists(args.keywords[0]):
            file_path = args.keywords[0]
            print(f"检测到通过命令行传入的关键词文件: '{file_path}'，正在读取...")
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    keywords = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
            except Exception as e:
                print(f"[错误] 读取关键词文件失败: {e}")
                sys.exit(1)
        else:
            keywords = args.keywords
        print(f"【直接模式】已通过命令行直接指定 {len(keywords)} 个检索关键词。")
        structured_keywords = {"manual_input": keywords}
        run_mode = "2"
        
    # 如果命令行没有直接指定关键词，且指定了输入文件，则走 DeepSeek 智能提取模式
    elif args.input:
        input_file = args.input
        print(f"【智能模式】已通过命令行指定实验描述文件: '{input_file}'")
        run_mode = "1"
        
    # 如果命令行什么都没指定，进入交互式选择界面
    else:
        print("\n请选择运行模式：")
        print("  1. 🧠 智能模式：读取实验描述文件，调用 DeepSeek 提取关键词（需要 DeepSeek API Key）")
        print("  2. 📥 直接模式：直接手动输入关键词，或从已有的关键词文本文件中读取（无需 DeepSeek）")
        print("  3. 📑 DOI 直接导入：直接输入已确定的文献 DOI，自动获取完整元数据（无需 DeepSeek）")
        print("=" * 80)
        user_mode = input("请选择模式 [1/2/3] (默认 1): ").strip()
        
        if user_mode == "2":
            keywords = get_manual_keywords()
            structured_keywords = {"manual_input": keywords}
            run_mode = "2"
        elif user_mode == "3":
            dois = get_manual_dois()
            keywords = dois  # 保存时直接输出这些 DOI
            structured_keywords = {"imported_dois": dois}
            run_mode = "3"
        else:
            # 智能模式，需要用户选择实验描述文件
            input_file = get_input_filepath()
            run_mode = "1"

    # 如果是智能模式（尚未获取关键词），执行 DeepSeek 提取
    if run_mode == "1" and not keywords:
        # 确保有输入文件
        if not input_file:
            input_file = get_input_filepath()
            
        # 读取实验描述文本
        try:
            exp_text = extract_text_from_file(input_file)
            print(f"成功提取文本，共 {len(exp_text)} 个字符。")
        except Exception as e:
            print(f"读取实验描述文件失败: {e}")
            sys.exit(1)
            
        # 智能提取模式，读取 DeepSeek API Key
        ds_api_key = get_deepseek_api_key()
        try:
            structured_keywords = call_deepseek_api(exp_text, ds_api_key)
            
            # 展平成一个扁平列表，用于后续的文献检索
            keywords = []
            print("\n" + "=" * 40)
            print(" 成功提取到结构化关键词：")
            print("=" * 40)
            for category, kws in structured_keywords.items():
                category_zh = {
                    "materials": "材料/系统 (Materials/Systems)",
                    "methods": "方法/技术 (Methods/Techniques)",
                    "phenomena": "现象/机制 (Phenomena/Mechanisms)",
                    "variables": "变量/调节剂 (Variables/Modulators)"
                }.get(category, category)
                
                print(f"【{category_zh}】:")
                for kw in kws:
                    print(f"  - {kw}")
                    keywords.append(kw)
            print("=" * 40)
            print(f"共提取到 {len(keywords)} 个核心学术检索关键词。")
        except Exception as e:
            print(f"提取关键词失败: {e}")
            sys.exit(1)

    # 打印最终配置参数
    print("\n" + "=" * 80)
    print(f"【最终配置参数】:")
    if run_mode == "3":
        print(f"  - 运行模式: DOI 直接导入模式")
        print(f"  - 导入 DOI 数量: {len(dois)} 个")
    elif input_file:
        print(f"  - 实验描述文件: {input_file}")
        print(f"  - 检索关键词数: {len(keywords)} 个")
        print(f"  - 每词检索数量: {args.limit} 篇")
        print(f"  - 过滤文献类型: {', '.join(args.pub_types)}")
    else:
        print(f"  - 运行模式: 直接关键词模式 (跳过实验描述与 DeepSeek 提取)")
        print(f"  - 检索关键词数: {len(keywords)} 个")
        print(f"  - 每词检索数量: {args.limit} 篇")
        print(f"  - 过滤文献类型: {', '.join(args.pub_types)}")
    print(f"  - 输出保存目录: {args.output}")
    print("=" * 80)
        
    # 4. 初始化 Semantic Scholar 搜索器
    print("\n正在初始化 Semantic Scholar 搜索客户端...")
    s2_key = get_semantic_scholar_api_key()
    searcher = SemanticScholarSearcher(api_key=s2_key)
    
    # 5. 循环检索/获取文献
    all_papers: List[Dict[str, Any]] = []
    
    if run_mode == "3":
        print(f"\n开始获取这 {len(dois)} 个 DOI 的文献元数据...")
        for idx, doi in enumerate(dois, 1):
            doi_clean = doi.strip()
            if not doi_clean:
                continue
            print(f"[{idx}/{len(dois)}] 正在获取 DOI 文献: '{doi_clean}'...")
            encoded_doi = urllib.parse.quote(doi_clean)
            url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{encoded_doi}?fields=title,authors,year,citationCount,externalIds,abstract"
            try:
                # 频控在 _make_request 内部自动处理
                paper_data = searcher._make_request(url)
                if paper_data and "title" in paper_data:
                    paper_data["matched_keywords"] = ["Direct DOI Import"]
                    all_papers.append(paper_data)
                    print(f"  ➜ 成功获取: '{paper_data.get('title')}'")
                else:
                    print(f"  ⚠️ 未能在 Semantic Scholar 找到该 DOI 对应的文献元数据。")
            except Exception as e:
                print(f"  ⚠️ 获取 DOI '{doi_clean}' 失败: {e}")
    else:
        print(f"\n开始依次检索每个关键词的文献 (每个关键词获取前 {args.limit} 篇)...")
        print(f"提示: 第一轮检索已限定高影响力综述期刊: {', '.join(REVIEW_JOURNALS)}")
        
        for idx, kw in enumerate(keywords, 1):
            print(f"\n[{idx}/{len(keywords)}] 正在检索关键词: '{kw}'")
            try:
                # 搜索指定类型的文献，并限定高影响力综述期刊
                papers = searcher.search_papers(kw, limit=args.limit, publication_types=args.pub_types, venues=REVIEW_JOURNALS)
                
                if not papers:
                    print(f"  ⚠️ 关键词 '{kw}' 未检索到任何文献。")
                else:
                    print(f"  ➜ 成功检索到 {len(papers)} 篇文献。")
                    
                # 为这些文献打上匹配的关键词标签
                for p in papers:
                    if "matched_keywords" not in p:
                        p["matched_keywords"] = []
                    if kw not in p["matched_keywords"]:
                        p["matched_keywords"].append(kw)
                        
                all_papers.extend(papers)
            except Exception as e:
                print(f"检索关键词 '{kw}' 时发生错误: {e}，将跳过此词。")
            
    # 6. 按 DOI 和 Paper ID 去重
    print("\n正在对检索到的文献进行去重合并...")
    unique_papers: List[Dict[str, Any]] = []
    
    # 使用字典来辅助合并相同文献的关键词标签
    doi_to_paper: Dict[str, Dict[str, Any]] = {}
    id_to_paper: Dict[str, Dict[str, Any]] = {}
    
    for paper in all_papers:
        paper_id = paper.get("paperId")
        external_ids = paper.get("externalIds") or {}
        doi = external_ids.get("DOI") or external_ids.get("doi")
        
        existing_paper = None
        
        # 优先按 DOI 查找是否已存在
        if doi:
            doi_clean = doi.strip().lower()
            if doi_clean in doi_to_paper:
                existing_paper = doi_to_paper[doi_clean]
        # 其次按 Paper ID 查找
        elif paper_id:
            if paper_id in id_to_paper:
                existing_paper = id_to_paper[paper_id]
                
        if existing_paper:
            # 如果文献已存在，则将当前关键词合并到已有文献的 matched_keywords 中
            for kw in paper.get("matched_keywords", []):
                if kw not in existing_paper["matched_keywords"]:
                    existing_paper["matched_keywords"].append(kw)
        else:
            # 如果是新文献，加入去重列表并建立索引
            unique_papers.append(paper)
            if doi:
                doi_to_paper[doi.strip().lower()] = paper
            if paper_id:
                id_to_paper[paper_id] = paper
                
    print(f"去重完成！原始文献数: {len(all_papers)} 篇 -> 去重后文献数: {len(unique_papers)} 篇。")
    
    # 7. 创建输出目录并保存结果
    os.makedirs(args.output, exist_ok=True)
    
    # 生成当前时间戳，防止下一次的数据被冲掉
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 保存提取出来的结构化关键词列表 (JSON)
    keywords_json_path = os.path.join(args.output, f"keywords_{timestamp}.json")
    with open(keywords_json_path, "w", encoding="utf-8") as f:
        json.dump(structured_keywords, f, indent=2, ensure_ascii=False)
        
    # 保存提取出来的扁平关键词列表 (TXT)
    keywords_txt_path = os.path.join(args.output, f"keywords_{timestamp}.txt")
    with open(keywords_txt_path, "w", encoding="utf-8") as f:
        for kw in keywords:
            f.write(f"{kw}\n")
    
    # 保存去重后的文献列表为 JSON
    json_path = os.path.join(args.output, f"papers_{timestamp}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(unique_papers, f, indent=2, ensure_ascii=False)
        
    # 保存纯 DOI 列表为 TXT (方便在 Zotero 中通过 "Add Item by Identifier" 批量导入)
    doi_path = os.path.join(args.output, f"dois_{timestamp}.txt")
    valid_dois = []
    for paper in unique_papers:
        external_ids = paper.get("externalIds") or {}
        doi = external_ids.get("DOI") or external_ids.get("doi")
        if doi:
            valid_dois.append(doi.strip())
            
    with open(doi_path, "w", encoding="utf-8") as f:
        for doi in valid_dois:
            f.write(f"{doi}\n")
            
    # 保存为标准的 BibTeX 格式 (方便 Zotero 直接导入)
    bib_path = os.path.join(args.output, f"papers_{timestamp}.bib")
    bib_content = generate_bibtex(unique_papers)
    with open(bib_path, "w", encoding="utf-8") as f:
        f.write(bib_content)
        
    # 8. 打印成功报告
    print("\n" + "=" * 80)
    print("🎉 任务圆满完成！所有文献及关键词已妥善保存。")
    print("=" * 80)
    print(f"【结构化关键词 (JSON)】: {os.path.abspath(keywords_json_path)}")
    print(f"【扁平关键词   (TXT) 】: {os.path.abspath(keywords_txt_path)}")
    print(f"【文献列表     (JSON)】: {os.path.abspath(json_path)}")
    print(f"【DOI 列表     (TXT) 】: {os.path.abspath(doi_path)}  (共 {len(valid_dois)} 个有效 DOI)")
    print(f"【BibTeX 格式   (BIB) 】: {os.path.abspath(bib_path)}  (支持完整元数据导入)")
    print("-" * 80)
    print("💡 Zotero 快速导入指南:")
    print("1. 批量自动下载 PDF 与元数据 (最推荐):")
    print(f"   打开 Zotero，点击顶部的 'Add Item(s) by Identifier' 按钮 (小魔棒图标)，")
    print(f"   复制 '{os.path.basename(doi_path)}' 文件中的所有 DOI 并粘贴进去，按回车即可一键下载并导入。")
    print("2. 导入完整文献信息:")
    print("   在 Zotero 中点击 'File -> Import'，选择 'A file'，然后选中上面生成的 '.bib' 文件导入。")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n用户中止了程序。")
        sys.exit(0)
    except Exception as e:
        print(f"\n程序运行中发生异常: {e}")
        sys.exit(1)
