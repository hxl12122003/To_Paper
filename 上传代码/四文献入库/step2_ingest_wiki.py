#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 2: Pure Physical-Driven Literature Library Ingester (100% Decoupled from CSV)
========================================================================================
1. 【零 CSV 依赖】：完全斩断与任何 *_info.csv 的关联，纯物理扫描任意指定的 PDF 文件夹 (Chaos Zone)。
2. 【高能格式校验】：排除小于 10KB 或者是假 PDF (不含 %PDF 头) 的报错网页或垃圾文件。
3. 【智能 DOI 物理逆向捕获】：
   - 第一级：物理读取 PDF 前两页文本，利用学术正则直接精准匹配以 10. 开头的合法 DOI。
   - 第二级：原文件名 DOI 探测。如果文本提取失败，尝试对原文件名利用正则探测并智能还原 (如将 Windows 非法的 '_' 还原为 '/') 以重建 DOI。
4. 【大模型标题提取 (兜底)】：
   - 第三级：如果以上均无法获得 DOI，自动读取 PDF 前两页文本送入 DeepSeek，逆向识别并提取最纯净的官方英文标题。
5. 【Semantic Scholar 权威对齐与自动纠偏】：
   - 利用 DOI 或大模型标题检索 Semantic Scholar (带 10 次指数退避重试，防 429 频控限制)。
   - 如果是通过标题检索成功，且官方元数据中包含 DOI，则自动补全和升级文献为“有 DOI 的高信度文献”。
6. 【全局增量去重对账】：
   - 全局对账账本 `D:\ARS\Literature_Library\master_registry.json` 自动维护。
   - 优先以 DOI 比对，次之以 Title（标准化去除非字母数字字符后）比对，已入库的文献自动秒级跳过，永不重复拷贝物理文件。
7. 【无损规范拷贝与隔离】：
   - 成功对齐的文献拷贝到 `PDFs_Processed/` 并重命名为规范学术名 `[年份] 作者 - 标题.pdf`。
   - 完全识别失败、检索不到或断网的文献，无残留、不污染主库，直接无损拷贝到隔离区 `Failed_Ingestion/`，保持原文件名，以便人工排查。
"""

from __future__ import annotations

import os
import sys
import re
import json
import shutil
import hashlib
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Set, Tuple

# =====================================================================
# ⚙️ 核心配置区 (Configuration Section)
# =====================================================================
# 默认扫描的零散/新下载文献下载目录 (Chaos Zone)
# 这个目录可以是任何地方，不再需要任何 csv 文件
DEFAULT_SEARCH_ROOT = r"D:\ARS\AutoSci-main\wiki\outputs\batch_search\llm_filtered_results\dois_by_score"

# 统一、永久的文献库根目录 (Sanctuary Zone)
LIBRARY_ROOT = Path(r"D:\ARS\Literature_Library")

# DeepSeek API Key 存储文件的绝对路径
DEEPSEEK_KEY_FILE_PATH = r"D:\ARS\deepseek_api_key.txt"

# Semantic Scholar API Key 存储文件的绝对路径
SEMANTIC_SCHOLAR_KEY_FILE_PATH = r"D:\ARS\Semantic_Scholar_API.txt"
# =====================================================================


def get_deepseek_api_key() -> str | None:
    """获取 DeepSeek API Key"""
    api_file = Path(DEEPSEEK_KEY_FILE_PATH)
    if api_file.exists():
        try:
            return api_file.read_text(encoding="utf-8").strip() or None
        except Exception:
            pass
    return os.environ.get("DEEPSEEK_API_KEY")


def get_semantic_scholar_api_key() -> str | None:
    """获取 Semantic Scholar API Key"""
    api_file = Path(SEMANTIC_SCHOLAR_KEY_FILE_PATH)
    if api_file.exists():
        try:
            return api_file.read_text(encoding="utf-8").strip() or None
        except Exception:
            pass
    return os.environ.get("S2_API_KEY")


def clean_filename(filename: str, max_len: int = 120) -> str:
    """清洗 Windows 文件名中的非法字符，并限制长度防止 Windows 路径超长"""
    cleaned = re.sub(r'[\\/*?:"<>|]', " ", filename)
    cleaned = re.sub(r'\s+', " ", cleaned).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len-3].strip() + "..."
    return cleaned


def is_valid_pdf(file_path: Path) -> bool:
    """检查文件是否为真实的 PDF（防止下到报错网页 HTML）"""
    if not file_path.exists():
        return False
    if file_path.stat().st_size < 10000:  # 官方报错网页通常小于 10KB
        return False
    try:
        with open(file_path, "rb") as f:
            return f.read(4) == b"%PDF"
    except Exception:
        return False


def extract_pdf_first_two_pages(pdf_path: Path) -> str:
    """提取 PDF 前两页的文本，用于提取 DOI和大模型识别标题"""
    import fitz
    try:
        doc = fitz.open(str(pdf_path))
        text = ""
        for i in range(min(2, len(doc))):
            text += doc[i].get_text() or ""
        doc.close()
        return text.strip()
    except Exception as e:
        print(f"    ⚠️ 读取 PDF 前两页文本失败: {e}")
        return ""


def extract_doi_from_pdf_text(text: str) -> str | None:
    """直接从 PDF 文本内容中，利用正则精准逆向提取合法的学术 DOI (以 10. 开头)"""
    if not text:
        return None
    # 匹配学术 DOI 的标准正则：以 10. 紧跟 4-9 位数字，再以 / 分割，其后是非空白的标识路径
    # 注意：在字符集中，为了防止 hyphen-minus (-) 被解析为范围，必须将其放在最开头 [-...]
    pattern = r'\b(10\.\d{4,9}/[-_a-zA-Z0-9.;()/:%#\+\=]+)'
    matches = re.findall(pattern, text)
    for m in matches:
        # 清理结尾可能包含的标点符号或空白（例如句尾的句号、括号等）
        m_clean = m.rstrip('.,;()[]{}<> \t\n\r')
        if m_clean.count('/') >= 1:
            if m_clean.startswith("10."):
                return m_clean
    return None


def extract_doi_from_filename(filename: str) -> str | None:
    """
    如果原文件名以 '10.' 开头且包含 '#' 号，则将文件名中的所有 '#' 号替换为 '/'。
    这允许用户手动将 DOI 中的斜杠 '/' 替换为 '#'（因为 DOI 中绝不会自然含有 '#'，而下划线和短横线在 DOI 中很常见）。
    例如：用户将文件重命名为 '10.1007#s12598-025-03340-9.pdf'
    程序会自动还原出完整的 DOI：'10.1007/s12598-025-03340-9'
    """
    fn_clean = filename.strip()
    if fn_clean.startswith("10.") and "#" in fn_clean:
        # 将文件名中的所有 '#' 替换为 '/'
        reconstructed_doi = fn_clean.replace("#", "/")
        return reconstructed_doi
    return None


def extract_title_via_llm(pdf_text: str, ds_key: str | None) -> str | None:
    """调用 DeepSeek 大模型，从 PDF 前两页提取出论文英文标题"""
    if not ds_key or not pdf_text:
        return None
    
    # 截取前 3000 字符，足够容纳前一至两页的重要元数据区域
    sample_text = pdf_text[:3000].strip()
    if not sample_text:
        return None
        
    prompt = (
        "你是一个专业的学术文献助手。以下是从一篇学术论文的 PDF 前两页中提取的原始文本。\n"
        "请在这段高度结构化的文本中，准确识别并提取这篇论文的【唯一官方英文标题】(English Paper Title)。\n\n"
        "【约束条件】:\n"
        "1. 仅输出论文的英文标题，不要包含任何多余的前言、解释、标点、说明、注释或 Markdown 格式（例如不要输出：这里是标题：xxx）。\n"
        "2. 不要包含作者姓名、机构、期刊名称、会议名称或摘要信息，只要最纯净的标题本身。\n"
        "3. 保持原本的学术英文拼写与大小写规范，不要自己做翻译。\n\n"
        "【原始文本】:\n"
        f"{sample_text}\n\n"
        "【英文标题】:"
    )
    
    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ds_key}"
        }
        body = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0,
            "max_tokens": 150
        }
        
        req = urllib.request.Request(
            url, 
            data=json.dumps(body).encode("utf-8"), 
            headers=headers
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices") or []
            if choices:
                extracted = choices[0].get("message", {}).get("content", "").strip()
                # 剔除可能带有的引号、星号或 Markdown 加粗等符号
                extracted = re.sub(r'^["\'`*#\s]+|["\'`*#\s]+$', '', extracted).strip()
                # 再次过滤一些常见前缀
                extracted = re.sub(r'^(Title|Paper Title|English Title|Document Title)[:：\s]+', '', extracted, flags=re.IGNORECASE)
                if extracted:
                    return extracted
    except Exception as e:
        print(f"    ⚠️ 调用 DeepSeek 提取标题发生异常: {e}")
    return None


def normalize_title_for_dedup(t: str) -> str:
    """为精确去重而清洗/标准化标题：只保留字母与数字"""
    return re.sub(r'[^a-z0-9]', '', t.lower().strip())


def clean_words(s: str) -> set[str]:
    """清洗字符串：转为小写，提取字母和数字，过滤掉常见的介词、学术停用词"""
    s = s.lower()
    words = re.findall(r'[a-z0-9]+', s)
    stopwords = {
        "and", "the", "with", "from", "for", "the", "that", "this", "these",
        "their", "of", "in", "on", "at", "by", "an", "is", "are", "was", "were",
        "be", "been", "has", "have", "had", "as", "into", "through", "using", "used"
    }
    return {w for w in words if w not in stopwords and len(w) > 2}


def fetch_metadata_via_doi(doi: str, ss_key: str | None) -> Dict[str, Any] | None:
    """调用 Semantic Scholar API，通过 DOI 获取官方完整的文献元数据（带退避指数重试功能，防 429 频控）"""
    encoded_doi = urllib.parse.quote(doi)
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{encoded_doi}?fields=title,authors,year,citationCount,externalIds,abstract,publicationTypes,venue"
    headers = {"User-Agent": "ARS-PaperSearcher/1.0"}
    if ss_key:
        headers["x-api-key"] = ss_key
        
    req = urllib.request.Request(url, headers=headers)
    
    max_retries = 10
    backoff_factor = 2.0
    
    for attempt in range(1, max_retries + 1):
        try:
            time.sleep(1.5)  # 基础延迟 1.5 秒，保持平稳
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data and "title" in data:
                    formatted = {
                        "paperId": data.get("paperId", hashlib.md5(doi.encode()).hexdigest()),
                        "externalIds": data.get("externalIds") or {"DOI": doi},
                        "title": data.get("title"),
                        "year": data.get("year"),
                        "citationCount": data.get("citationCount", 0),
                        "venue": data.get("venue") or "",
                        "authors": data.get("authors") or [],
                        "abstract": data.get("abstract", ""),
                        "publicationTypes": data.get("publicationTypes") or [],
                        "matched_keywords": ["DOI Ingestion"]
                    }
                    return formatted
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"  ℹ️ S2 数据库未收录此 DOI (HTTP 404)。")
                return None
            elif e.code == 429:
                sleep_time = min(3600.0, 10.0 * (backoff_factor ** (attempt - 1)))
                print(f"  ⚠️ 触发 API 频控 (HTTP 429)。将在 {sleep_time:.1f} 秒后进行第 {attempt}/{max_retries} 次指数退避重试...")
                time.sleep(sleep_time)
            else:
                sleep_time = min(3600.0, 10.0 * (backoff_factor ** (attempt - 1)))
                print(f"  ⚠️ S2 接口返回 HTTP {e.code} 错误。将在 {sleep_time:.1f} 秒后进行第 {attempt}/{max_retries} 次重试...")
                if attempt == max_retries:
                    return None
                time.sleep(sleep_time)
        except Exception as e:
            sleep_time = min(3600.0, 10.0 * (backoff_factor ** (attempt - 1)))
            print(f"  ⚠️ 联网请求异常: {e}。将在 {sleep_time:.1f} 秒后进行第 {attempt}/{max_retries} 次重试...")
            if attempt == max_retries:
                return None
            time.sleep(sleep_time)
    return None


def fetch_metadata_via_title(title: str, ss_key: str | None) -> Dict[str, Any] | None:
    """调用 Semantic Scholar API，通过 Title 搜索官方文献元数据（带退避指数重试功能，防 429 频控）"""
    encoded_title = urllib.parse.quote(title)
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={encoded_title}&limit=3&fields=title,authors,year,citationCount,externalIds,abstract,publicationTypes,venue"
    headers = {"User-Agent": "ARS-PaperSearcher/1.0"}
    if ss_key:
        headers["x-api-key"] = ss_key
        
    req = urllib.request.Request(url, headers=headers)
    
    max_retries = 10
    backoff_factor = 2.0
    
    for attempt in range(1, max_retries + 1):
        try:
            time.sleep(1.5)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                papers = data.get("data") or []
                if not papers:
                    return None
                
                target_words = clean_words(title)
                for paper in papers:
                    p_title = paper.get("title", "")
                    p_words = clean_words(p_title)
                    if not p_words:
                        continue
                    
                    # 相似度安全阀值：词汇交集占比 >= 0.85
                    score = len(target_words.intersection(p_words)) / min(len(target_words), len(p_words))
                    if score >= 0.85:
                        formatted = {
                            "paperId": paper.get("paperId"),
                            "externalIds": paper.get("externalIds") or {},
                            "title": paper.get("title"),
                            "year": paper.get("year"),
                            "citationCount": paper.get("citationCount", 0),
                            "venue": paper.get("venue") or "",
                            "authors": paper.get("authors") or [],
                            "abstract": paper.get("abstract", ""),
                            "publicationTypes": paper.get("publicationTypes") or [],
                            "matched_keywords": ["Title Search Recovered"]
                        }
                        return formatted
                return None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"  ℹ️ S2 数据库未收录此标题 (HTTP 404)。")
                return None
            elif e.code == 429:
                sleep_time = min(3600.0, 10.0 * (backoff_factor ** (attempt - 1)))
                print(f"  ⚠️ 触发 API 频控 (HTTP 429)。将在 {sleep_time:.1f} 秒后进行第 {attempt}/{max_retries} 次指数退避重试...")
                time.sleep(sleep_time)
            else:
                sleep_time = min(3600.0, 10.0 * (backoff_factor ** (attempt - 1)))
                print(f"  ⚠️ S2 接口返回 HTTP {e.code} 错误。将在 {sleep_time:.1f} 秒后进行第 {attempt}/{max_retries} 次重试...")
                if attempt == max_retries:
                    return None
                time.sleep(sleep_time)
        except Exception as e:
            sleep_time = min(3600.0, 10.0 * (backoff_factor ** (attempt - 1)))
            print(f"  ⚠️ 联网请求异常: {e}。将在 {sleep_time:.1f} 秒后进行第 {attempt}/{max_retries} 次重试...")
            if attempt == max_retries:
                return None
            time.sleep(sleep_time)
    return None


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    print("=" * 80)
    print("🪐 Step 2: 正在初始化全新物理文件驱动文献永久入库程序 (100% 斩断 CSV 依赖)")
    print("=" * 80)

    # 0. 检查并打印 API Key 加载状态
    ss_key = get_semantic_scholar_api_key()
    ds_key = get_deepseek_api_key()
    print(f"[*] Semantic Scholar API Key: {'已成功加载 (x-api-key 启用)' if ss_key else '未检测到 (将使用无 Key 限制模式)'}")
    print(f"[*] DeepSeek API Key: {'已成功加载' if ds_key else '未检测到 (无大模型逆向解析标题能力)'}")
    print(f"[*] 永久文献库根目录: '{LIBRARY_ROOT}'")
    print("-" * 80)

    # 1. 解析要扫描的物理源文件夹路径
    if len(sys.argv) > 1:
        target_path = Path(sys.argv[1])
    else:
        target_path = Path(DEFAULT_SEARCH_ROOT)

    if not target_path.exists():
        print(f"❌ 错误: 找不到目标扫描路径 '{target_path}'。")
        sys.exit(1)

    print(f"🔍 正在执行物理扫描，源文件夹: '{target_path.resolve()}'")

    # 2. 递归扫描所有的 .pdf 文件
    all_pdfs = [p for p in target_path.rglob("*.pdf") if p.is_file()]
    print(f"  ➜ 共搜寻到 {len(all_pdfs)} 个 PDF 物理文件。")

    if not all_pdfs:
        print("ℹ️ 该目录下未发现任何 PDF 文件，程序退出。")
        sys.exit(0)

    # 3. 初始化永久文献库物理目标目录与对账账本
    processed_pdf_dir = LIBRARY_ROOT / "PDFs_Processed"
    metadata_dir = LIBRARY_ROOT / "Metadata"
    failed_ingest_dir = LIBRARY_ROOT / "Failed_Ingestion"

    processed_pdf_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    failed_ingest_dir.mkdir(parents=True, exist_ok=True)

    master_registry_path = LIBRARY_ROOT / "master_registry.json"
    master_registry = {
        "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "matched_count": 0,
        "matched_papers": []
    }
    if master_registry_path.exists():
        try:
            with open(master_registry_path, "r", encoding="utf-8") as f:
                master_registry = json.load(f)
            print(f"✅ 全局 master_registry.json 对账单成功加载！内含 {master_registry.get('matched_count', 0)} 篇已入库文献。")
        except Exception as e:
            print(f"⚠️ 警告: 读取全局 master_registry.json 失败 (可能格式受损，正在重建): {e}")

    # 用于在本次运行中加速去重比对的内存集合
    registered_dois = set()
    registered_titles = set()
    for item in master_registry.get("matched_papers", []):
        m_doi = (item.get("metadata", {}).get("externalIds", {}).get("DOI") or "").strip().lower()
        m_title = (item.get("metadata", {}).get("title") or "").strip()
        if m_doi:
            registered_dois.add(m_doi)
        if m_title:
            registered_titles.add(normalize_title_for_dedup(m_title))

    # 4. 开始物理对齐与入库循环
    ingested_count = 0
    failed_count = 0
    skipped_count = 0

    for idx, pdf_path in enumerate(all_pdfs, 1):
        print(f"\n👉 [{idx}/{len(all_pdfs)}] 正在分析物理文件: '{pdf_path.name}'")

        # 4.1 物理格式深度校验（排除小于10KB或假PDF报错网页）
        if not is_valid_pdf(pdf_path):
            print(f"  🔴 [文件受损/非法PDF] 文件头非 %PDF 或大小小于 10KB。安全隔离中...")
            shutil.copy2(pdf_path, failed_ingest_dir / pdf_path.name)
            failed_count += 1
            continue

        # 4.2 提取前两页原始文本
        pdf_text = extract_pdf_first_two_pages(pdf_path)

        # 4.3 物理三级逆向特征探测
        doi = ""
        title = ""

        # 【第一级】：优先进行原文件名 DOI 探测还原（用户手动改名具有最高优先级，防任何提取噪音）
        extracted_fn_doi = extract_doi_from_filename(pdf_path.stem)
        if extracted_fn_doi:
            doi = extracted_fn_doi
            print(f"  🟢 [用户手动改名 DOI 识别成功] ➡️ '{doi}'")
        else:
            # 【第二级】：PDF 物理文本正则提取 DOI
            extracted_pdf_doi = extract_doi_from_pdf_text(pdf_text)
            if extracted_pdf_doi:
                doi = extracted_pdf_doi
                print(f"  🟢 [PDF物理提取 DOI 成功] ➡️ '{doi}'")

        doi_lower = doi.lower()
        has_valid_doi = doi_lower.startswith("10.")

        # 【第三级】：若无 DOI，利用大模型逆向提取官方标题作为对账线索
        if not has_valid_doi:
            print("  ⚠️ [未探测到DOI] 正在尝试大模型逆向识别论文主标题...")
            if pdf_text and ds_key:
                print("    🤖 正在调用 DeepSeek 精准反向提取该 PDF 前两页中的官方英文标题...")
                extracted_title = extract_title_via_llm(pdf_text, ds_key)
                if extracted_title:
                    title = extracted_title
                    print(f"    🎉 [大模型提取标题成功] ➡️ '{title}'")
                else:
                    print("    ⚠️ 大模型未能提取到有效的文献标题。")
            else:
                if not ds_key:
                    print("    ⚠️ 无 DeepSeek API Key，无法使用大模型逆向识别。")
                else:
                    print("    ⚠️ PDF 文本为空，无法供大模型识别。")

        # 如果既没有 DOI，大模型也没能识别出标题，说明无法作为合法文献入库，直接隔离
        if not has_valid_doi and not title:
            print("  ❌ [物理归档失败] 无法提取有效 DOI 且大模型识别标题失败。安全隔离拷贝中...")
            shutil.copy2(pdf_path, failed_ingest_dir / pdf_path.name)
            failed_count += 1
            continue

        # 4.4 全局极速去重比对
        already_registered = False
        if has_valid_doi and doi_lower in registered_dois:
            already_registered = True
        elif title and normalize_title_for_dedup(title) in registered_titles:
            already_registered = True

        if already_registered:
            print("  ➜ 💾 [增量去重] 经对账，该物理文献已被永久文献库录入，跳过物理复制。")
            skipped_count += 1
            continue

        # 4.5 联网补全完整的学术元数据并自动纠偏 DOI
        meta = None
        if has_valid_doi:
            print("  ➜ 正在联网从 Semantic Scholar 检索最新官方元数据...")
            meta = fetch_metadata_via_doi(doi, ss_key)
            if meta:
                print("    🎉 [元数据拉取成功] S2 官方元数据同步对齐。")
        else:
            print(f"  ➜ 正在通过【逆向标题】从 Semantic Scholar 补全官方元数据...")
            meta = fetch_metadata_via_title(title, ss_key)
            if meta:
                print("    🎉 [标题匹配成功] S2 官方元数据检索补全。")
                # 自动升级纠偏机制：如果官方元数据里含有 DOI，自动顺带抓取！
                fetched_doi = (meta.get("externalIds") or {}).get("DOI")
                if fetched_doi:
                    doi = fetched_doi
                    doi_lower = doi.lower()
                    has_valid_doi = doi_lower.startswith("10.")
                    print(f"    👉 [官方 DOI 自动纠偏补全] 纠正为: '{doi}'")

        # 如果联网完全没找到这篇文献
        if not meta:
            print("  ❌ [元数据检索失败] Semantic Scholar 接口无此文献或由于网络错误拉取失败。正在执行安全隔离...")
            shutil.copy2(pdf_path, failed_ingest_dir / pdf_path.name)
            failed_count += 1
            continue

        # 4.6 写入独立的元数据 JSON
        s2_id = meta.get("paperId") or hashlib.md5((doi if has_valid_doi else title).encode()).hexdigest()
        meta_file_path = metadata_dir / f"{s2_id}.json"
        try:
            meta_file_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"  ⚠️ 写入独立元数据 JSON 失败: {e}")

        # 4.7 规范重命名与物理归档
        meta_title = meta.get("title") or title
        year_str = str(meta.get("year") or "Unknown")
        
        # 提取第一作者姓氏
        author_last_name = "Unknown"
        if meta.get("authors"):
            first_author_full = meta["authors"][0].get("name", "Unknown")
            author_last_name = first_author_full.split()[-1] if first_author_full else "Unknown"

        final_filename = clean_filename(f"[{year_str}] {author_last_name} - {meta_title}") + ".pdf"
        target_pdf_path = processed_pdf_dir / final_filename

        # 执行复制 PDF 副本到永久库中
        try:
            shutil.copy2(pdf_path, target_pdf_path)
            print(f"  ➜ 💾 [物理备份成功] PDF 副本安全复制重命名为: '{final_filename}'")
        except Exception as e:
            print(f"  ❌ [物理备份失败] 无法将 PDF 复制到 processed 文件夹: {e}")
            continue

        # 4.8 登记入全局 master_registry.json 并同步内存去重集合
        new_registry_item = {
            "pdf_name": final_filename,
            "pdf_path": str(target_pdf_path),
            "cache_path": None,
            "parent_dir": pdf_path.parent.name,
            "metadata": meta,
            "match_score": 1.0
        }
        master_registry["matched_papers"].append(new_registry_item)
        master_registry["matched_count"] += 1

        # 同步内存集合
        if has_valid_doi:
            registered_dois.add(doi_lower)
        registered_titles.add(normalize_title_for_dedup(meta_title))

        ingested_count += 1

    # 5. 物理持久化更新全局账本
    try:
        master_registry["scan_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        master_registry_path.write_text(json.dumps(master_registry, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n" + "=" * 80)
        print(f"💾 全局 master_registry.json 对账单持久化保存成功！")
        print(f"   ➜ 永久文献库（主库）当前已完美同步文献总数: {master_registry['matched_count']} 篇")
        print(f"   ➜ 本次成功归档（无损物理复制+美化重命名+元数据补全）: {ingested_count} 篇")
        print(f"   ➜ 经对账已存在（增量秒跳过）: {skipped_count} 篇")
        print(f"   ➜ 归档失败移入 Failed_Ingestion 隔离区: {failed_count} 篇")
        print("=" * 80)
    except Exception as e:
        print(f"❌ 物理保存全局账本失败: {e}")

    print("\n" + "=" * 80)
    print("🎉 永久文献库主库（Literature_Library）物理建库与智能增量对齐任务全部圆满结束！")
    print("=" * 80)


if __name__ == "__main__":
    main()
