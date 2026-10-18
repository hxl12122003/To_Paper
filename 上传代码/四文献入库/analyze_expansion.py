#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Centralized Literature Library Expansion Analyzer (100% Local Cross-Referencing Version)
========================================================================================
1. 【核心圈构建】：读取 `D:\ARS\Literature_Library\master_registry.json`，加载 400+ 篇已下载的核心文献。
2. 【零 API 消耗对账】：
   - 物理扫描 `Metadata/` 目录下的所有独立 JSON，提取每个核心文献的 `references`（引用列表）。
   - 联网获取核心文献的 `citations`（被引列表）并永久回写缓存到本地 JSON 中（终身只查一次）。
   - 在本地内存中，将所有核心文献的 references 和 citations 汇聚成一个“核心学术圈网络图谱”。
3. 【三大候选池提取】：
   - 候选池 1：未下载的高分文献。在原始 CSV 中评分 >= 7（有摘要）或 >= 4（无摘要），但物理 PDF 未成功下载的文献。
   - 候选池 2：有摘要 6 分文献。
   - 候选池 3：无摘要 3 分文献。
4. 【本地内存打分】：
   - 遍历候选文献，计算 Connection Score = (被核心文献引用次数) + (引用核心文献次数)。
5. 【结构化输出】：
   - 在 `D:\ARS\Literature_Library\Expansion_Recommendations\` 下按池子分文件夹，一个分数生成一个 CSV 索引，按 Citation Count 从高到低排序，附带直连下载链接。
"""

from __future__ import annotations

import os
import sys
import re
import csv
import json
import time
import shutil
import hashlib
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Set, Tuple

# =====================================================================
# ⚙️ 核心配置区 (Configuration Section)
# =====================================================================
# 永久文献库根目录 (Sanctuary Zone)
LIBRARY_ROOT = Path(r"D:\ARS\Literature_Library")

# 原始 CSV 搜索成果的两个根目录 (Chaos Zone)
LLM_FILTERED_DIR = Path(r"D:\ARS\AutoSci-main\wiki\outputs\batch_search\llm_filtered_results\dois_by_score")
NO_ABSTRACT_FILTERED_DIR = Path(r"D:\ARS\AutoSci-main\wiki\outputs\batch_search\no_abstract_filtered_results\dois_by_score")
NO_ABSTRACT_SUBSET_DIR = Path(r"D:\ARS\AutoSci-main\wiki\outputs\batch_search\no_abstract_filtered_results\dois_by_score_subset")

# Semantic Scholar API Key 存储文件的绝对路径
SEMANTIC_SCHOLAR_KEY_FILE_PATH = r"D:\ARS\Semantic_Scholar_API.txt"
# =====================================================================


def get_semantic_scholar_api_key() -> str | None:
    """获取 Semantic Scholar API Key"""
    api_file = Path(SEMANTIC_SCHOLAR_KEY_FILE_PATH)
    if api_file.exists():
        try:
            return api_file.read_text(encoding="utf-8").strip() or None
        except Exception:
            pass
    return os.environ.get("S2_API_KEY")


def fetch_s2_citations_from_api(paper_id: str, ss_key: str | None) -> List[Dict[str, Any]]:
    """联网获取指定文献的引用它的文献(citations)（带退避指数重试，防 429）"""
    url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations?limit=1000&fields=externalIds,title,year"
    headers = {"User-Agent": "ARS-PaperSearcher/1.0"}
    if ss_key:
        headers["x-api-key"] = ss_key
        
    req = urllib.request.Request(url, headers=headers)
    
    max_retries = 10
    backoff_factor = 2.0
    
    for attempt in range(1, max_retries + 1):
        try:
            time.sleep(1.5)  # 频率控制安全延迟 1.5 秒
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results = []
                for item in data.get("data") or []:
                    paper_obj = item.get("citingPaper")
                    if paper_obj:
                        results.append(paper_obj)
                return results
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []
            elif e.code == 429:
                sleep_time = min(3600.0, 10.0 * (backoff_factor ** (attempt - 1)))
                print(f"    ⚠️ 触发 S2 关系频控 (HTTP 429)。将在 {sleep_time:.1f} 秒后进行第 {attempt}/{max_retries} 次指数退避重试...")
                time.sleep(sleep_time)
            else:
                sleep_time = min(3600.0, 10.0 * (backoff_factor ** (attempt - 1)))
                print(f"    ⚠️ 获取 citations 关系失败 ({paper_id}): HTTP {e.code}。将在 {sleep_time:.1f} 秒后重试...")
                if attempt == max_retries:
                    return []
                time.sleep(sleep_time)
        except Exception as e:
            sleep_time = min(3600.0, 10.0 * (backoff_factor ** (attempt - 1)))
            print(f"    ⚠️ 获取 citations 关系异常 ({paper_id}): {e}。将在 {sleep_time:.1f} 秒后重试...")
            if attempt == max_retries:
                return []
            time.sleep(sleep_time)
    return []


def read_original_csv(csv_path: Path) -> List[Dict[str, str]]:
    """读取 CSV 原始搜索记录"""
    papers = []
    try:
        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    papers.append(row)
        except (UnicodeDecodeError, UnicodeError):
            with open(csv_path, "r", encoding="gb18030") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    papers.append(row)
    except Exception as e:
        print(f"  ⚠️ 读取 CSV 失败 '{csv_path.name}': {e}")
    return papers


def normalize_title(t: str) -> str:
    """标准化标题，用于去重和比对"""
    return re.sub(r'[^a-z0-9]', '', t.lower().strip())


def generate_direct_pdf_url(doi: str) -> str:
    """根据 DOI 自动生成高能直连下载链接"""
    if not doi:
        return ""
    doi_lower = doi.lower().strip()
    
    # RSC
    if "10.1039" in doi_lower:
        match = re.search(r'10\.1039/([a-z0-9]+)$', doi_lower)
        if match:
            return f"https://pubs.rsc.org/en/content/articlepdf/{datetime.now().year}/{match.group(1).lower()}"
    # Wiley
    elif "10.1002" in doi_lower or "10.1111" in doi_lower:
        return f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}"
    # ACS
    elif "10.1021" in doi_lower:
        return f"https://pubs.acs.org/doi/pdf/{doi}"
    # Nature
    elif "10.1038" in doi_lower:
        return f"https://www.nature.com/articles/{doi_lower.split('/', 1)[1]}.pdf"
    # Science
    elif "10.1126" in doi_lower:
        return f"https://www.science.org/doi/pdf/{doi}"
    # Elsevier
    elif "10.1016" in doi_lower:
        return f"https://doi.org/{doi}"  # Elsevier 走 DOI 重定向
        
    return f"https://doi.org/{doi}"


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    print("=" * 80)
    print("🪐 Centralized Literature Library Expansion Analyzer (本地图谱耦合打分版)")
    print("=" * 80)

    ss_key = get_semantic_scholar_api_key()
    print(f"[*] Semantic Scholar API Key: {'已成功加载 (x-api-key 启用)' if ss_key else '未检测到 (将使用无 Key 限制模式)'}")
    print(f"[*] 永久文献库根目录: '{LIBRARY_ROOT}'")
    print("-" * 80)

    # 1. 读取全局账本，加载核心已下载文献
    master_registry_path = LIBRARY_ROOT / "master_registry.json"
    if not master_registry_path.exists():
        print("❌ 错误: 找不到全局 master_registry.json 账本！请先运行 Step 2 建立主库。")
        sys.exit(1)

    with open(master_registry_path, "r", encoding="utf-8") as f:
        master_registry = json.load(f)

    core_papers = master_registry.get("matched_papers", [])
    print(f"✅ 成功加载全局对账单，当前主库已下载核心文献: {len(core_papers)} 篇。")

    # 建立核心文献的快速去重集合
    core_dois = set()
    core_titles = set()
    for item in core_papers:
        m_doi = (item.get("metadata", {}).get("externalIds", {}).get("DOI") or "").strip().lower()
        m_title = (item.get("metadata", {}).get("title") or "").strip()
        if m_doi: core_dois.add(m_doi)
        if m_title: core_titles.add(normalize_title(m_title))

    # 2. 补全核心文献的 citations 关系并建立本地学术圈大图谱
    print("\n[*] 正在构建本地核心学术圈双向引用图谱...")
    metadata_dir = LIBRARY_ROOT / "Metadata"
    
    # 核心圈大图谱：记录哪些文献与核心文献存在引用关系
    # cited_by_core: 核心文献引用了它
    # citing_core: 它引用了核心文献
    cited_by_core: Dict[str, Set[str]] = {}  # target_id -> set of core_slugs/core_titles that cite it
    citing_core: Dict[str, Set[str]] = {}     # source_id -> set of core_slugs/core_titles that it cites

    for idx, item in enumerate(core_papers, 1):
        meta = item["metadata"]
        paper_id = meta.get("paperId")
        title = meta.get("title", "")
        
        print(f"   [{idx}/{len(core_papers)}] 正在梳理核心脉络: '{title[:40]}...'")
        if not paper_id:
            continue

        local_json_path = metadata_dir / f"{paper_id}.json"
        if not local_json_path.exists():
            continue

        # 读取本地 JSON
        with open(local_json_path, "r", encoding="utf-8") as f:
            local_meta = json.load(f)

        # 2.1 提取 references (核心文献引用了谁)
        references = local_meta.get("references") or []
        for ref in references:
            ref_id = ref.get("paperId")
            ref_doi = (ref.get("externalIds") or {}).get("DOI") or (ref.get("externalIds") or {}).get("doi")
            ref_title = ref.get("title", "")
            
            # 记录：这个文献被当前核心文献引用了
            keys = [k for k in [ref_id, ref_doi, normalize_title(ref_title)] if k]
            for key in keys:
                key_lower = str(key).lower().strip()
                if key_lower not in cited_by_core:
                    cited_by_core[key_lower] = set()
                cited_by_core[key_lower].add(title)

        # 2.2 提取/补全 citations (谁引用了核心文献)
        citations = local_meta.get("citations") or []
        has_citations_cache = "citations" in local_meta
        
        if not has_citations_cache:
            print(f"     🌐 [本地无被引缓存] 正在联网补全其『被引文献 (Citations)』...")
            citations = fetch_s2_citations_from_api(paper_id, ss_key)
            # 永久回写缓存到本地 JSON
            try:
                local_meta["citations"] = citations
                with open(local_json_path, "w", encoding="utf-8") as f:
                    json.dump(local_meta, f, ensure_ascii=False, indent=2)
                print("       💾 [被引缓存写入成功] 永久追加写入本地元数据 JSON。")
            except Exception as e:
                print(f"       ⚠️ 写入本地被引缓存失败: {e}")

        for cit in citations:
            cit_id = cit.get("paperId")
            cit_doi = (cit.get("externalIds") or {}).get("DOI") or (cit.get("externalIds") or {}).get("doi")
            cit_title = cit.get("title", "")
            
            # 记录：这个文献引用了当前核心文献
            keys = [k for k in [cit_id, cit_doi, normalize_title(cit_title)] if k]
            for key in keys:
                key_lower = str(key).lower().strip()
                if key_lower not in citing_core:
                    citing_core[key_lower] = set()
                citing_core[key_lower].add(title)

    print("\n✅ 本地核心学术圈双向图谱构建完毕！正在提取候选文献池...")

    # 3. 扫描原始成果并提取三大候选池
    pool_1_raw = []  # 未下载的高分文献
    pool_2_raw = []  # 有摘要 6 分文献
    pool_3_raw = []  # 无摘要 3 分文献

    # 3.1 提取【候选池 1】：未下载的高分文献
    # 按照您的精准建议：递归扫描 D:\ARS\AutoSci-main\wiki\outputs\batch_search 下所有 failed_downloads_dois.txt 和 *_failed_dois.txt
    failed_dois_set = set()
    search_root = Path(r"D:\ARS\AutoSci-main\wiki\outputs\batch_search")
    
    if search_root.exists():
        # 匹配 failed_downloads_dois.txt 以及诸如 *_failed_dois.txt 等包含 failed 和 doi 的文本文件
        for txt_path in search_root.rglob("*.txt"):
            filename_lower = txt_path.name.lower()
            if "failed" in filename_lower and "doi" in filename_lower:
                try:
                    lines = txt_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                    for line in lines:
                        cleaned_line = line.strip()
                        if cleaned_line.startswith("10."):
                            failed_dois_set.add(cleaned_line.lower())
                except Exception as e:
                    print(f"  ⚠️ 读取失败列表文件出错 '{txt_path.name}': {e}")
                    
    print(f"\n📂 [未下载精确扫描] 递归搜寻 failed_downloads_dois.txt 成果共提取出 {len(failed_dois_set)} 个未下载的 DOI 目标。")

    # 3.2 扫描有摘要的 llm_filtered_results 目录下的所有 CSV，填充候选池
    if LLM_FILTERED_DIR.exists():
        for csv_path in LLM_FILTERED_DIR.rglob("*_info.csv"):
            if "part" in csv_path.parent.name and csv_path.parent.parent.name == "dois_by_score":
                continue
            
            score_match = re.search(r'score_(\d+)', csv_path.name)
            if not score_match:
                continue
            score = int(score_match.group(1))
            
            rows = read_original_csv(csv_path)
            for r in rows:
                r["source_csv"] = csv_path.name
                r["abstract_status"] = "With Abstract"
                r_doi = (r.get("DOI") or r.get("doi") or "").strip().lower()
                r_title = (r.get("文献标题") or r.get("title") or "").strip()
                
                # 排除已下载核心文献
                if r_doi and r_doi in core_dois: continue
                if r_title and normalize_title(r_title) in core_titles: continue
                
                # 判定归属
                if r_doi and r_doi in failed_dois_set:
                    pool_1_raw.append(r)
                elif score == 6:
                    pool_2_raw.append(r)

    # 3.3 扫描无摘要的 no_abstract_filtered_results 目录下的所有 CSV
    no_abstract_csvs = []
    if NO_ABSTRACT_SUBSET_DIR.exists():
        no_abstract_csvs.extend(list(NO_ABSTRACT_SUBSET_DIR.rglob("*_info.csv")))
    if NO_ABSTRACT_FILTERED_DIR.exists():
        no_abstract_csvs.extend(list(NO_ABSTRACT_FILTERED_DIR.rglob("*_info.csv")))

    no_abstract_csvs = sorted(list(set(no_abstract_csvs)))

    for csv_path in no_abstract_csvs:
        if "dois_by_score_subset" in str(csv_path) and csv_path.parent.name != "dois_by_score_subset":
            continue
            
        score_match = re.search(r'score_(\d+)', csv_path.name)
        if not score_match:
            continue
        score = int(score_match.group(1))
        
        rows = read_original_csv(csv_path)
        for r in rows:
            r["source_csv"] = csv_path.name
            r["abstract_status"] = "No Abstract"
            r_doi = (r.get("DOI") or r.get("doi") or "").strip().lower()
            r_title = (r.get("文献标题") or r.get("title") or "").strip()
            
            # 排除已下载核心文献
            if r_doi and r_doi in core_dois: continue
            if r_title and normalize_title(r_title) in core_titles: continue
            
            # 判定归属
            if r_doi and r_doi in failed_dois_set:
                pool_1_raw.append(r)
            elif score == 3:
                pool_3_raw.append(r)

    # 4. 候选池去重
    def deduplicate_pool(raw_pool: List[Dict[str, str]]) -> List[Dict[str, str]]:
        seen_dois = set()
        seen_titles = set()
        deduped = []
        for r in raw_pool:
            doi = (r.get("DOI") or r.get("doi") or "").strip().lower()
            title = (r.get("文献标题") or r.get("title") or "").strip()
            norm_t = normalize_title(title)
            
            is_dup = False
            if doi and doi in seen_dois: is_dup = True
            elif norm_t and norm_t in seen_titles: is_dup = True
            
            if not is_dup:
                if doi: seen_dois.add(doi)
                if norm_t: seen_titles.add(norm_t)
                deduped.append(r)
        return deduped

    pool_1 = deduplicate_pool(pool_1_raw)
    pool_2 = deduplicate_pool(pool_2_raw)
    pool_3 = deduplicate_pool(pool_3_raw)

    print(f"  ➜ 候选池 1 (高分未下载救援池) 提取去重后共: {len(pool_1)} 篇")
    print(f"  ➜ 候选池 2 (有摘要 6 分扩容池) 提取去重后共: {len(pool_2)} 篇")
    print(f"  ➜ 候选池 3 (无摘要 3 分扩容池) 提取去重后共: {len(pool_3)} 篇")

    # 5. 本地内存对账打分
    print("\n[*] 正在进行本地内存对账打分...")
    
    def score_and_enrich_pool(pool: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        scored_pool = []
        for r in pool:
            doi = (r.get("DOI") or r.get("doi") or "").strip().lower()
            title = (r.get("文献标题") or r.get("title") or "").strip()
            norm_t = normalize_title(title)
            
            # 5.1 计算被核心文献引用的次数 (cited_by_core)
            cited_sources = set()
            for key in [doi, norm_t]:
                if key and key in cited_by_core:
                    cited_sources.update(cited_by_core[key])
                    
            # 5.2 计算引用核心文献的次数 (citing_core)
            citing_sources = set()
            for key in [doi, norm_t]:
                if key and key in citing_core:
                    citing_sources.update(citing_core[key])
                    
            score = len(cited_sources) + len(citing_sources)
            
            # 允许设定最低打分门槛，起码要与核心库有 2 篇发生引用/被引（Connection_Score >= 2）才采纳
            # 这样能完全隔绝只和一篇论文发生微弱关联的噪音文献！
            if score >= 2:
                enriched = {
                    "connection_score": score,
                    "citing_core_count": len(citing_sources),  # 它引用了多少篇核心文献
                    "cited_by_core_count": len(cited_sources), # 核心文献有多少篇引用了它
                    "title": title,
                    "doi": doi.upper(),
                    "year": r.get("年份") or r.get("year") or "Unknown",
                    "journal": r.get("期刊") or r.get("journal") or "Unknown",
                    "citation_count": int(r.get("引用数") or r.get("citationCount") or 0),
                    "abstract_status": r.get("abstract_status"),
                    "source_csv": r.get("source_csv"),
                    "cited_by_core_sources": list(cited_sources),
                    "citing_core_sources": list(citing_sources),
                    "direct_download_url": generate_direct_pdf_url(doi) if doi else ""
                }
                scored_pool.append(enriched)
        return scored_pool

    scored_pool_1 = score_and_enrich_pool(pool_1)
    scored_pool_2 = score_and_enrich_pool(pool_2)
    scored_pool_3 = score_and_enrich_pool(pool_3)

    # 6. 结构化输出推荐账本
    recommend_root = LIBRARY_ROOT / "Expansion_Recommendations"
    recommend_root.mkdir(parents=True, exist_ok=True)

    def output_pool_to_csvs(scored_pool: List[Dict[str, Any]], subfolder_name: str):
        subfolder_dir = recommend_root / subfolder_name
        # 清空旧目录，防止脏数据混淆
        if subfolder_dir.exists():
            shutil.rmtree(subfolder_dir)
        subfolder_dir.mkdir(parents=True, exist_ok=True)
        
        if not scored_pool:
            print(f"  ℹ️ 子推荐库 '{subfolder_name}' 无任何关联文献，跳过输出。")
            return

        # 按 connection_score 分组
        grouped_by_score: Dict[int, List[Dict[str, Any]]] = {}
        for item in scored_pool:
            score = item["connection_score"]
            if score not in grouped_by_score:
                grouped_by_score[score] = []
            grouped_by_score[score].append(item)
            
        # 依次输出每个分数的 CSV 文件
        for score, items in sorted(grouped_by_score.items(), reverse=True):
            # 内部严格按照“原始引用数”从高到低排序
            sorted_items = sorted(items, key=lambda x: x["citation_count"], reverse=True)
            
            csv_path = subfolder_dir / f"connection_score_{score:02d}.csv"
            
            headers = [
                "关联得分(Connection_Score)", "库内被引次数", "库内引用次数", 
                "文献标题", "DOI", "发表年份", "期刊/会议", "原始总引用数", 
                "摘要状态", "来源CSV", "核心被引源(核心论文引用了它)", 
                "核心引用源(它引用了核心论文)", "官方直连下载链接"
            ]
            
            try:
                with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(headers)
                    for item in sorted_items:
                        writer.writerow([
                            item["connection_score"],
                            item["cited_by_core_count"],  # 库内被引次数
                            item["citing_core_count"],     # 库内引用次数
                            item["title"],
                            item["doi"],
                            item["year"],
                            item["journal"],
                            item["citation_count"],
                            item["abstract_status"],
                            item["source_csv"],
                            " | ".join(item["cited_by_core_sources"]),  # 核心被引源
                            " | ".join(item["citing_core_sources"]),    # 核心引用源
                            item["direct_download_url"]
                        ])
            except Exception as e:
                print(f"    ❌ 写入 CSV 推荐表失败 '{csv_path.name}': {e}")

    print("\n[*] 正在将对账打分成果结构化输出到 D:\\ARS\\Literature_Library\\Expansion_Recommendations\\...")
    output_pool_to_csvs(scored_pool_1, "1_Un_downloaded_High_Score")
    output_pool_to_csvs(scored_pool_2, "2_Score_6_With_Abstract")
    output_pool_to_csvs(scored_pool_3, "3_Score_3_No_Abstract")

    # 7. 全局分流聚合：下载失败救援池 (Pool 1) VS. 新发现扩容池 (Pools 2 & 3)
    print("\n[*] 正在对扩展分析成果进行全局分流聚合，生成批量下载面板与纯 DOI 列表...")
    
    # 7.1 【救援池 - 历史下载失败】去重与分流
    rescue_recommendations = []
    seen_dois_r = set()
    seen_titles_r = set()
    for item in scored_pool_1:
        doi = item["doi"].lower().strip()
        title = item["title"]
        norm_t = normalize_title(title)
        
        is_dup = False
        if doi and doi in seen_dois_r: is_dup = True
        elif norm_t and norm_t in seen_titles_r: is_dup = True
        
        if not is_dup:
            if doi: seen_dois_r.add(doi)
            if norm_t: seen_titles_r.add(norm_t)
            rescue_recommendations.append(item)
            
    rescue_high = [item for item in rescue_recommendations if item["connection_score"] >= 6]
    rescue_medium = [item for item in rescue_recommendations if 2 <= item["connection_score"] <= 5]

    # 7.2 【扩容池 - 6分有摘要/3分无摘要新发现】去重与分流
    expansion_recommendations = []
    seen_dois_e = set()
    seen_titles_e = set()
    for item in (scored_pool_2 + scored_pool_3):
        doi = item["doi"].lower().strip()
        title = item["title"]
        norm_t = normalize_title(title)
        
        is_dup = False
        if doi and doi in seen_dois_e: is_dup = True
        elif norm_t and norm_t in seen_titles_e: is_dup = True
        
        if not is_dup:
            if doi: seen_dois_e.add(doi)
            if norm_t: seen_titles_e.add(norm_t)
            expansion_recommendations.append(item)
            
    expansion_high = [item for item in expansion_recommendations if item["connection_score"] >= 6]
    expansion_medium = [item for item in expansion_recommendations if 2 <= item["connection_score"] <= 5]
    
    def clean_filename(filename: str, max_len: int = 120) -> str:
        cleaned = re.sub(r'[\\/*?:"<>|]', " ", filename)
        cleaned = re.sub(r'\s+', " ", cleaned).strip()
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len-3].strip() + "..."
        return cleaned

    def generate_download_artifacts(items_list: List[Dict[str, Any]], group_name: str, display_title: str):
        if not items_list:
            print(f"  ℹ️ 分组 '{display_title}' 无数据，跳过下载包生成。")
            return
            
        # 按照原始引用数从高到低重排
        sorted_items = sorted(items_list, key=lambda x: x["citation_count"], reverse=True)
        
        dois_list = []
        publisher_urls = []
        html_links = []
        
        for idx, item in enumerate(sorted_items, 1):
            title = item["title"]
            doi = item["doi"]
            year_str = str(item["year"])
            journal = item["journal"]
            c_score = item["connection_score"]
            cite_count = item["citation_count"]
            direct_url = item["direct_download_url"]
            
            if doi:
                dois_list.append(doi)
            if direct_url:
                publisher_urls.append(direct_url)
                
            safe_filename = clean_filename(f"[{year_str}] {title}")
            
            # 按钮与信息拼接
            html_buttons = (
                f'  <a href="{direct_url}" download="{safe_filename}.pdf" target="_blank" class="btn btn-smart" style="background-color: #2980b9; border-color: #2980b9;" title="利用学校机构权限极速下载，100% 稳定免验证码">🏢 官方直连下载</a>'
            )
            html_links.append(
                f'<li>'
                f'<strong>[{idx}]</strong> '
                f'<span style="font-size: 1.1em; font-weight: bold;">[{year_str}] {title}</span>'
                f'<span style="margin-left: 10px; background-color: #e67e22; color: white; padding: 2px 6px; border-radius: 3px; font-size: 0.8em; font-weight: bold;">关联得分: {c_score} 分</span>'
                f'<br>'
                f'<div style="margin-top: 5px; margin-bottom: 5px;">'
                f'{html_buttons}'
                f'</div>'
                f'<span style="color: #666; font-size: 0.85em;">期刊: {journal} | DOI: {doi} | 原始被引: {cite_count} 次 | <span style="color: #2980b9; font-weight: bold;">🏢 官方直连通道</span></span>'
                f'</li>'
            )
            
        # 写入纯 DOI 列表
        dois_path = recommend_root / f"{group_name}_dois.txt"
        dois_path.write_text("\n".join(dois_list), encoding="utf-8")
        
        # 写入纯直连 URL 列表
        links_path = recommend_root / f"{group_name}_direct_links.txt"
        links_path.write_text("\n".join(publisher_urls), encoding="utf-8")

        # 写入对应的 CSV 索引表，供 check_downloads.py 进行只读比对校验 (完美对齐 1-N 本地序号)
        csv_path = recommend_root / f"{group_name}_info.csv"
        csv_headers = [
            "编号", "文献标题", "DOI", "年份", "期刊/会议", 
            "关联得分(Connection_Score)", "库内被引次数", "库内引用次数", 
            "原始总引用数", "官方直连下载链接"
        ]
        try:
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(csv_headers)
                for csv_idx, item in enumerate(sorted_items, 1):
                    writer.writerow([
                        csv_idx,
                        item["title"],
                        item["doi"],
                        item["year"],
                        item["journal"],
                        item["connection_score"],
                        item["cited_by_core_count"],
                        item["citing_core_count"],
                        item["citation_count"],
                        item["direct_download_url"]
                    ])
        except Exception as e:
            print(f"    ⚠️ 写入 CSV 校验索引表失败 '{csv_path.name}': {e}")
        
        # 写入 HTML 直连极速批量下载面板
        list_items_html = "\n        ".join(html_links)
        html_path = recommend_root / f"{group_name}_download_panel.html"
        
        html_template = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>AutoSci 扩展文献官方直连极速批量下载面板 - {display_title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            margin: 40px auto;
            max-width: 1000px;
            padding: 0 20px;
            color: #333;
            background-color: #f9f9f9;
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 2px solid #34495e;
            padding-bottom: 10px;
        }}
        .notice {{
            background-color: #e8f4f8;
            border-left: 5px solid #2980b9;
            padding: 15px;
            margin-bottom: 30px;
            border-radius: 4px;
        }}
        ol {{
            background: #fff;
            padding: 20px 40px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }}
        li {{
            margin-bottom: 20px;
            padding-bottom: 20px;
            border-bottom: 1px dashed #eee;
        }}
        li:last-child {{
            border-bottom: none;
        }}
        .btn {{
            display: inline-block;
            padding: 5px 12px;
            margin-right: 10px;
            border-radius: 4px;
            font-size: 0.9em;
            font-weight: bold;
            text-decoration: none;
            transition: all 0.2s;
        }}
        .btn-smart {{
            background-color: #2980b9;
            color: white !important;
            border: 1px solid #2980b9;
        }}
        .btn-smart:hover {{
            background-color: #1f618d;
            box-shadow: 0 2px 4px rgba(0,0,0,0.15);
        }}
    </style>
</head>
<body>
    <h1>📥 AutoSci 扩展文献官方直连下载面板 ({display_title})</h1>
    <div class="notice">
        <h3>💡 扩容与救援文献极速批量下载指南：</h3>
        <p>1. <strong>纯 DOI 一键导入 Zotero（强力推荐）</strong>：直接复制同级目录下的 <code>{group_name}_dois.txt</code> 中的所有 DOI，粘贴进 Zotero 的“通过标识符添加条目”魔法棒，借助 Zotero 插件后台自动秒级补全元数据并下载 PDF！</p>
        <p>2. <strong>浏览器直连批量下载</strong>：在浏览器中安装 <strong>Simple Mass Downloader</strong> 插件。直接复制同级目录下的 <code>{group_name}_direct_links.txt</code> 纯直连列表，导入插件中挂机下载。</p>
        <p>3. <strong>手动按需点选</strong>：您也可以直接在此网页中，点击 <strong>🏢 官方直连下载</strong> 按钮，利用您的校园网/机构权限进行免验证码下载。</p>
    </div>
    <h2>推荐扩容文献列表 (共 {len(sorted_items)} 篇)</h2>
    <ol>
        {list_items_html}
    </ol>
</body>
</html>
"""
        html_path.write_text(html_template, encoding="utf-8")
        print(f"  ➜ 🟢 [大组成功生成] '{display_title}' ({len(sorted_items)}篇)：")
        print(f"    ➜ 🌐 HTML 批量下载网页: Expansion_Recommendations/{html_path.name}")
        print(f"    ➜ 🏢 TXT 物理直连列表: Expansion_Recommendations/{links_path.name}")
        print(f"    ➜ 🎫 TXT 纯 DOI 列表 (Zotero专用): Expansion_Recommendations/{dois_path.name}")
        print(f"    ➜ 📊 CSV 校验比对索引表 (只读校验): Expansion_Recommendations/{csv_path.name}")

    # 分别生成历史下载失败救援包（Pool 1）
    generate_download_artifacts(rescue_high, "rescue_high_score", "历史下载失败救援包 - 关联得分 6 分及以上")
    generate_download_artifacts(rescue_medium, "rescue_medium_score", "历史下载失败救援包 - 关联得分 2 至 5 分")

    # 分别生成文献库新文献扩容包（Pools 2 & 3 汇总去重后）
    generate_download_artifacts(expansion_high, "new_expansion_high_score", "学术库新文献扩容包 - 关联得分 6 分及以上")
    generate_download_artifacts(expansion_medium, "new_expansion_medium_score", "学术库新文献扩容包 - 关联得分 2 至 5 分")

    # 分割各池子的子统计用于终端友好输出
    pool_1_high = [item for item in scored_pool_1 if item["connection_score"] >= 6]
    pool_1_med = [item for item in scored_pool_1 if 2 <= item["connection_score"] <= 5]
    
    pool_2_high = [item for item in scored_pool_2 if item["connection_score"] >= 6]
    pool_2_med = [item for item in scored_pool_2 if 2 <= item["connection_score"] <= 5]
    
    pool_3_high = [item for item in scored_pool_3 if item["connection_score"] >= 6]
    pool_3_med = [item for item in scored_pool_3 if 2 <= item["connection_score"] <= 5]

    print("\n" + "=" * 80)
    print("🎉 恭喜！本地图谱耦合打分与高能文献库扩展分析任务全部圆满结束！")
    print(f"   ➜ 高分未下载救援池 (强关联筛选后): {len(scored_pool_1)} 篇 (其中 2-5分: {len(pool_1_med)} 篇，6分及以上: {len(pool_1_high)} 篇)")
    print(f"   ➜ 有摘要 6 分扩容池 (强关联筛选后): {len(scored_pool_2)} 篇 (其中 2-5分: {len(pool_2_med)} 篇，6分及以上: {len(pool_2_high)} 篇)")
    print(f"   ➜ 无摘要 3 分扩容池 (强关联筛选后): {len(scored_pool_3)} 篇 (其中 2-5分: {len(pool_3_med)} 篇，6分及以上: {len(pool_3_high)} 篇)")
    print(f"📂 推荐账本与 Zotero 补下工具已全部安全分流导出至:")
    print(f"   'D:\\ARS\\Literature_Library\\Expansion_Recommendations\\'")
    print("=" * 80)


if __name__ == "__main__":
    main()
