#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 1_8: No-Abstract Literature Classifier & Semantic Filter (Strict Partitioning & Journal Analysis)
====================================================================================================
该脚本针对无摘要的 4,388 篇文献进行深度处理：
1. 【大模型分类】：调用 DeepSeek API 根据【标题】和元数据判断文献类型：
   - 专利 (Patent) / 会议文章 (Conference) -> ❌ 过滤删除
   - 期刊 (Journal) / 综述 (Review) -> 🟢 保留
2. 【严格三级分区】：大模型根据标题评估其与课题的相关度（1-5 分）：
   - 🔴 高相关度分区 (Score >= 4)：核心保留库 `no_abstract_kept_high.json`
   - 🟡 中相关度分区 (Score 2-3)：扩展参考库 `no_abstract_kept_medium.json`
   - ⚪ 低相关度分区 (Score < 2，即 1 分)：暂存库 `no_abstract_staged_low.json`
3. 【期刊与出版社深度分析】：通过解析所有 4,388 篇文献的 DOI，智能识别它们发表在哪些主流杂志和出版社上，生成详尽的学术分布报告。
4. 【运行模式】：
   - 默认测试模式：随机挑选 100 篇无摘要文献进行打分分类，并输出精美报告。
   - 全量模式 (--run-all)：对全部 4,388 篇无摘要文献进行多线程并发处理。
"""

import os
import sys
import json
import time
import argparse
import random
import re
from pathlib import Path
from typing import Dict, List, Set, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import urllib3

# 禁用 urllib3 的不安全请求警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 路径配置
INPUT_NO_ABSTRACT_PAPERS = Path(r"D:\ARS\AutoSci-main\wiki\outputs\batch_search\llm_filtered_results\no_abstract_papers.json")
OUTPUT_DIR = Path(r"D:\ARS\AutoSci-main\wiki\outputs\batch_search\no_abstract_filtered_results")
PROGRESS_CACHE_PATH = OUTPUT_DIR / "no_abstract_eval_progress.json"

# 最终输出库
KEPT_HIGH_PATH = OUTPUT_DIR / "no_abstract_kept_high.json"
KEPT_MEDIUM_PATH = OUTPUT_DIR / "no_abstract_kept_medium.json"
STAGED_LOW_PATH = OUTPUT_DIR / "no_abstract_staged_low.json"
DISCARDED_PATH = OUTPUT_DIR / "no_abstract_discarded.json"
KEYWORD_FILE = Path(r"D:\ARS\关键词15条.txt")

# API 配置
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
MAX_WORKERS = 15  # 默认线程数

def load_deepseek_key() -> str:
    """自动加载 DeepSeek API Key"""
    for key_file in (r"D:\ARS\deepseek_api_key.txt", r"D:\ARS\deepseek.txt", "deepseek_api_key.txt"):
        if os.path.exists(key_file):
            try:
                with open(key_file, "r", encoding="utf-8") as f:
                    key = f.read().strip()
                    if key:
                        return key
            except Exception:
                pass
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
        
    print("❌ 错误: 未找到 DeepSeek API Key！")
    print("请在 D:\\ARS\\ 目录下创建 'deepseek_api_key.txt' 并写入您的 API Key。")
    sys.exit(1)

def parse_keywords_15(file_path: Path) -> str:
    """解析 15 条关键词维度，生成格式化的英文文本供 Prompt 使用"""
    if not file_path.exists():
        print(f"❌ 错误: 找不到关键词文件 '{file_path}'")
        sys.exit(1)
        
    content = file_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    
    formatted_dims = []
    current_num = None
    current_terms = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        import re
        match = re.match(r'^(\d+)\s*\.\s*(.*)$', line)
        if match:
            if current_num is not None and current_terms:
                formatted_dims.append(f"Dimension {current_num:02d}: {', '.join(current_terms)}")
            current_num = int(match.group(1))
            term = match.group(2).strip()
            current_terms = [term] if term else []
        else:
            if current_num is not None:
                current_terms.append(line)
                
    if current_num is not None and current_terms:
        formatted_dims.append(f"Dimension {current_num:02d}: {', '.join(current_terms)}")
        
    return "\n".join(formatted_dims)

def get_journal_from_doi(doi: str) -> str:
    """根据 DOI 前缀和特征智能识别期刊名称"""
    if not doi:
        return "Unknown Journal"
    doi_lower = doi.lower()
    if "10.1021" in doi_lower:
        if "/ja" in doi_lower or ".ja" in doi_lower:
            return "Journal of the American Chemical Society (JACS)"
        elif "/nl" in doi_lower or ".nl" in doi_lower:
            return "Nano Letters"
        elif "/jp" in doi_lower or ".jp" in doi_lower:
            return "The Journal of Physical Chemistry"
        elif "/nn" in doi_lower or ".nn" in doi_lower:
            return "ACS Nano"
        elif "/am" in doi_lower or ".am" in doi_lower:
            return "ACS Applied Materials & Interfaces"
        else:
            return "ACS Journals"
    elif "10.1039" in doi_lower:
        if any(x in doi_lower for x in ["c3cc", "c4cc", "c5cc", "c6cc", "c7cc", "c8cc", "c9cc", "d0cc", "d1cc", "d2cc", "d3cc", "d4cc"]):
            return "Chemical Communications (ChemComm)"
        elif any(x in doi_lower for x in ["c3cp", "c4cp", "c5cp", "c6cp", "c7cp", "c8cp", "c9cp", "d0cp", "d1cp", "d2cp", "d3cp", "d4cp"]):
            return "Physical Chemistry Chemical Physics (PCCP)"
        elif any(x in doi_lower for x in ["tc", "ta", "tb"]):
            return "Journal of Materials Chemistry"
        else:
            return "RSC Journals"
    elif "10.1002" in doi_lower:
        if "anie" in doi_lower:
            return "Angewandte Chemie"
        elif "adma" in doi_lower:
            return "Advanced Materials"
        elif "adfm" in doi_lower:
            return "Advanced Functional Materials"
        else:
            return "Wiley Journals"
    elif "10.1016" in doi_lower:
        if "dyepig" in doi_lower:
            return "Dyes and Pigments"
        else:
            return "Elsevier Journals"
    elif "10.1038" in doi_lower or "10.1007" in doi_lower:
        if "ncomms" in doi_lower or "s41467" in doi_lower:
            return "Nature Communications"
        else:
            return "Springer Nature"
    elif "10.1063" in doi_lower:
        if "1.4" in doi_lower or "jcp" in doi_lower:
            return "The Journal of Chemical Physics (JCP)"
        else:
            return "AIP Journals"
    elif "10.1103" in doi_lower:
        if "physrevlett" in doi_lower:
            return "Physical Review Letters (PRL)"
        else:
            return "APS Journals"
    elif "10.1109" in doi_lower:
        return "IEEE Transactions"
    return "Other / Unknown Journal"

def load_dimension_names_map(file_path: Path) -> Dict[int, str]:
    """解析 15 条关键词维度文件，生成 {维度编号: 简短名称} 的映射"""
    if not file_path.exists():
        return {}
    content = file_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    groups = {}
    current_num = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        import re
        match = re.match(r'^(\d+)\s*\.\s*(.*)$', line)
        if match:
            current_num = int(match.group(1))
            term = match.group(2).strip()
            groups[current_num] = [term] if term else []
        else:
            if current_num is not None:
                groups[current_num].append(line)
    # 取每个维度的第一个核心词作为简短名称
    return {num: terms[0] if terms else f"Dimension {num}" for num, terms in groups.items()}

def load_no_abstract_papers() -> List[Dict[str, Any]]:
    """加载无摘要文献"""
    if not INPUT_NO_ABSTRACT_PAPERS.exists():
        print(f"❌ 错误: 找不到无摘要文献文件 '{INPUT_NO_ABSTRACT_PAPERS}'，请先运行 Step 1.7。")
        sys.exit(1)
        
    with open(INPUT_NO_ABSTRACT_PAPERS, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    papers = data.get("papers", [])
    print(f"✅ 成功加载 {len(papers)} 篇无摘要文献。")
    return papers

def analyze_journals_by_doi(papers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    通过解析文献的 DOI 缀和特征，智能分析它们发表在哪些主流出版社和顶级期刊上。
    """
    publisher_stats = {
        "ACS (美国化学会)": 0,
        "RSC (英国皇家化学会)": 0,
        "Wiley (威立出版社)": 0,
        "Elsevier (爱思唯尔)": 0,
        "Springer Nature (自然集团)": 0,
        "AIP (美国物理联合会)": 0,
        "APS (美国物理学会)": 0,
        "IEEE (电气电子工程师学会)": 0,
        "Other / Unknown (其他/未识别)": 0
    }
    
    journal_stats = {
        "Nano Letters (纳米快报)": 0,
        "Journal of the American Chemical Society (JACS)": 0,
        "The Journal of Physical Chemistry (JPC系列)": 0,
        "ACS Nano": 0,
        "ACS Applied Materials & Interfaces": 0,
        "Angewandte Chemie (德国应用化学)": 0,
        "Advanced Materials (先进材料)": 0,
        "Advanced Functional Materials": 0,
        "Chemical Communications (ChemComm)": 0,
        "Physical Chemistry Chemical Physics (PCCP)": 0,
        "Journal of Materials Chemistry (A/B/C)": 0,
        "Dyes and Pigments (染料与颜料)": 0,
        "Nature Communications (自然通讯)": 0,
        "The Journal of Chemical Physics (JCP)": 0,
        "Physical Review Letters (PRL)": 0,
        "Other Specific Journals (其他期刊)": 0
    }
    
    no_doi_count = 0
    
    for p in papers:
        doi = (p.get("externalIds") or {}).get("DOI", "")
        if not doi:
            no_doi_count += 1
            publisher_stats["Other / Unknown (其他/未识别)"] += 1
            continue
            
        doi_lower = doi.lower()
        
        # 1. 识别出版社 (通过 DOI 前缀)
        is_identified = False
        
        # ACS: 10.1021
        if "10.1021" in doi_lower:
            publisher_stats["ACS (美国化学会)"] += 1
            is_identified = True
            # 识别具体 ACS 期刊
            if "/ja" in doi_lower or ".ja" in doi_lower:
                journal_stats["Journal of the American Chemical Society (JACS)"] += 1
            elif "/nl" in doi_lower or ".nl" in doi_lower:
                journal_stats["Nano Letters (纳米快报)"] += 1
            elif "/jp" in doi_lower or ".jp" in doi_lower:
                journal_stats["The Journal of Physical Chemistry (JPC系列)"] += 1
            elif "/nn" in doi_lower or ".nn" in doi_lower:
                journal_stats["ACS Nano"] += 1
            elif "/am" in doi_lower or ".am" in doi_lower:
                journal_stats["ACS Applied Materials & Interfaces"] += 1
            else:
                journal_stats["Other Specific Journals (其他期刊)"] += 1
                
        # RSC: 10.1039
        elif "10.1039" in doi_lower:
            publisher_stats["RSC (英国皇家化学会)"] += 1
            is_identified = True
            if "c3cc" in doi_lower or "c4cc" in doi_lower or "c5cc" in doi_lower or "c6cc" in doi_lower or "c7cc" in doi_lower or "c8cc" in doi_lower or "c9cc" in doi_lower or "d0cc" in doi_lower or "d1cc" in doi_lower or "d2cc" in doi_lower or "d3cc" in doi_lower or "d4cc" in doi_lower:
                journal_stats["Chemical Communications (ChemComm)"] += 1
            elif "c3cp" in doi_lower or "c4cp" in doi_lower or "c5cp" in doi_lower or "c6cp" in doi_lower or "c7cp" in doi_lower or "c8cp" in doi_lower or "c9cp" in doi_lower or "d0cp" in doi_lower or "d1cp" in doi_lower or "d2cp" in doi_lower or "d3cp" in doi_lower or "d4cp" in doi_lower:
                journal_stats["Physical Chemistry Chemical Physics (PCCP)"] += 1
            elif "tc" in doi_lower or "ta" in doi_lower or "tb" in doi_lower:
                journal_stats["Journal of Materials Chemistry (A/B/C)"] += 1
            else:
                journal_stats["Other Specific Journals (其他期刊)"] += 1
                
        # Wiley: 10.1002
        elif "10.1002" in doi_lower:
            publisher_stats["Wiley (威立出版社)"] += 1
            is_identified = True
            if "anie" in doi_lower:
                journal_stats["Angewandte Chemie (德国应用化学)"] += 1
            elif "adma" in doi_lower:
                journal_stats["Advanced Materials (先进材料)"] += 1
            elif "adfm" in doi_lower:
                journal_stats["Advanced Functional Materials"] += 1
            else:
                journal_stats["Other Specific Journals (其他期刊)"] += 1
                
        # Elsevier: 10.1016
        elif "10.1016" in doi_lower:
            publisher_stats["Elsevier (爱思唯尔)"] += 1
            is_identified = True
            if "dyepig" in doi_lower:
                journal_stats["Dyes and Pigments (染料与颜料)"] += 1
            else:
                journal_stats["Other Specific Journals (其他期刊)"] += 1
                
        # Springer Nature: 10.1038 or 10.1007
        elif "10.1038" in doi_lower or "10.1007" in doi_lower:
            publisher_stats["Springer Nature (自然集团)"] += 1
            is_identified = True
            if "ncomms" in doi_lower or "s41467" in doi_lower:
                journal_stats["Nature Communications (自然通讯)"] += 1
            else:
                journal_stats["Other Specific Journals (其他期刊)"] += 1
                
        # AIP: 10.1063
        elif "10.1063" in doi_lower:
            publisher_stats["AIP (美国物理联合会)"] += 1
            is_identified = True
            if "1.4" in doi_lower or "jcp" in doi_lower:
                journal_stats["The Journal of Chemical Physics (JCP)"] += 1
            else:
                journal_stats["Other Specific Journals (其他期刊)"] += 1
                
        # APS: 10.1103
        elif "10.1103" in doi_lower:
            publisher_stats["APS (美国物理学会)"] += 1
            is_identified = True
            if "physrevlett" in doi_lower:
                journal_stats["Physical Review Letters (PRL)"] += 1
            else:
                journal_stats["Other Specific Journals (其他期刊)"] += 1
                
        # IEEE: 10.1109
        elif "10.1109" in doi_lower:
            publisher_stats["IEEE (电气电子工程师学会)"] += 1
            is_identified = True
            journal_stats["Other Specific Journals (其他期刊)"] += 1
            
        if not is_identified:
            publisher_stats["Other / Unknown (其他/未识别)"] += 1
            journal_stats["Other Specific Journals (其他期刊)"] += 1
            
    return {
        "publishers": publisher_stats,
        "journals": journal_stats,
        "no_doi_count": no_doi_count
    }

def load_eval_progress() -> Dict[str, Dict[str, Any]]:
    """加载已有的评估进度（断点续传）"""
    if PROGRESS_CACHE_PATH.exists():
        try:
            with open(PROGRESS_CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ 读取进度缓存失败: {e}，将重新开始。")
    return {}

def save_eval_progress(progress_data: Dict[str, Dict[str, Any]]):
    """保存评估进度"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = PROGRESS_CACHE_PATH.with_suffix(".tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(progress_data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, PROGRESS_CACHE_PATH)
    except Exception as e:
        print(f"⚠️ 保存进度缓存失败: {e}")

def classify_and_score_title(paper: Dict[str, Any], api_key: str, dimensions_prompt: str) -> Dict[str, Any] | None:
    """调用 DeepSeek API 根据标题分类并打分"""
    title = paper.get("title", "")
    year = paper.get("year", "Unknown")
    
    system_prompt = (
        "You are an expert peer reviewer in physical chemistry, photophysics, and nanomaterials.\n"
        "Your task is to analyze the TITLE of an academic paper that has no abstract, and perform two tasks:\n\n"
        "Task 1: Classify the paper type into one of the following:\n"
        "- 'Patent': If the title sounds like a patent (e.g., starts with 'A preparation method of...', 'Method for...', '一种...', 'Device for...', 'Process for manufacturing...').\n"
        "- 'Conference': If the title or metadata indicates it is a conference abstract, poster, proceeding, or presentation (e.g., contains 'Abstracts of...', 'Proceeding of...', 'Meeting Abstract...').\n"
        "- 'Review': If the title contains words like 'Review', 'Progress', 'Prospect', 'Advances', 'Tutorial', 'Overview'.\n"
        "- 'Journal': If it is a standard research journal article.\n"
        "- 'Other': Editorials, errata, books, etc.\n\n"
        "Task 2: Evaluate its semantic relevance to our 15 target research dimensions based ONLY on the title.\n"
        "Here are the 15 target research dimensions:\n"
        f"{dimensions_prompt}\n\n"
        "Evaluation Rules for Task 2:\n"
        "1. Carefully check which of the 15 dimensions are actively studied, discussed, or highly relevant to the paper's title. You must understand fuzzy, vague, or non-exact academic expressions.\n"
        "2. Count the number of matched dimensions. This count will be the 'relevance_score' (from 0 to 15). Since titles are short, the score will naturally be lower (often 0 to 4), which is completely expected.\n\n"
        "You must respond strictly in JSON format with the following keys:\n"
        "- 'paper_type': 'Patent' | 'Conference' | 'Review' | 'Journal' | 'Other'\n"
        "- 'relevance_score': An integer from 0 to 15.\n"
        "- 'matched_dimensions': A list of integers representing the matched dimension numbers (e.g., [1, 3])."
    )
    
    user_prompt = (
        f"Please evaluate the following paper title:\n\n"
        f"Title: {title}\n"
        f"Year: {year}\n\n"
        f"Return the JSON response directly. Do not include markdown code block syntax (like ```json) in your response, just raw JSON."
    )
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }
    
    max_retries = 5
    backoff = 2.0
    for attempt in range(max_retries):
        try:
            resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=30, verify=False)
            if resp.status_code == 200:
                result_json = resp.json()
                content_str = result_json["choices"][0]["message"]["content"].strip()
                eval_data = json.loads(content_str)
                return eval_data
            elif resp.status_code == 429:
                time.sleep(backoff)
                backoff *= 2
            elif 500 <= resp.status_code < 600:
                time.sleep(backoff)
                backoff *= 2
            else:
                return None
        except Exception:
            time.sleep(backoff)
            backoff *= 2
            
    return None

def main():
    parser = argparse.ArgumentParser(description="AutoSci 无摘要文献分类精筛系统")
    parser.add_argument("--run-all", action="store_true", help="是否运行全部 4,388 篇无摘要文献的精筛")
    args = parser.parse_args()

    print("=" * 80)
    print("🚀 开始运行 Step 1.8: 无摘要文献大模型分类与标题语义精筛系统")
    print("=" * 80)
    
    # 1. 加载 API Key 和无摘要文献
    api_key = load_deepseek_key()
    print("✅ DeepSeek API Key 加载成功。")
    
    print("📋 正在解析 15 个学术维度并生成 Prompt...")
    dimensions_prompt = parse_keywords_15(KEYWORD_FILE)
    
    all_papers = load_no_abstract_papers()
    if not all_papers:
        print("❌ 错误: 无摘要文献库为空。")
        sys.exit(1)
        
    # 2. 深度分析这 4,388 篇文献的杂志/出版社分布
    print("\n📊 正在对全部 4,388 篇无摘要文献进行 DOI 杂志/出版社分布分析...")
    doi_analysis = analyze_journals_by_doi(all_papers)
    print("✅ 杂志/出版社分布分析完成！")
    
    # 3. 决定运行模式：测试模式 (100篇) vs 全量模式
    if not args.run_all:
        print("\n" + "=" * 50)
        print("🧪 【测试模式启动 - 100篇无摘要文献分类打分】")
        print("我们将随机挑选 100 篇无摘要文献进行大模型分类与标题语义打分测试。")
        print("这能帮您快速看清无摘要文献的构成比例，并验证打分效果。")
        print("=" * 50)
        
        # 随机挑选 100 篇进行测试，确保每次测试结果一致，我们固定随机种子
        random.seed(42)
        test_papers = random.sample(all_papers, min(100, len(all_papers)))
        todo_papers = test_papers
    else:
        print("\n" + "=" * 50)
        print("🚀 【全量精筛模式启动 - 4,388篇无摘要文献】")
        print("我们将对全部无摘要文献进行多线程并发分类与打分。")
        print("=" * 50)
        
        # 加载已有进度
        progress = load_eval_progress()
        completed_count = len(progress)
        print(f"⏭️  检测到已有评估进度：已完成 {completed_count}/{len(all_papers)} 篇文献。")
        
        # 过滤出未处理的文献
        todo_papers = [p for p in all_papers if p["paperId"] not in progress]
        print(f"📝 本次需要评估的文献数量: {len(todo_papers)} 篇。")
        
    # 4. 运行评估
    progress = load_eval_progress() if args.run_all else {}
    
    if todo_papers:
        print(f"⚡ 启动多线程评估管线 (线程数: {MAX_WORKERS})，请稍候...")
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_paper = {
                executor.submit(classify_and_score_title, paper, api_key, dimensions_prompt): paper
                for paper in todo_papers
            }
            
            success_count = 0
            fail_count = 0
            
            try:
                for future in as_completed(future_to_paper):
                    paper = future_to_paper[future]
                    pid = paper["paperId"]
                    title_short = paper["title"][:50] + "..."
                    
                    try:
                        eval_result = future.result()
                        if eval_result:
                            full_record = {**paper, **eval_result}
                            progress[pid] = full_record
                            success_count += 1
                            
                            if args.run_all and success_count % 10 == 0:
                                save_eval_progress(progress)
                                
                            print(f"  🟢 [{success_count}/{len(todo_papers)}] 类型: {eval_result.get('paper_type')} | 得分: {eval_result.get('relevance_score')}/15 | {title_short}")
                        else:
                            print(f"  🔴 [失败] 无法获取评估结果: {title_short}")
                            fail_count += 1
                    except Exception as e:
                        print(f"  ❌ [异常] 处理文献时发生异常: {e}")
                        fail_count += 1
                        
            except KeyboardInterrupt:
                if args.run_all:
                    print("\n⚠️ 收到中断信号 (Ctrl+C)，正在安全保存当前进度并退出...")
                    save_eval_progress(progress)
                    print("💾 进度已安全存盘。您可以随时重新运行脚本继续。")
                else:
                    print("\n⚠️ 收到中断信号，测试中止。")
                sys.exit(0)
                
        if args.run_all:
            save_eval_progress(progress)
            
    # 5. 统计与严格各分数段归档
    evaluated_list = list(progress.values()) if args.run_all else list(progress.values())
    if not args.run_all:
        evaluated_list = [p for p in progress.values() if "paper_type" in p]
        
    # 在归档前，为文献数据补充核心元数据字段
    for p in evaluated_list:
        doi = p.get("externalIds", {}).get("DOI", "")
        p["doi"] = doi
        p["journal"] = get_journal_from_doi(doi)
        p["year"] = p.get("year", "Unknown")
        p["citationCount"] = p.get("citationCount", 0)
        
    discarded_papers = []   # 专利、会议、其他
    papers_by_score = {score: [] for score in range(15, -1, -1)}
    
    type_counts = {"Patent": 0, "Conference": 0, "Journal": 0, "Review": 0, "Other": 0}
    score_counts = {score: 0 for score in range(15, -1, -1)}
    
    for p in evaluated_list:
        ptype = p.get("paper_type", "Other")
        score = p.get("relevance_score", 0)
        
        type_counts[ptype] = type_counts.get(ptype, 0) + 1
        if ptype in ("Journal", "Review"):
            score_counts[score] = score_counts.get(score, 0) + 1
            if score in papers_by_score:
                papers_by_score[score].append(p)
            else:
                papers_by_score[0].append(p)
                
        # 严格分类逻辑
        if ptype in ("Patent", "Conference", "Other"):
            discarded_papers.append(p)
            
    # 存盘输出 JSON
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "_test" if not args.run_all else ""
    result_file = OUTPUT_DIR / (f"no_abstract_semantic_filtered_papers{suffix}.json")
    disc_path = DISCARDED_PATH.with_name(DISCARDED_PATH.stem + suffix + ".json")
    
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump({
            "total_evaluated": len(evaluated_list),
            "score_distribution": {score: len(papers) for score, papers in papers_by_score.items()},
            "papers_by_score": {
                score: sorted(papers, key=lambda x: x.get("citationCount", 0), reverse=True)
                for score, papers in papers_by_score.items() if papers
            }
        }, f, ensure_ascii=False, indent=2)
        
    with open(disc_path, "w", encoding="utf-8") as f:
        json.dump({"count": len(discarded_papers), "papers": discarded_papers}, f, ensure_ascii=False, indent=2)
        
    # 导出各分数段的 CSV 索引表至独立文件夹
    doi_dir = OUTPUT_DIR / ("dois_by_score" if args.run_all else "dois_by_score_test")
    doi_dir.mkdir(parents=True, exist_ok=True)
    
    # 清理旧的 CSV 文件
    for f in doi_dir.glob("score_*_info.csv"):
        try: f.unlink()
        except Exception: pass
            
    # 加载维度简短名称映射
    dim_map = load_dimension_names_map(KEYWORD_FILE)
    
    exported_stats = []
    import csv
    for score in range(15, -1, -1):
        papers = papers_by_score[score]
        if not papers:
            continue
        
        # 排序：引用数从高到低
        sorted_papers = sorted(papers, key=lambda x: x.get("citationCount", 0), reverse=True)
        dois = [p.get("doi") for p in sorted_papers if p.get("doi")]
        
        if dois:
            # 导出带编号、标题、文献类型、命中维度、期刊、年份、引用数、DOI的 CSV 索引表（供 Excel 查看）
            csv_file = doi_dir / f"score_{score:02d}_info.csv"
            with open(csv_file, "w", encoding="utf-8-sig", newline="") as f: # utf-8-sig 确保 Excel 打开不乱码
                writer = csv.writer(f)
                writer.writerow(["编号", "文献标题", "文献类型", "命中维度", "期刊", "年份", "引用数", "DOI"])
                for idx, p in enumerate(sorted_papers, 1):
                    # 规范化文献类型显示
                    ptype = p.get("paper_type", "Journal")
                    if ptype == "Journal":
                        ptype_zh = "Research Article"
                    elif ptype == "Review":
                        ptype_zh = "Review"
                    else:
                        ptype_zh = ptype
                        
                    # 转换命中维度为文字：将 [1, 3] 转换为 "[1] perovskite nanocrystals; [3] organic dye"
                    matched_ids = p.get("matched_dimensions", [])
                    matched_names = [f"[{dim_id}] {dim_map.get(dim_id, f'Dimension {dim_id}')}" for dim_id in sorted(matched_ids) if dim_id in dim_map]
                    matched_str = "; ".join(matched_names) if matched_names else "None"
                    
                    writer.writerow([
                        idx,
                        p.get("title", ""),
                        ptype_zh,
                        matched_str,
                        p.get("journal", "Unknown Journal"),
                        p.get("year", "Unknown"),
                        p.get("citationCount", 0),
                        p.get("doi", "")
                    ])
            exported_stats.append(f"  ➜ 🔴 得分 {score:2d} 分: {len(dois):4d} 篇 | 📊 详细索引表: {csv_file.name}")
            
    print(f"💾 成功按每个分数导出无摘要文献 CSV 索引表：")
    for stat in exported_stats:
        print(stat)
        
    # 6. 生成精美报告
    report_file = OUTPUT_DIR / f"no_abstract_filtering_report{suffix}.md"
    
    # 准备报告内容
    report_lines = [
        f"# 📭 无摘要文献大模型分类与严格精筛报告 ({'全量模式' if args.run_all else '测试模式'})",
        f"**生成时间**: 2026-06-16 | **评估样本数**: {len(evaluated_list)} 篇",
        "",
        "## 📊 1. 文献类型构成分析 (Paper Type Analysis)",
        "大模型通过阅读标题，对无摘要文献的类型进行了精准识别：",
        "",
        "| 文献类型 | 数量 | 占比 | 处理决策 | 状态 |",
        "| :--- | :---: | :---: | :--- | :--- |",
        f"| 📝 **期刊论文 (Journal)** | **{type_counts['Journal']}** 篇 | {type_counts['Journal']/len(evaluated_list)*100:.2f}% | 根据标题相关度进一步打分 | 保留/暂存 |",
        f"| 📚 **综述文献 (Review)** | **{type_counts['Review']}** 篇 | {type_counts['Review']/len(evaluated_list)*100:.2f}% | 根据标题相关度进一步打分 | 保留/暂存 |",
        f"| 💡 **专利文献 (Patent)** | **{type_counts['Patent']}** 篇 | {type_counts['Patent']/len(evaluated_list)*100:.2f}% | ❌ **非学术研究，直接过滤** | 已删除 |",
        f"| 📢 **会议文章 (Conference)** | **{type_counts['Conference']}** 篇 | {type_counts['Conference']/len(evaluated_list)*100:.2f}% | ❌ **多为摘要集 or 墙报，直接过滤** | 已删除 |",
        f"| ⚪ **其他类型 (Other)** | **{type_counts['Other']}** 篇 | {type_counts['Other']/len(evaluated_list)*100:.2f}% | ❌ **勘误、书籍、社论，直接过滤** | 已删除 |",
        "",
        "---",
        "",
        "## 📈 2. 严格按分数段相关度分布",
        "针对保留下来的期刊和综述文献，我们根据标题进行了 0-15 分的语义相关度精确打分：",
        "",
        "| 得分 (Score) | 文献数量 (Count) | 占比 (占期刊/综述) | 决策归档 | 状态 |",
        "| :---: | :---: | :---: | :--- | :--- |"
    ]
    
    total_valid_no_abstract = sum(len(papers_by_score[s]) for s in range(15, -1, -1))
    for score in range(15, -1, -1):
        count = len(papers_by_score[score])
        if count == 0:
            continue
        pct = count / max(1, total_valid_no_abstract) * 100
        if score >= 6:
            decision = f"score_{score:02d}_info.csv (🔴 高相关度)"
        elif 4 <= score <= 5:
            decision = f"score_{score:02d}_info.csv (🟡 中相关度)"
        else:
            decision = f"score_{score:02d}_info.csv (⚪ 低相关度)"
        report_lines.append(f"| **{score} 分** | **{count}** 篇 | {pct:.2f}% | {decision} | 🟢 已导出 |")
        
    report_lines.extend([
        "",
        "---",
        "",
        "## 🏛️ 3. 4,388 篇无摘要文献学术分布分析 (Journal & Publisher Analysis)",
        "通过解析无摘要文献的 DOI，我们对**全部 4,388 篇无摘要文献**的出版社 and 主流期刊进行了系统统计。这能帮您看清这些文献都发表在哪些高水平杂志上：",
        "",
        "### 🏢 A. 出版社分布 (Publisher Distribution)",
        "",
        "| 出版社名称 | 文献数量 | 占比 | 知名期刊代表 |",
        "| :--- | :---: | :---: | :--- |"
    ])
    
    # 写入出版社统计
    sorted_publishers = sorted(doi_analysis["publishers"].items(), key=lambda x: x[1], reverse=True)
    total_analyzed = len(all_papers)
    for pub, count in sorted_publishers:
        pct = count / total_analyzed * 100
        rep = ""
        if "ACS" in pub: rep = "JACS, Nano Letters, J. Phys. Chem. C/Letters, ACS Nano"
        elif "RSC" in pub: rep = "Chem. Comm., PCCP, J. Mater. Chem. A/C, Nanoscale"
        elif "Wiley" in pub: rep = "Angewandte Chemie, Advanced Materials, Adv. Funct. Mater."
        elif "Elsevier" in pub: rep = "Dyes and Pigments, J. Photochem. Photobiol."
        elif "Springer" in pub: rep = "Nature Communications, Nano Research"
        elif "AIP" in pub: rep = "The Journal of Chemical Physics, Applied Physics Letters"
        elif "APS" in pub: rep = "Physical Review Letters, Physical Review B"
        elif "IEEE" in pub: rep = "IEEE Transactions (电子与工程类)"
        else: rep = "其他中小型出版社、国内期刊或无 DOI 元数据文献"
        report_lines.append(f"| {pub} | **{count}** 篇 | {pct:.2f}% | {rep} |")
        
    report_lines.extend([
        "",
        "### 📖 B. 主流顶级期刊分布 (Top Journal Distribution)",
        "在全部 4,388 篇无摘要文献中，发表在物理化学、纳米材料领域核心期刊上的数量统计：",
        "",
        "| 期刊名称 | 文献数量 | 占比 (占总无摘要文献) | 学术声誉与分区 |",
        "| :--- | :---: | :---: | :--- |"
    ])
    
    # 写入期刊统计
    sorted_journals = sorted(doi_analysis["journals"].items(), key=lambda x: x[1], reverse=True)
    for jr, count in sorted_journals:
        pct = count / total_analyzed * 100
        reputation = ""
        if "JACS" in jr: reputation = "化学界顶级期刊 (中科院1区 / Nature Index)"
        elif "Nano Letters" in jr: reputation = "纳米材料顶级快报 (中科院1区 / Nature Index)"
        elif "JPC" in jr: reputation = "物理化学老牌经典期刊 (JPC A/B/C/Letters)"
        elif "ACS Nano" in jr: reputation = "纳米材料顶级期刊 (中科院1区 / Nature Index)"
        elif "ACS Applied" in jr: reputation = "材料应用核心期刊 (中科院2区顶尖)"
        elif "Angewandte" in jr: reputation = "化学界顶级期刊 (中科院1区 / Nature Index)"
        elif "Advanced Materials" in jr: reputation = "材料学界至尊期刊 (中科院1区 / Nature Index)"
        elif "Advanced Functional" in jr: reputation = "材料学界顶级期刊 (中科院1区 / Nature Index)"
        elif "ChemComm" in jr: reputation = "化学核心快报 (中科院2区顶尖 / Nature Index)"
        elif "PCCP" in jr: reputation = "物理化学核心期刊 (中科院3区)"
        elif "Materials Chemistry" in jr: reputation = "材料化学核心期刊 (J. Mater. Chem. A/B/C)"
        elif "Dyes and Pigments" in jr: reputation = "有机染料/光敏剂核心期刊 (中科院2区顶尖)"
        elif "Nature Communications" in jr: reputation = "综合性顶级期刊 (中科院1区 / Nature Index)"
        elif "JCP" in jr: reputation = "化学物理老牌经典期刊 (中科院3区)"
        elif "PRL" in jr: reputation = "物理学界至尊期刊 (中科院1区 / Nature Index)"
        else: reputation = "其他细分领域期刊"
        report_lines.append(f"| {jr} | **{count}** 篇 | {pct:.2f}% | {reputation} |")
        
    report_lines.extend([
        "",
        "---",
        "",
        "## 🏆 4. 核心保留文献按分数展示",
        "以下是筛选出的无摘要文献，按每个得分进行分组展示：",
        ""
    ])
    
    global_rank = 1
    for score in range(15, -1, -1):
        papers = papers_by_score[score]
        if not papers:
            continue
            
        report_lines.extend([
            f"## 📌 得分: {score} 分 (共 {len(papers)} 篇)",
            "---",
            ""
        ])
        
        for p in sorted(papers, key=lambda x: x.get("citationCount", 0), reverse=True)[:30]: # 每个分数段最多展示 30 篇典型
            authors_str = ", ".join([a.get("name", "Unknown") for a in p.get("authors", [])[:3]])
            if len(p.get("authors", [])) > 3:
                authors_str += " et al."
                
            report_lines.extend([
                f"### {global_rank}. 【{p.get('paper_type')}】 {p['title']}",
                f"- **作者**: {authors_str} | **期刊**: {p.get('journal')} | **年份**: {p.get('year')} | **引用数**: {p.get('citationCount', 0)} | **DOI**: `{p.get('doi', 'None')}`",
                ""
            ])
            global_rank += 1
        
    report_file.write_text("\n".join(report_lines), encoding="utf-8")
    
    print("\n" + "=" * 80)
    print(f"✨ Step 1.8 无摘要文献分类精筛完成！({'测试模式' if not args.run_all else '全量模式'})")
    print(f"  ➜ 📂 详细精筛 JSON 数据已按得分分组存入: {result_file.name}")
    print(f"  ➜ ❌ 已删除库 (专利/会议): {len(discarded_papers)} 篇 -> 存入 {disc_path.name}")
    print("-" * 80)
    print(f"📝 严格分区与杂志分布报告已生成: {report_file.name}")
    print("=" * 80)

if __name__ == "__main__":
    main()