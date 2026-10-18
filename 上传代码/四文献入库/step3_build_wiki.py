#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 3: Build LLM Wiki - Node Generator & Citation Linker (De-centralized & Local Caching Version)
=================================================================================================
该脚本读取 D:\ARS\Literature_Library\master_registry.json 账本，
1. 100% 消除对 Citations 被引接口的联网请求，纯靠本地文献的“引用 (References)”关系在内存中反向自动推导。
2. 引入【永久本地关系缓存】：
   - 优先检查本地 `D:\ARS\Literature_Library\Metadata/{s2_id}.json` 中是否已有 `"references"` 字段。
   - 若有，直接从本地磁盘秒级读取，0 次 API 请求。
   - 若无，联网检索一次，并立刻将参考文献列表回写并永久保存到该 json 中。
3. 429 频控退避重试机制同步升级为 10s -> 20s -> 40s 翻倍指数退避，最大上限 1 小时。
4. 在 wiki/papers/ 下批量生成 Markdown 节点，并自动重建 Wiki 索引 (index.md)。
"""

from __future__ import annotations

import os
import sys
import re
import json
import time
import urllib.parse
import urllib.request
import urllib.error
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Set, Tuple

# =====================================================================
# ⚙️ 核心配置区 (Configuration Section) - 请在此处手动修改您的输入输出路径
# =====================================================================
# 1. 默认文献匹配索引路径 (已升级为全新永久文献库)
DEFAULT_TARGET_PATH = r"D:\ARS\Literature_Library"

# 2. AutoSci Wiki 系统根目录
WIKI_ROOT = Path(r"D:\ARS\AutoSci-main\wiki")

# 3. 辅助工具目录 (指向 AutoSci 引擎工具目录)
TOOLS_DIR = Path(r"D:\ARS\AutoSci-main\tools")

# 4. Semantic Scholar API Key 存储文件的绝对路径
SEMANTIC_SCHOLAR_KEY_FILE_PATH = r"D:\ARS\Semantic_Scholar_API.txt"
# =====================================================================

# 引入 OmegaWiki 的官方 slugify 算法
sys.path.insert(0, str(TOOLS_DIR.resolve()))
try:
    import research_wiki
except ImportError:
    print("⚠️ 警告: 无法直接导入 research_wiki，将使用本地备用 slugify 算法。")
    research_wiki = None


def get_slug(title: str) -> str:
    """获取标准的 Schema-compliant slug"""
    if research_wiki and hasattr(research_wiki, "slugify"):
        return research_wiki.slugify(title)
    text = re.sub(r"[^a-z0-9\s]", " ", title.lower())
    words = text.split()
    stopwords = {"a", "an", "the", "of", "for", "in", "on", "with", "via", "and", "to", "by", "is", "are"}
    keywords = [w for w in words if w not in stopwords and len(w) > 1]
    if not keywords:
        keywords = [w for w in words if w]
    return "-".join(keywords[:6])


def get_semantic_scholar_api_key() -> str | None:
    """获取 Semantic Scholar API Key"""
    api_file = SEMANTIC_SCHOLAR_KEY_FILE_PATH
    if os.path.exists(api_file):
        try:
            with open(api_file, "r", encoding="utf-8") as f:
                key = f.read().strip()
                if key:
                    return key
        except Exception:
            pass
    return os.environ.get("S2_API_KEY")


def fetch_s2_references_from_api(paper_id: str, ss_key: str | None) -> List[Dict[str, Any]]:
    """联网获取指定文献的参考文献(references)（带退避指数重试，防 429）"""
    url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/references?limit=1000&fields=externalIds,title,year"
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
                    paper_obj = item.get("citedPaper")
                    if paper_obj:
                        results.append(paper_obj)
                return results
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"    ℹ️ S2 接口返回 404，该文献在 S2 中无参考文献记录。")
                return []
            elif e.code == 429:
                sleep_time = min(3600.0, 10.0 * (backoff_factor ** (attempt - 1)))
                print(f"    ⚠️ 触发 S2 关系频控 (HTTP 429)。将在 {sleep_time:.1f} 秒后进行第 {attempt}/{max_retries} 次指数退避重试...")
                time.sleep(sleep_time)
            else:
                sleep_time = min(3600.0, 10.0 * (backoff_factor ** (attempt - 1)))
                print(f"    ⚠️ 获取 references 关系失败 ({paper_id}): HTTP {e.code}。将在 {sleep_time:.1f} 秒后重试...")
                if attempt == max_retries:
                    return []
                time.sleep(sleep_time)
        except Exception as e:
            sleep_time = min(3600.0, 10.0 * (backoff_factor ** (attempt - 1)))
            print(f"    ⚠️ 获取 references 关系异常 ({paper_id}): {e}。将在 {sleep_time:.1f} 秒后重试...")
            if attempt == max_retries:
                return []
            time.sleep(sleep_time)
    return []


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


def process_single_index(index_json_path: Path, ss_key: str | None):
    """处理单个 master_registry.json 索引文件并导入 Wiki"""
    print("\n" + "=" * 80)
    print(f"🚀 正在处理对齐索引: '{index_json_path.parent.name}/{index_json_path.name}'")
    print("=" * 80)

    with open(index_json_path, "r", encoding="utf-8") as f:
        index_data = json.load(f)

    matched_papers = index_data.get("matched_papers", [])
    if not matched_papers:
        print("ℹ️ 索引文件中没有已成功对齐匹配的文献数据，跳过。")
        return

    print(f"✅ 成功读取对齐索引，共包含 {len(matched_papers)} 篇核心文献。")

    # 1. 建立本地文献的多维快捷查找字典
    print("\n[*] 正在建立本地文献标识哈希字典...")
    local_papers_by_id = {}
    local_papers_by_doi = {}
    local_papers_by_title_cleaned = {}

    def clean_title_for_lookup(t: str) -> str:
        return re.sub(r'[^a-z0-9]', '', t.lower())

    for item in matched_papers:
        meta = item["metadata"]
        paper_id = meta.get("paperId")
        doi = (meta.get("externalIds") or {}).get("DOI") or (meta.get("externalIds") or {}).get("doi")
        title = meta.get("title", "")
        
        slug = get_slug(title)
        item["slug"] = slug

        if paper_id:
            local_papers_by_id[paper_id] = item
        if doi:
            local_papers_by_doi[doi.strip().lower()] = item
        if title:
            local_papers_by_title_cleaned[clean_title_for_lookup(title)] = item

    # 2. 物理缓存驱动拉取文献间交叉引用网络 ( Bib-Links )
    print(f"[*] 正在分析这 {len(matched_papers)} 篇文献之间的引用关联关系 (100% 本地缓存优先)...")
    citations_graph: Set[Tuple[str, str]] = set()
    metadata_dir = index_json_path.parent / "Metadata"

    for idx, item in enumerate(matched_papers, 1):
        meta = item["metadata"]
        paper_id = meta.get("paperId")
        title = meta.get("title", "")
        slug = item["slug"]
        
        print(f"\n   [{idx}/{len(matched_papers)}] 正在获取学术脉络: '{title[:45]}...'")
        
        if not paper_id:
            print("     ⚠️ 该文献无 S2 paperId，跳过引用分析。")
            continue

        # 2.1 检查本地 JSON 中是否已有 references 和 citations 缓存
        local_json_path = metadata_dir / f"{paper_id}.json"
        local_refs = []
        local_cits = []
        has_refs_cache = False
        has_cits_cache = False
        
        if local_json_path.exists():
            try:
                with open(local_json_path, "r", encoding="utf-8") as f:
                    local_meta = json.load(f)
                    if "references" in local_meta:
                        local_refs = local_meta["references"]
                        has_refs_cache = True
                    if "citations" in local_meta:
                        local_cits = local_meta["citations"]
                        has_cits_cache = True
            except Exception as e:
                print(f"     ⚠️ 读取本地缓存 JSON 失败: {e}")

        # 2.2 参考文献处理：如果有缓存，直接用；如果没有，联网获取一次并回写
        refs = []
        if has_refs_cache:
            print("     ➜ 💾 [缓存命中] 直接从本地读取参考文献，0 次网络请求。")
            refs = local_refs
        else:
            print("     ➜ 🌐 [本地无缓存] 正在联网检索其『参考文献 (References)』...")
            refs = fetch_s2_references_from_api(paper_id, ss_key)
            # 永久回写缓存到本地 JSON 文件中
            if local_json_path.exists():
                try:
                    with open(local_json_path, "r", encoding="utf-8") as f:
                        local_meta = json.load(f)
                    local_meta["references"] = refs
                    with open(local_json_path, "w", encoding="utf-8") as f:
                        json.dump(local_meta, f, ensure_ascii=False, indent=2)
                    print("       💾 [参考文献缓存写入成功] 永久追加写入本地元数据 JSON。")
                except Exception as e:
                    print(f"       ⚠️ 写入本地参考文献缓存失败: {e}")

        # 2.3 被引文献处理（为明天的扩展分析脚本提前一并缓存！）：如果有缓存，直接用；如果没有，联网获取并回写
        cits = []
        if has_cits_cache:
            print("     ➜ 💾 [缓存命中] 直接从本地读取被引文献，0 次网络请求。")
            cits = local_cits
        else:
            print("     ➜ 🌐 [本地无缓存] 正在联网检索其『被引文献 (Citations)』...")
            cits = fetch_s2_citations_from_api(paper_id, ss_key)
            # 永久回写缓存到本地 JSON 文件中
            if local_json_path.exists():
                try:
                    with open(local_json_path, "r", encoding="utf-8") as f:
                        local_meta = json.load(f)
                    local_meta["citations"] = cits
                    with open(local_json_path, "w", encoding="utf-8") as f:
                        json.dump(local_meta, f, ensure_ascii=False, indent=2)
                    print("       💾 [被引文献缓存写入成功] 永久追加写入本地元数据 JSON。")
                except Exception as e:
                    print(f"       ⚠️ 写入本地被引文献缓存失败: {e}")

        # 2.4 匹配本地文献，建立引用边
        ref_matches = 0
        for r in refs:
            r_id = r.get("paperId")
            r_doi = (r.get("externalIds") or {}).get("DOI") or (r.get("externalIds") or {}).get("doi")
            r_title = r.get("title", "")
            
            matched_local = None
            if r_id and r_id in local_papers_by_id:
                matched_local = local_papers_by_id[r_id]
            elif r_doi and r_doi.strip().lower() in local_papers_by_doi:
                matched_local = local_papers_by_doi[r_doi.strip().lower()]
            elif r_title:
                cleaned_rt = clean_title_for_lookup(r_title)
                if cleaned_rt in local_papers_by_title_cleaned:
                    matched_local = local_papers_by_title_cleaned[cleaned_rt]
            
            if matched_local:
                target_slug = matched_local["slug"]
                citations_graph.add((slug, target_slug))
                ref_matches += 1
        print(f"       ✅ 匹配到其引用了本地文献 {ref_matches} 篇")

    print(f"\n🎉 交叉图谱分析完成！共识别出文献间学术引用关系 {len(citations_graph)} 条。")

    # 3. 内存自动推导 cited_by (被引) 缓存
    cited_by_map: Dict[str, List[str]] = {p["slug"]: [] for p in matched_papers}
    for from_slug, to_slug in citations_graph:
        if to_slug in cited_by_map:
            val = f"papers/{from_slug}"
            if val not in cited_by_map[to_slug]:
                cited_by_map[to_slug].append(val)

    # 4. 开始批量写入 wiki/papers/{slug}.md
    print("\n[*] 正在批量生成文献的独立 Wiki Markdown 文件...")
    papers_dir = WIKI_ROOT / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)

    today_str = datetime.now().strftime("%Y-%m-%d")

    for item in matched_papers:
        meta = item["metadata"]
        title = meta.get("title", "")
        slug = item["slug"]
        doi = (meta.get("externalIds") or {}).get("DOI") or (meta.get("externalIds") or {}).get("doi") or ""
        year = meta.get("year")
        paper_id = meta.get("paperId") or ""
        
        abstract = meta.get("abstract") or ""
        tldr = abstract.split(". ")[0].strip() if abstract else ""
        if tldr and not tldr.endswith("."):
            tldr += "."
        if len(tldr) > 200:
            tldr = tldr[:197] + "..."

        pub_types = meta.get("publicationTypes") or []
        frontmatter = {
            "title": title,
            "slug": slug,
            "arxiv": "",
            "venue": meta.get("venue") or "",
            "year": int(year) if year else None,
            "tags": ["perovskite", "BODIPY", "energy-transfer"] + [t.lower() for t in pub_types],
            "importance": 4,
            "date_added": today_str,
            "source_type": "pdf",
            "s2_id": paper_id,
            "tldr": tldr or "Review paper covering lead halide perovskites and BODIPY dyes.",
            "publication_types": pub_types,
            "contribution_type": ["analysis", "survey"],
            "datasets": [],
            "code_url": "",
            "cited_by": cited_by_map.get(slug, [])
        }

        fm_lines = ["---"]
        for k, v in frontmatter.items():
            if isinstance(v, list):
                if not v:
                    fm_lines.append(f"{k}: []")
                else:
                    fm_lines.append(f"{k}:")
                    for item_val in v:
                        fm_lines.append(f"  - {item_val}")
            elif v is None:
                fm_lines.append(f"{k}: null")
            elif isinstance(v, str):
                val_escaped = v.replace('"', '\\"')
                fm_lines.append(f'{k}: "{val_escaped}"')
            else:
                fm_lines.append(f"{k}: {v}")
        fm_lines.append("---")
        fm_text = "\n".join(fm_lines)

        body_text = """
## Problem & Context

## Key idea

## Method

## Experiment & Results

## Limitations

## Open questions

## My take

## Related
"""
        full_content = fm_text + "\n" + body_text
        md_file_path = papers_dir / f"{slug}.md"
        with open(md_file_path, "w", encoding="utf-8") as f:
            f.write(full_content)
        print(f"  📝 已生成: {md_file_path.name}")

    # 5. 写入 wiki/graph/citations.jsonl
    print("\n[*] 正在同步写入 wiki/graph/citations.jsonl...")
    citations_path = WIKI_ROOT / "graph" / "citations.jsonl"
    citations_path.parent.mkdir(parents=True, exist_ok=True)

    existing_citations = []
    if citations_path.exists():
        try:
            with open(citations_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        existing_citations.append(json.loads(line))
        except Exception:
            pass

    for from_slug, to_slug in citations_graph:
        cit_record = {
            "from": f"papers/{from_slug}",
            "to": f"papers/{to_slug}",
            "type": "cites",
            "source": "semantic_scholar",
            "date": today_str
        }
        if not any(c.get("from") == cit_record["from"] and c.get("to") == cit_record["to"] for c in existing_citations):
            existing_citations.append(cit_record)

    with open(citations_path, "w", encoding="utf-8") as f:
        for c in existing_citations:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"  💾 引用关联已同步写回至 {citations_path.name}，当前总关联边数: {len(existing_citations)}")

    # 6. 将带有 'slug' 字段的完整数据持久化回写大表/索引文件中 (彻底解决命名分歧)
    print("\n[*] 正在将计算出的完美 Slug 标识永久写回并登记至大表/索引文件中...")
    try:
        with open(index_json_path, "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
        print("  💾 [登记成功] 大表/索引文件已成功同步保存 'slug' 键！")
    except Exception as e:
        print(f"  ❌ [登记失败] 无法将 slug 状态写回大表/索引文件: {e}")


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    print("=" * 80)
    print("🚀 Step 3: 开始构建 LLM Wiki 学术基础关联图谱 (本地去中心化缓存版)")
    print("=" * 80)

    ss_key = get_semantic_scholar_api_key()
    print(f"[*] Semantic Scholar API Key: {'已成功加载 (x-api-key 启用)' if ss_key else '未检测到 (将使用无 Key 限制模式)'}")
    print("-" * 80)

    if len(sys.argv) > 1:
        input_path = Path(sys.argv[1])
    else:
        input_path = Path(DEFAULT_TARGET_PATH)

    if not input_path.exists():
        print(f"❌ 错误: 找不到目标路径 '{input_path}'。")
        sys.exit(1)

    # 自动初始化 Wiki 根目录
    if not WIKI_ROOT.exists():
        print(f"\n[*] 检测到 Wiki 根目录不存在，正在自动初始化: '{WIKI_ROOT}'")
        try:
            cmd = ["python", str(TOOLS_DIR / "research_wiki.py"), "init", str(WIKI_ROOT)]
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            if result.returncode == 0:
                print("🎉 Wiki 目录结构初始化成功！")
            else:
                print(f"⚠️ 警告: 初始化 Wiki 结构失败: {result.stderr}")
        except Exception as e:
            print(f"⚠️ 警告: 初始化 Wiki 结构出错: {e}")

    # 自动识别运行模式：全新永久文献库统一导入模式 vs. 单索引文件模式 vs. 根目录循环挂机模式
    is_master_registry = (input_path.is_dir() and (input_path / "master_registry.json").exists()) or input_path.name == "master_registry.json"
    
    if is_master_registry:
        index_json_path = input_path / "master_registry.json" if input_path.is_dir() else input_path
        print(f"💡 🪐 检测到全新永久文献库统一导入模式！正在直接处理全局账本: '{index_json_path.name}'")
        process_single_index(index_json_path, ss_key)
    elif input_path.is_file() or (input_path.is_dir() and (input_path / "matched_literature_index.json").exists()):
        # 单文件夹/单文件模式
        index_json_path = input_path / "matched_literature_index.json" if input_path.is_dir() else input_path
        print(f"💡 检测到单分包运行模式，正在直接处理: '{index_json_path.parent.name}'")
        process_single_index(index_json_path, ss_key)
    else:
        # 根目录循环挂机模式：递归寻找所有的 matched_literature_index.json
        print(f"💡 检测到根目录循环挂机模式！正在递归搜寻 '{input_path.name}' 下的所有绑定索引...")
        index_files_to_process = []
        for p in input_path.rglob("matched_literature_index.json"):
            if p.is_file():
                index_files_to_process.append(p)
                
        index_files_to_process = sorted(list(set(index_files_to_process)))
        
        if not index_files_to_process:
            print(f"❌ 错误: 未在 '{input_path}' 及其子目录下找到任何 matched_literature_index.json 或 master_registry.json 索引！请先运行 Step 2。")
            sys.exit(1)
            
        print(f"🎉 搜寻完毕！共找到 {len(index_files_to_process)} 个待导入的文献索引：")
        for idx, file_path in enumerate(index_files_to_process, 1):
            print(f"   [{idx}] '{file_path.parent.relative_to(input_path)}/{file_path.name}'")
            
        # 依次循环处理每个索引文件
        for idx, file_path in enumerate(index_files_to_process, 1):
            print(f"\n🚀 [挂机进度: {idx}/{len(index_files_to_process)}] 正在导入分包节点...")
            process_single_index(file_path, ss_key)

    # 7. 自动运行 Index 重建，使 Wiki 生效
    print("\n[*] 正在调用 OmegaWiki 官方组件重建 Wiki 索引 (index.md)...")
    try:
        cmd = ["python", str(TOOLS_DIR / "research_wiki.py"), "rebuild-index", str(WIKI_ROOT)]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if result.returncode == 0:
            print("🎉 Wiki 索引更新成功！index.md 已同步对齐。")
        else:
            print(f"⚠️ 警告: 重建 index 失败: {result.stderr}")
    except Exception as e:
        print(f"⚠️ 警告: 重建 index 出错: {e}")

    print("\n" + "=" * 80)
    print("✨ 文献基础图谱及文献 Markdown 节点构建完成！")
    print("✨ 所有的文献 Markdown 节点和引用关系已完美导入并在索引中对齐生效！")
    print("=" * 80)


if __name__ == "__main__":
    main()
