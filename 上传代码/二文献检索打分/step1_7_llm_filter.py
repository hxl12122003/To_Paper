#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 1.7: LLM-Based Literature Semantic Filtering System (with Test Mode & No-Abstract Library)
=============================================================================================
该脚本读取 Step 1.6 的粗筛结果，进行以下深度升级：
1. 【无摘要文献独立成库】：自动识别并提取无摘要的文献，不参与打分，单独存入 `no_abstract_papers.json`。
2. 【15维度注入 Prompt】：将 15 个学术维度完整注入给 DeepSeek，让大模型逐个维度进行语义关联评估。
3. 【测试模式（4组 * 80篇）】：挑选第 1, 100, 200, 277 组文献（每组最多 80 篇，去重后），共约 320 篇文献，进行全量打分并输出打分依据。
4. 【断点续传与多线程】：支持随时中断与恢复，支持多线程并发。
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from typing import Dict, List, Set, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import urllib3

# 禁用 urllib3 的不安全请求警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 路径配置
KEYWORD_FILE = Path(r"D:\ARS\关键词15条.txt")
GROUPS_DIR = Path(r"D:\ARS\AutoSci-main\wiki\outputs\batch_search\groups")
OUTPUT_DIR = Path(r"D:\ARS\AutoSci-main\wiki\outputs\batch_search\llm_filtered_results")
PROGRESS_CACHE_PATH = OUTPUT_DIR / "llm_eval_progress.json"
FINAL_RESULT_PATH = OUTPUT_DIR / "llm_semantic_filtered_papers.json"
NO_ABSTRACT_PATH = OUTPUT_DIR / "no_abstract_papers.json"

# API 配置
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
MAX_WORKERS = 15  # 4组测试模式下使用 10 线程，全量运行时可提升至 15

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

def load_and_separate_papers_by_groups(target_groups: List[int] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    根据目标组号（如 1, 100, 200, 277）加载文献，并将其分类为：
    1. 有效文献 (valid_papers)：有摘要、正则得分 >= 1
    2. 无摘要文献 (no_abstract_papers)：无摘要、正则得分 >= 1
    """
    if not GROUPS_DIR.exists():
        print(f"❌ 错误: 找不到文献组目录 '{GROUPS_DIR}'")
        sys.exit(1)
        
    valid_papers = []
    no_abstract_papers = []
    seen_pids = set()
    
    # 确定要加载的 JSON 文件
    if target_groups:
        json_files = [GROUPS_DIR / f"group_{g:02d}_papers.json" for g in target_groups]
        json_files = [f for f in json_files if f.exists()]
        print(f"📂 [测试模式] 正在加载指定的 4 组文献 (组号: {target_groups})...")
    else:
        json_files = list(GROUPS_DIR.glob("group_*.json"))
        print(f"📂 [全量模式] 正在加载全部 {len(json_files)} 组文献...")
        
    for fpath in json_files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            papers = data.get("papers", [])
            for p in papers:
                pid = p.get("paperId")
                if not pid:
                    continue
                if pid not in seen_pids:
                    seen_pids.add(pid)
                    
                    # 检查摘要是否有效
                    abstract = p.get("abstract", "") or ""
                    abstract_clean = abstract.strip().lower()
                    
                    # 0分文献属于绝对噪音，直接排除
                    if p.get("score", 0) == 0:
                        # 如果没有 score 字段（说明是全量加载），我们不排除
                        pass
                    elif p.get("score", 0) == 0:
                        continue
                        
                    if not abstract_clean or "no abstract available" in abstract_clean:
                        no_abstract_papers.append(p)
                    else:
                        valid_papers.append(p)
        except Exception as e:
            print(f"  ⚠️ 读取文件 '{fpath.name}' 失败: {e}")
            
    # 保存无摘要文献到独立库
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(NO_ABSTRACT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "count": len(no_abstract_papers),
            "description": "These papers matched some keywords but do not have abstracts in Semantic Scholar database.",
            "papers": no_abstract_papers
        }, f, ensure_ascii=False, indent=2)
        
    print(f"✅ 成功加载文献：")
    print(f"  ➜ 📝 有效待评估文献 (有摘要): {len(valid_papers)} 篇")
    print(f"  ➜ 📭 无摘要文献 (已单独归档至 '{NO_ABSTRACT_PATH.name}'): {len(no_abstract_papers)} 篇")
    return valid_papers, no_abstract_papers

def evaluate_single_paper(paper: Dict[str, Any], api_key: str, dimensions_prompt: str) -> Dict[str, Any] | None:
    """调用 DeepSeek API 语义评估单篇文献"""
    title = paper.get("title", "")
    abstract = paper.get("abstract", "")
    
    system_prompt = (
        "You are an expert peer reviewer in physical chemistry, photophysics, and nanomaterials.\n"
        "Your task is to read the title and abstract of an academic paper, and evaluate its semantic relevance to our 15 target research dimensions.\n\n"
        "Here are the 15 target research dimensions:\n"
        f"{dimensions_prompt}\n\n"
        "Evaluation Rules:\n"
        "1. Carefully check which of the 15 dimensions are actively studied, discussed, or highly relevant to the paper's abstract. You must understand fuzzy, vague, or non-exact academic expressions (e.g., 'triplet deshelving' or 'RISC' implies triplet state; 'exciton gating' or 'energy transfer' implies FRET/energy transfer; 'sensitizer' or 'acceptor' implies donor-acceptor structure).\n"
        "2. Count the number of matched dimensions. This count will be the 'relevance_score' (from 0 to 15).\n\n"
        "You must respond strictly in JSON format with the following keys:\n"
        "- 'relevance_score': An integer (0 to 15) representing how many of the 15 dimensions are semantically matched.\n"
        "- 'matched_dimensions': A list of integers representing the matched dimension numbers (e.g., [1, 4, 6, 8]).\n"
        "- 'core_mechanism': A brief English phrase describing the photophysical mechanism studied (e.g., 'Triplet Energy Transfer', 'PL Quenching via FRET', 'None')."
    )
    
    user_prompt = (
        f"Please evaluate the following paper:\n\n"
        f"Title: {title}\n"
        f"Abstract: {abstract}\n\n"
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
            resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=45, verify=False)
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
    parser = argparse.ArgumentParser(description="AutoSci LLM 语义过滤系统")
    parser.add_argument("--run-all", action="store_true", help="是否直接运行全量 494 组文献的精筛")
    args = parser.parse_args()

    print("=" * 80)
    print("🚀 开始运行 Step 1.7: 基于 DeepSeek 的文献语义精筛与机理提取系统")
    print("=" * 80)
    
    # 1. 加载 API Key 和 15 维度 Prompt
    api_key = load_deepseek_key()
    print("✅ DeepSeek API Key 加载成功。")
    
    print("📋 正在解析 15 个学术维度并生成 Prompt...")
    dimensions_prompt = parse_keywords_15(KEYWORD_FILE)
    
    # 2. 判断运行模式并加载文献
    if not args.run_all:
        target_groups = [1, 100, 200, 277]
        print("\n" + "=" * 50)
        print("🧪 【测试模式启动 - 4组全文献打分】")
        print(f"我们将挑选第 {target_groups} 组的所有去重文献（每组最多 80 篇）进行打分。")
        print("这将输出每篇文献的打分结果与详细打分依据，供您全面评估打分效果。")
        print("=" * 50)
        valid_papers, no_abstract_papers = load_and_separate_papers_by_groups(target_groups=target_groups)
    else:
        print("\n" + "=" * 50)
        print("🚀 【全量精筛模式启动】")
        print("我们将对全部 494 组文献进行多线程精筛。")
        print("=" * 50)
        valid_papers, no_abstract_papers = load_and_separate_papers_by_groups(target_groups=None)
    
    # 3. 加载已有进度
    progress = load_eval_progress()
    completed_count = len(progress)
    
    # 过滤出未处理的文献
    todo_papers = [p for p in valid_papers if p["paperId"] not in progress]
    print(f"⏭️  检测到已有评估进度：已完成 {completed_count}/{len(valid_papers)} 篇文献。")
    print(f"📝 本次需要评估的文献数量: {len(todo_papers)} 篇。")
    
    if not todo_papers:
        print("🎉 所有文献已评估完毕！正在直接生成最终过滤报告...")
    else:
        print(f"⚡ 启动多线程评估管线 (线程数: {MAX_WORKERS})，请稍候...")
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_paper = {
                executor.submit(evaluate_single_paper, paper, api_key, dimensions_prompt): paper
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
                            
                            if success_count % 5 == 0:
                                save_eval_progress(progress)
                                
                            print(f"  🟢 [成功] 得分: {eval_result.get('relevance_score')}/15 | {title_short}")
                        else:
                            print(f"  🔴 [失败] 无法获取评估结果: {title_short}")
                            fail_count += 1
                    except Exception as e:
                        print(f"  ❌ [异常] 处理文献 '{title_short}' 时发生异常: {e}")
                        fail_count += 1
                        
            except KeyboardInterrupt:
                print("\n⚠️ 收到中断信号 (Ctrl+C)，正在安全保存当前进度并退出...")
                save_eval_progress(progress)
                print("💾 进度已安全存盘。您可以随时重新运行脚本继续。")
                sys.exit(0)
                
        save_eval_progress(progress)
        print(f"\n✅ 运行完毕！成功评估: {success_count} 篇 | 失败: {fail_count} 篇。")
        
    # 4. 生成最终的精筛结果和精美报告
    # 只针对当前加载的文献生成报告
    current_pids = {p["paperId"] for p in valid_papers}
    current_evaluated = [progress[pid] for pid in current_pids if pid in progress]
    
    # 在归档前，为文献数据补充核心元数据字段
    for p in current_evaluated:
        doi = p.get("externalIds", {}).get("DOI", "")
        p["doi"] = doi
        p["journal"] = get_journal_from_doi(doi)
        p["year"] = p.get("year", "Unknown")
        p["citationCount"] = p.get("citationCount", 0)
        
        # 智能识别文献类型：综述 (Review) 还是研究文章 (Research Article)
        # 优先通过 Semantic Scholar 的 publicationTypes 字段识别，其次通过标题正则
        pub_types = [t.lower() for t in p.get("publicationTypes", []) if t]
        title_lower = p.get("title", "").lower()
        if "review" in pub_types or "review" in title_lower or "progress" in title_lower or "prospect" in title_lower or "advances" in title_lower:
            p["paper_type"] = "Review"
        else:
            p["paper_type"] = "Research Article"
    
    # 建立每个得分的分组 (15 down to 0)
    papers_by_score = {score: [] for score in range(15, -1, -1)}
    for p in current_evaluated:
        score = p.get("relevance_score", 0)
        if score in papers_by_score:
            papers_by_score[score].append(p)
        else:
            papers_by_score[0].append(p) # fallback
            
    # 保存精筛 JSON 结果，按得分分组
    result_file = FINAL_RESULT_PATH if args.run_all else OUTPUT_DIR / "llm_test_filtered_papers.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump({
            "total_evaluated": len(current_evaluated),
            "score_distribution": {score: len(papers) for score, papers in papers_by_score.items()},
            "papers_by_score": {
                score: sorted(papers, key=lambda x: x.get("citationCount", 0), reverse=True)
                for score, papers in papers_by_score.items() if papers
            }
        }, f, ensure_ascii=False, indent=2)
        
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
                    # 转换命中维度为文字：将 [1, 3] 转换为 "[1] perovskite nanocrystals; [3] organic dye"
                    matched_ids = p.get("matched_dimensions", [])
                    matched_names = [f"[{dim_id}] {dim_map.get(dim_id, f'Dimension {dim_id}')}" for dim_id in sorted(matched_ids) if dim_id in dim_map]
                    matched_str = "; ".join(matched_names) if matched_names else "None"
                    
                    writer.writerow([
                        idx,
                        p.get("title", ""),
                        p.get("paper_type", "Research Article"),
                        matched_str,
                        p.get("journal", "Unknown Journal"),
                        p.get("year", "Unknown"),
                        p.get("citationCount", 0),
                        p.get("doi", "")
                    ])
                    
            exported_stats.append(f"  ➜ 🔴 得分 {score:2d} 分: {len(dois):4d} 篇 | 📊 详细索引表: {csv_file.name}")
            
    print(f"💾 成功按每个分数导出 CSV 索引表：")
    for stat in exported_stats:
        print(stat)
        
    # 生成 Markdown 精筛报告
    report_file = OUTPUT_DIR / "llm_semantic_filtering_report.md" if args.run_all else OUTPUT_DIR / "llm_test_filtering_report.md"
    
    # 1. 摘要表格行
    summary_table_lines = [
        "| 得分 (Score) | 文献数量 (Count) | 占比 (Percentage) | 建议决策与状态 |",
        "| :---: | :---: | :---: | :--- |"
    ]
    for score in range(15, -1, -1):
        count = len(papers_by_score[score])
        if count == 0:
            continue
        pct = count / max(1, len(current_evaluated)) * 100
        if score >= 6:
            decision = "🔴 **核心文献 (极高价值，精读并导入 Wiki)**"
        elif 4 <= score <= 5:
            decision = "🟡 **参考文献 (高价值参考，作为背景知识)**"
        else:
            decision = "⚪ **淘汰文献 (相关度较低，排除噪音)**"
        summary_table_lines.append(f"| **{score} 分** | **{count}** 篇 | {pct:.2f}% | {decision} |")

    report_lines = [
        f"# 🤖 AutoSci 文献图谱 LLM 语义精筛报告 ({'全量模式' if args.run_all else '4组测试模式'})",
        f"**评估模型**: DeepSeek-Chat | **评估时间**: 2026-06-16",
        "",
        "## 📊 1. 语义筛选得分分布摘要",
        "通过 DeepSeek 对文献进行深度阅读，我们对文献在 15 个学术维度上的匹配度进行了精确打分：",
        "",
    ] + summary_table_lines + [
        f"| **总计评估** | **{len(current_evaluated)}** 篇 | 100.00% | **DOI 导出目录: `{doi_dir.name}/`** |",
        "",
        "---",
        "",
        "## 🏆 2. 评估文献详细打分展示 (按分数从高到低分组)",
        "以下是本次评估的所有文献，按每个得分进行分组展示：",
        ""
    ]
    
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
        
        # 排序：引用数从高到低
        sorted_papers = sorted(papers, key=lambda x: x.get("citationCount", 0), reverse=True)
        for p in sorted_papers:
            authors_str = ", ".join([a.get("name", "Unknown") for a in p.get("authors", [])[:3]])
            if len(p.get("authors", [])) > 3:
                authors_str += " et al."
                
            report_lines.extend([
                f"### {global_rank}. {p['title']}",
                f"- **作者**: {authors_str} | **期刊**: {p.get('journal')} | **年份**: {p.get('year')} | **引用数**: {p.get('citationCount', 0)} | **DOI**: `{p.get('doi', 'None')}`",
                f"- **研究机理**: `{p.get('core_mechanism')}`",
                f"- **命中的具体维度**: `{p.get('matched_dimensions')}`",
                f"- **摘要**: *{p.get('abstract', '')[:250]}...*",
                ""
            ])
            global_rank += 1
        
    report_file.write_text("\n".join(report_lines), encoding="utf-8")
    
    print("\n" + "=" * 80)
    print(f"✨ Step 1.7 大模型语义精筛完成！({'测试模式' if not args.run_all else '全量模式'})")
    print(f"📂 详细精筛 JSON 数据已存入: {result_file}")
    print(f"📝 精美语义精筛报告已生成: {report_file}")
    print("=" * 80)

if __name__ == "__main__":
    main()