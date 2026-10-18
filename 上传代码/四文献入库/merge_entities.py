# -*- coding: utf-8 -*-
"""
AutoSci Wiki Universal Entity Consolidator (Methods / Mechanisms / Concepts)
====================================================================================
1. 参数化支持分类内部合并：
   - mechanisms: 合并物理机制 (wiki/mechanisms/)
   - concepts:   合并引言概念 (wiki/concepts/)
   - methods:    合并表征手段 (wiki/methods/)
2. 采用【两阶段智能聚类】（Python 词法预洗 ➡️ DeepSeek 语义终审），生成最规范的合并方案。
3. 结构自动适配：
   - methods & mechanisms: 拆分/追加 "### [[slug]] 中的描述与结果"
   - concepts:             拆分/追加 "### [[slug]] 中的引言段落"
4. 全局超链自愈：递归扫描整个 wiki/ 下所有 md 文件，同步更新所有旧 wikilinks 链接。
"""

import os
import sys
import re
import json
import shutil
import urllib.request
from pathlib import Path
from difflib import SequenceMatcher
from typing import List, Dict, Any, Tuple, Set

# ⚙️ 路径配置
WIKI_ROOT = Path(r"D:\ARS\AutoSci-main\wiki")
DEEPSEEK_KEY_FILE_PATH = r"D:\ARS\deepseek_api_key.txt"

def get_deepseek_api_key() -> str | None:
    api_file = Path(DEEPSEEK_KEY_FILE_PATH)
    if api_file.exists():
        try:
            return api_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return os.environ.get("DEEPSEEK_API_KEY")

def lexical_pre_clustering(filenames: List[str]) -> List[List[str]]:
    """第一阶段：利用 Python 快速进行词法编辑距离与 Jaccard 相似度预聚类，将文件快速归类"""
    clusters = []
    visited = set()
    
    def get_clean_words(name: str) -> Set[str]:
        cleaned = re.sub(r'[^a-z0-9\s]', ' ', name.lower().replace('.md', ''))
        return set(w for w in cleaned.split() if len(w) > 1)

    sorted_names = sorted(filenames, key=len)
    
    for name in sorted_names:
        if name in visited:
            continue
        current_cluster = [name]
        visited.add(name)
        words1 = get_clean_words(name)
        
        for other in sorted_names:
            if other in visited:
                continue
            words2 = get_clean_words(other)
            
            # 计算 Jaccard 相似度 (词语重合度)
            intersection = words1 & words2
            union = words1 | words2
            jaccard = len(intersection) / len(union) if union else 0
            
            # 计算 SequenceMatcher 编辑距离
            seq_ratio = SequenceMatcher(None, name.lower(), other.lower()).ratio()
            
            # 如果重合度极高，或者属于包含关系的短语，归为一类
            if jaccard >= 0.65 or seq_ratio >= 0.75:
                current_cluster.append(other)
                visited.add(other)
            elif words1.issubset(words2) and len(words1) >= 3:
                # 包含关系（如 "triplet energy transfer" 包含在 "interfacial triplet energy transfer" 中）
                current_cluster.append(other)
                visited.add(other)
                
        clusters.append(current_cluster)
    return clusters

def request_deepseek_clustering(representative_names: List[str], entity_type: str, api_key: str) -> Dict[str, List[str]]:
    """第二阶段：呼叫 DeepSeek 进行高级学术语义对账聚类，输出规范映射表"""
    prompt = f"""You are an elite academic taxonomist. We are cleaning up our local academic database directory for **{entity_type}**.
We have pre-clustered redundant filenames. Your task is to analyze these representative filenames, group synonymous terms together (e.g. abbreviations vs full names, spelling variations), select the single best CANONICAL name for each group, and map the synonyms to it.

### ENTITY TYPE BEING MERGED:
{entity_type} (e.g., characterization methods, photophysical mechanisms, or academic concept nodes)

### CANDIDATE FILES REPRESENTATIVES:
{json.dumps(representative_names, ensure_ascii=False, indent=2)}

### CLUSTERING RULES:
1. Group truly synonymous terms under one standard and professional canonical name (e.g. `triplet-triplet-energy-transfer-ttet.md` and `triplet-energy-transfer-tet.md` represent the same mechanism).
2. The canonical name must end with '.md' and must be chosen from the provided list of candidates.
3. Map all other synonymous files in that group to this "canonical_file".
4. If a file is unique and has no synonym, omit it from the synonyms mappings.

### OUTPUT FORMAT:
Respond with a strict JSON object with this exact schema (no Markdown wrap, no conversational filler, just raw JSON):
{{
  "mappings": [
    {{
      "canonical_file": "standard-professional-name.md",
      "synonyms": [
        "abbreviated-name.md",
        "variation-spelling.md"
      ]
    }}
  ]
}}
"""
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a professional academic assistant. You perform semantic clustering and output valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "thinking": {"type": "disabled"}
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
            content = resp_data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            res = json.loads(content.strip())
            
            # 重建映射表：synonym -> canonical
            flat_map = {}
            for item in res.get("mappings", []):
                canonical = item.get("canonical_file", "").strip()
                synonyms = item.get("synonyms", [])
                if canonical:
                    for syn in synonyms:
                        syn_clean = syn.strip()
                        if syn_clean and syn_clean != canonical:
                            flat_map[syn_clean] = canonical
            return flat_map
    except Exception as e:
        print(f"   ⚠️ [DeepSeek 聚类接口异常]: {e}")
        return {}

def update_global_wikilinks(old_slug: str, new_slug: str):
    """全局超链自愈：递归扫描整个 wiki 目录，更新所有 MD 链接"""
    old_link = f"[[{old_slug}]]"
    new_link = f"[[{new_slug}]]"
    
    count = 0
    for file_path in WIKI_ROOT.rglob("*.md"):
        if file_path.is_file():
            try:
                text = file_path.read_text(encoding="utf-8")
                if old_link in text:
                    new_text = text.replace(old_link, new_link)
                    file_path.write_text(new_text, encoding="utf-8")
                    count += 1
            except Exception:
                pass
    return count

def execute_merge_file(src_path: Path, dest_path: Path, entity_type: str, archive_dir: Path):
    """执行单个文件的内容无损合并（核心段落拆分与排重追加）"""
    if not src_path.exists() or src_path == dest_path:
        return
        
    # 根据类别，自动适配拆分锚点
    if entity_type == "concepts":
        split_anchor = r"###\s+\[\[(.*?)\]\]\s*中的引言段落"
        header_template = "### [[{paper_slug}]] 中的引言段落"
    else:
        split_anchor = r"###\s+\[\[(.*?)\]\]\s*中的描述与结果"
        header_template = "### [[{paper_slug}]] 中的描述与结果"

    try:
        src_text = src_path.read_text(encoding="utf-8")
        dest_text = dest_path.read_text(encoding="utf-8")
        
        # 解析源文件
        src_sections = re.split(split_anchor, src_text)
        src_chunks = {}
        for i in range(1, len(src_sections), 2):
            src_chunks[src_sections[i].strip()] = src_sections[i+1].strip()
            
        # 解析目标文件
        dest_sections = re.split(split_anchor, dest_text)
        dest_chunks = {}
        for i in range(1, len(dest_sections), 2):
            dest_chunks[dest_sections[i].strip()] = dest_sections[i+1].strip()
            
        # 合并 source_papers 字段 (Frontmatter)
        src_papers = set(re.findall(r"-\s*\"?papers/([^\s\"]+)\"?", src_text))
        dest_papers = set(re.findall(r"-\s*\"?papers/([^\s\"]+)\"?", dest_text))
        
        # 同时提取无前缀的纯文件名匹配
        src_papers_raw = set(re.findall(r"-\s*\"?([^\s\"]+)\"?", src_text))
        dest_papers_raw = set(re.findall(r"-\s*\"?([^\s\"]+)\"?", dest_text))
        
        all_p_slugs = set()
        for p in (src_papers | dest_papers | src_papers_raw | dest_papers_raw):
            p_clean = p.replace("papers/", "").strip()
            if p_clean and p_clean not in [entity_type, "mechanism", "protocol", "concept", "stable", "experimental"]:
                all_p_slugs.add(p_clean)
                
        merged_papers = sorted(list(all_p_slugs))
        
        # 合并并排重追加真题描述块
        for p_slug, chunk_body in src_chunks.items():
            if p_slug not in dest_chunks:
                dest_chunks[p_slug] = chunk_body
                
        # 重构目标文件的 Frontmatter
        fm_match = re.match(r"^(---\s*\n.*?\n---)", dest_text, re.DOTALL)
        if fm_match:
            fm_lines = fm_match.group(1).split("\n")
            new_fm_lines = []
            in_source_papers = False
            
            for line in fm_lines:
                if "source_papers:" in line:
                    new_fm_lines.append("source_papers:")
                    for p in merged_papers:
                        new_fm_lines.append(f"  - \"papers/{p}\"")
                    in_source_papers = True
                    continue
                if in_source_papers:
                    if line.startswith("  -") or line.strip() == "":
                        continue
                    else:
                        in_source_papers = False
                new_fm_lines.append(line)
            fm_text = "\n".join(new_fm_lines)
        else:
            fm_text = dest_text.split("## ")[0].strip()
            
        # 组装新内容
        body_blocks = []
        for p_slug, body in sorted(dest_chunks.items()):
            header = header_template.format(paper_slug=p_slug)
            body_blocks.append(f"{header}\n{body}")
            
        # 确定二级标题名称
        sec_title = "Introduction Chunks (引言论证段落库)" if entity_type == "concepts" else "Descriptions in Papers (文献中的具体描述与结果)"
        
        merged_content = f"""{fm_text}

# {dest_path.stem.replace('-', ' ').title()}

## Overview
这是一个在物理化学和光动力学中讨论的核心学术知识节点。

## {sec_title}

""" + "\n\n".join(body_blocks)

        dest_path.write_text(merged_content.strip() + "\n", encoding="utf-8")
        
        # 物理隔离归档废弃的同义文件 (绝对不删除，放归档目录备查)
        archive_path = archive_dir / src_path.name
        shutil.move(str(src_path), str(archive_path))
        
    except Exception as e:
        print(f"  ❌ 合并文件时发生异常 '{src_path.name}' ➡️ '{dest_path.name}': {e}")

def main():
    if len(sys.argv) < 2:
        print("❌ 错误: 请指定要合并的实体类别！")
        print("用法: python D:\\ARS\\merge_entities.py [methods | mechanisms | concepts] [--execute]")
        return
        
    entity_type = sys.argv[1].lower().strip()
    if entity_type not in ["methods", "mechanisms", "concepts"]:
        print(f"❌ 错误: 不支持的实体类别 '{entity_type}'。必须是 methods, mechanisms 或 concepts 之一。")
        return
        
    is_dry_run = "--execute" not in sys.argv
    
    print("=" * 80)
    print(f"🚀 AutoSci {entity_type.upper()} 本地学术实体去重合并终端 {'[只读预览模式]' if is_dry_run else '[正式物理合并模式]'}")
    print("=" * 80)
    
    target_dir = WIKI_ROOT / entity_type
    if not target_dir.exists():
        print(f"❌ 错误: 找不到目标实体目录 '{target_dir}'")
        return
        
    api_key = get_deepseek_api_key()
    if not api_key:
        print("❌ 错误: 无法获取 DeepSeek API Key！")
        return
        
    # 建立隔离归档目录
    archive_dir = target_dir.parent / f"{entity_type}_archive"
    if not is_dry_run:
        archive_dir.mkdir(parents=True, exist_ok=True)
        
    all_files = [f.name for f in target_dir.glob("*.md")]
    print(f"[*] 成功扫描本地 `{entity_type}` 库，当前共有 {len(all_files)} 个独立文件。")
    
    # 1. 运行第一阶段：Python 词法预洗
    print("[*] 正在执行第一阶段：本地高速词法 Jaccard/编辑距离预清洗...")
    lexical_groups = lexical_pre_clustering(all_files)
    
    representative_to_group = {}
    representatives = []
    for g in lexical_groups:
        rep = g[0] # 取代表性名称
        representatives.append(rep)
        representative_to_group[rep] = g
        
    print(f"  ➜ 预清洗完毕！已将 {len(all_files)} 个文件压缩归纳为了 {len(representatives)} 个核心代表组。")
    
    # 2. 运行第二阶段：DeepSeek 语义终审映射
    print("\n[*] 正在执行第二阶段：呼叫 DeepSeek 专家大脑进行学术语义大终审...")
    semantic_mappings = request_deepseek_clustering(representatives, entity_type, api_key)
    
    # 3. 编织最终合并计划
    final_plan = {} # obsolete_file -> canonical_file
    for rep, syn_list in representative_to_group.items():
        canonical_rep = semantic_mappings.get(rep, rep)
        for file_name in syn_list:
            if file_name != canonical_rep:
                final_plan[file_name] = canonical_rep
                
    if not final_plan:
        print("\n🎉 对账完毕！当前库内所有实体节点均高度独立，无冗余！无需合并。")
        return
        
    # 4. 打印报告与执行合并
    print("\n" + "=" * 80)
    print(f"📋 【{entity_type.upper()} 智能合并计划表】")
    print("=" * 80)
    
    for idx, (obsolete, canonical) in enumerate(sorted(final_plan.items()), 1):
        print(f"   [{idx}] 📁 `{obsolete}` ➡️ 🎯 合并入: `{canonical}`")
        
    print("=" * 80)
    print(f"统计：本次计划将归并 {len(final_plan)} 个冗余同义文件，保留并凝聚至 {len(set(final_plan.values()))} 个规范核心节点中。")
    
    if is_dry_run:
        print("\n💡 提示：当前为[只读预览模式]，未对磁盘做任何修改。")
        print(f"   如果您确认上述合并计划无误，请在终端命令末尾加上 `--execute` 开启物理合并与超链自愈：")
        print(f"   👉 `python D:\\ARS\\merge_entities.py {entity_type} --execute`")
    else:
        print("\n🔥 物理大合并与全局超链自愈正式启动！请稍候...")
        # 执行物理合并
        for obsolete, canonical in final_plan.items():
            src_p = target_dir / obsolete
            dest_p = target_dir / canonical
            execute_merge_file(src_p, dest_p, entity_type, archive_dir)
            
        # 全局超链自愈修复
        print("[*] 正在递归自愈整个 Wiki 数据库中的所有学术引用链接...")
        total_links_fixed = 0
        for obsolete, canonical in final_plan.items():
            old_slug = obsolete.replace(".md", "")
            new_slug = canonical.replace(".md", "")
            fixed_count = update_global_wikilinks(old_slug, new_slug)
            total_links_fixed += fixed_count
            
        print("\n" + "=" * 80)
        print(f"🎉 恭喜！{entity_type.upper()} 库内部高精无损合并与全局超链自愈完美结束！")
        print(f"  ➜ 1. 成功归并碎片同义文件: {len(final_plan)} 个")
        print(f"  ➜ 2. 已安全移动隔离至归档目录: `wiki/{entity_type}_archive/`")
        print(f"  ➜ 3. 全局自愈更新所有 Markdown 引用链接: {total_links_fixed} 处！")
        print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
