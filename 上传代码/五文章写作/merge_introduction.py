# -*- coding: utf-8 -*-
"""
AutoSci Introduction Merger & Master Polish Station (Introduction Assembler)
===================================================================================
1. 自动扫描 `Introduction_Workspace/point_*.json`，按序号排序载入所有单点论证。
2. 【全局文献排重与重编号】：跨段落全局去重，为所有引用的文献分配连续的全局引文编号 [1], [2], [3]...
3. 【宏观引言范式检索 (Top 6 Raw Introductions)】：从知识库 460+ 篇文献中，智能检索并精选 6 篇与本文全局课题最贴合的顶刊完整引言原文。
4. 【终极学术缝合与润色 (DeepSeek Mode)】：以 6 篇顶刊引言的宏观起承转合、过渡句型与叙事节奏为标杆，对各论点段落进行无缝逻辑缝合，生成一气呵成的完整引言。
5. 【全局 PDF 物理归档】：将所有被引文献的原装 PDF 汇聚拷贝至 `Introduction_Final_Report/Source_PDFs/`（按全局 [1]... 命名），并将 6 篇引言范文拷贝至 `Exemplar_PDFs/`。
6. 导出终极引言手稿与全套溯源核对指南。
"""

import os
import sys
import re
import json
import shutil
import urllib.request
from pathlib import Path
from typing import List, Dict, Any, Tuple

# ⚙️ 路径配置
WORKSPACE_DIR = Path(r"D:\ARS\Introduction_Workspace")
FINAL_REPORT_DIR = Path(r"D:\ARS\Introduction_Final_Report")
WIKI_PAPERS_DIR = Path(r"D:\ARS\AutoSci-main\wiki\papers")
MASTER_REGISTRY_PATH = Path(r"D:\ARS\Literature_Library\master_registry.json")
DEEPSEEK_KEY_FILE_PATH = r"D:\ARS\deepseek_api_key.txt"

def get_deepseek_api_key() -> str | None:
    api_file = Path(DEEPSEEK_KEY_FILE_PATH)
    if api_file.exists():
        try:
            return api_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return os.environ.get("DEEPSEEK_API_KEY")

def format_author_name(full_name: str) -> str:
    parts = full_name.strip().split()
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    last = parts[-1]
    initials = "".join([f"{p[0]}." for p in parts[:-1] if p and p[0].isalpha()])
    return f"{last}, {initials}" if initials else last

def format_authors(authors_list: list) -> str:
    if not authors_list:
        return "Anon."
    formatted = []
    for a in authors_list:
        name = a.get("name", "") if isinstance(a, dict) else str(a)
        if name:
            formatted.append(format_author_name(name))
    if not formatted:
        return "Anon."
    if len(formatted) > 3:
        return "; ".join(formatted[:3]) + " et al."
    return "; ".join(formatted)

def extract_all_citations(text: str) -> set:
    found = set()
    matches = re.findall(r"\[([\d\s,\–\-]+)\]", text)
    for m in matches:
        chunks = re.split(r"[,;]\s*", m.strip())
        for c in chunks:
            c = c.strip()
            if not c:
                continue
            range_match = re.match(r"^(\d+)\s*[\–\-]\s*(\d+)$", c)
            if range_match:
                start, end = int(range_match.group(1)), int(range_match.group(2))
                for i in range(min(start, end), max(start, end) + 1):
                    found.add(i)
            elif c.isdigit():
                found.add(int(c))
    return found

def build_references_section(global_refs: List[Dict[str, Any]], paper_by_slug: Dict[str, Any]) -> str:
    lines = ["## 📚 References\n"]
    for ref in global_refs:
        g_idx = ref["global_index"]
        slug = ref["slug"]
        paper_record = paper_by_slug.get(slug, {})
        meta = paper_record.get("metadata", {})
        
        # Authors
        authors_raw = meta.get("authors", [])
        if authors_raw:
            authors_str = format_authors(authors_raw)
        elif ref.get("authors"):
            authors_str = ref.get("authors")
        else:
            authors_str = "Anon."
            
        # Title
        raw_title = meta.get("title") or ref.get("title") or "Untitled Paper"
        clean_title = re.sub(r"\s+", " ", raw_title).strip().rstrip(".")
        
        # Venue / Journal
        venue = meta.get("venue")
        if not venue and isinstance(meta.get("journal"), dict):
            venue = meta.get("journal", {}).get("name")
        venue_str = f" *{venue.strip()}*" if venue and venue.strip() else ""
        
        # Year
        year = meta.get("year") or ref.get("year") or "n.d."
        
        # DOI
        ext_ids = meta.get("externalIds", {}) if isinstance(meta.get("externalIds"), dict) else {}
        doi = ext_ids.get("DOI") or meta.get("doi") or ""
        doi_str = f" https://doi.org/{doi.strip()}" if doi else ""
        
        ref_line = f"[{g_idx}] {authors_str} {clean_title}.{venue_str} ({year}).{doi_str}"
        lines.append(ref_line)
        
    return "\n".join(lines)

def load_master_registry_papers() -> List[Dict[str, Any]]:
    if not MASTER_REGISTRY_PATH.exists():
        return []
    try:
        data = json.loads(MASTER_REGISTRY_PATH.read_text(encoding="utf-8"))
        return data.get("matched_papers", [])
    except Exception:
        return []

def load_all_raw_introductions() -> List[Dict[str, Any]]:
    """扫描 wiki/papers/ 目录，读取所有已提取完整 Raw Introduction 的文献"""
    if not WIKI_PAPERS_DIR.exists():
        return []
        
    intro_list = []
    for md_file in WIKI_PAPERS_DIR.glob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
            
        # 提取 Raw Introduction 部分
        intro_match = re.search(r"## Raw Introduction\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
        if not intro_match:
            continue
            
        raw_intro = intro_match.group(1).strip()
        if len(raw_intro) < 120:
            continue
            
        # 提取标题
        title = md_file.stem.replace("-", " ").title()
        title_match = re.search(r'^title:\s*["\']?(.*?)["\']?\s*$', text, re.MULTILINE)
        if title_match and title_match.group(1):
            title = title_match.group(1).strip()
        else:
            h1_match = re.search(r"^#\s+(.*?)$", text, re.MULTILINE)
            if h1_match and h1_match.group(1):
                title = h1_match.group(1).strip()
                
        intro_list.append({
            "slug": md_file.stem,
            "title": title,
            "raw_introduction": raw_intro,
            "filepath": md_file
        })
        
    return intro_list

def select_exemplar_introductions(topic: str, points_data: List[Dict[str, Any]], all_intros: List[Dict[str, Any]], api_key: str, limit: int = 6) -> List[Dict[str, Any]]:
    """
    两阶段筛选 6 篇与本文最贴近的顶刊完整引言：
    1. 基于关键词重合度粗筛出 Top 20 候选篇目
    2. 呼叫 DeepSeek 进行语义重排，精选出 6 篇最具宏观架构参考价值的引言原文
    """
    if not all_intros:
        return []
        
    print(f"\n📚 [宏观引言范式检索] 正在从知识库 ({len(all_intros)} 篇全引言库) 中智能匹配 Top {limit} 篇范文...")
    
    # 构建全文查询特征词
    query_text = topic + " " + " ".join([p.get("user_claim", "") for p in points_data])
    clean_words = re.findall(r"[a-zA-Z0-9\u4e00-\u9fa5]{2,}", query_text.lower())
    
    STOP_WORDS = {
        "the", "and", "of", "in", "to", "for", "with", "on", "at", "by", "from",
        "an", "as", "is", "are", "was", "were", "this", "that", "its", "we", "our",
        "can", "be", "has", "have", "been", "which", "study", "paper", "work", "论点",
        "研究", "分析", "探讨", "机制", "进行", "提出", "基于", "表明"
    }
    keywords = [w for w in clean_words if w not in STOP_WORDS]
    
    # 1. 词频与标题重合度初筛
    scored_candidates = []
    for item in all_intros:
        score = 0
        title_lower = item["title"].lower()
        intro_lower = item["raw_introduction"].lower()
        
        for kw in keywords:
            if kw in title_lower:
                score += 10
            intro_count = intro_lower.count(kw)
            score += min(intro_count, 5) * 2
            
        if score > 0:
            scored_candidates.append((score, item))
            
    scored_candidates.sort(key=lambda x: x[0], reverse=True)
    top_candidates = [item for _, item in scored_candidates[:20]]
    
    if len(top_candidates) <= limit:
        return top_candidates
        
    # 2. 呼叫 DeepSeek 进行精细语义重排 (LLM-as-a-Reranker)
    candidates_list_str = ""
    for idx, cand in enumerate(top_candidates, 1):
        snippet = cand["raw_introduction"][:250].replace("\n", " ")
        candidates_list_str += f"[{idx}] Title: {cand['title']}\n    Slug: {cand['slug']}\n    Snippet: {snippet}...\n\n"
        
    prompt = f"""You are a distinguished research director and journal editor in photophysics, nanomaterials, and physical chemistry.
We are writing an academic manuscript on:
**Title/Topic**: {topic}
**Core Outline Points**:
{chr(10).join([f"- Point {p.get('point_id')}: {p.get('user_claim')}" for p in points_data])}

Below is a pool of {len(top_candidates)} candidate papers with complete published Introduction sections.
Please select the TOP {limit} papers whose Introduction sections provide the best narrative flow, transition logic, structural tension, and thematic benchmark for writing our manuscript's Introduction.

### CANDIDATE POOL:
{candidates_list_str}

### OUTPUT FORMAT:
Respond with a strict JSON object with this exact schema (no markdown wrap, no conversational filler, just raw JSON):
{{
  "selected_indices": [1, 3, 5, 8, 12, 14]
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
            {"role": "system", "content": "You are a professional academic assistant. You select the best exemplar papers and output JSON only."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "thinking": {"type": "disabled"}
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
            content = resp_data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            res = json.loads(content.strip())
            indices = res.get("selected_indices", [])
            
            selected = []
            for i in indices:
                if isinstance(i, int) and 1 <= i <= len(top_candidates):
                    selected.append(top_candidates[i - 1])
                    
            if len(selected) >= 3:
                return selected[:limit]
    except Exception as e:
        print(f"  ⚠️ LLM 重排异常 ({e})，回退使用高频统计排序。")
        
    return top_candidates[:limit]

def stitch_and_polish_introduction(
    topic: str,
    points_data: List[Dict[str, Any]],
    global_ref_mapping: Dict[str, int],
    global_refs: List[Dict[str, Any]],
    exemplar_intros: List[Dict[str, Any]],
    api_key: str
) -> Dict[str, str] | None:
    total_refs = len(global_refs)
    required_citations_str = ", ".join([f"[{i}]" for i in range(1, total_refs + 1)])
    
    print(f"\n🧠 正在呼叫 DeepSeek 专家大脑进行全文逻辑平滑缝合与高阶学术润色...")
    print(f"   ➜ 已融合 {len(exemplar_intros)} 篇同领域顶刊引言原文作为宏观逻辑流向与过渡标杆！")
    print(f"   ➜ 全篇共 {total_refs} 篇参考文献 ([1]~[{total_refs}])，已开启【引用零丢失硬约束】！")
    
    # 1. 组装输入段落积木 (替换为全局连续引文 [1], [2], ...)
    body_draft_blocks = []
    for p in points_data:
        p_id = p["point_id"]
        claim = p["user_claim"]
        raw_en = p["english_text"]
        
        # 将局部引文编号 [1], [2] 替换为全局引文占位
        for local_ref in p.get("references", []):
            local_idx = local_ref["index"]
            slug = local_ref["slug"]
            global_idx = global_ref_mapping.get(slug)
            if global_idx:
                raw_en = re.sub(rf"\[{local_idx}\]", f"[{global_idx}]", raw_en)
                
        body_draft_blocks.append(f"### SECTION/POINT {p_id} (Target Claim: {claim}):\n{raw_en}\n")
        
    combined_drafts_str = "\n".join(body_draft_blocks)
    
    # 2. 组装 6 篇引言范文的精炼逻辑提要与转折脉络 (适度浓缩去噪，保留核心修辞与叙事节奏)
    exemplars_str = ""
    for idx, ex in enumerate(exemplar_intros, 1):
        raw_text = ex['raw_introduction'].strip()
        # 截取前 450 字符最具代表性的开篇立论与起承转合部分
        condensed_snippet = raw_text[:450].replace("\n", " ")
        exemplars_str += f"[{idx}] Title: {ex['title']}\n"
        exemplars_str += f"    Narrative Trajectory & Transition Style: \"{condensed_snippet}...\"\n\n"
        
    prompt = f"""You are a senior journal editor and academic writing master in physical chemistry, photophysics, and nanomaterials.
We have individually drafted the core paragraphs of an academic Introduction section for a paper on:
**Title/Topic**: {topic}

Your task is to integrate, polish, and synthesize these distinct paragraph blocks into a single, beautifully cohesive, peer-reviewed-level academic Introduction following the highest standards of Nature/JACS.

### 6 TOP-TIER JOURNAL INTRODUCTION EXEMPLARS (STYLE & RHETORICAL BENCHMARKS):
{exemplars_str}

### DRAFT PARAGRAPH BLOCKS TO INTEGRATE & POLISH:
{combined_drafts_str}

### MANDATORY CITATION CHECKLIST:
The input paragraphs collectively reference citations [1] through [{total_refs}]:
{required_citations_str}

### INTEGRATION & POLISHING GUIDELINES:
1. **MANDATORY ANTI-PLAGIARISM & PARAPHRASING (20%+ DISSIMILARITY)**:
   - **Zero Verbatim Copying**: NEVER copy sentence strings directly from the exemplars.
   - **Substantial Paraphrasing**: Every sentence MUST be uniquely synthesized to ensure **at least 20% linguistic/structural difference** from any exemplar text.
2. **Learn from the Exemplars (Narrative Arc & Transitions)**:
   - Maintain the standard four-phase top-tier introduction structure:
     * Phase 1 (Significance): Broad optoelectronic & physical significance of the components.
     * Phase 2 (Intrinsic Trade-offs & Bottlenecks): Physical dilemmas (e.g. low direct ISC, Auger competition, non-radiative losses, interfacial recombination).
     * Phase 3 (Hybrid Assemblies & The Unresolved Dilemma): How hybridizing quantum dots with molecular acceptors breaks trade-offs, yet how structural conformation and energy alignment drive TET vs. FRET competition remains unresolved.
     * Phase 4 (This Work - "Herein..."): Precise molecular engineering (rigid vs. flexible BODIPY), spectroscopic validation, and systematic mechanistic insights.
   - Borrow sophisticated transition formulations (e.g., *'Despite these notable achievements, a persistent bottleneck lies in...'*, *'To circumvent this intrinsic dilemma without compromising photostability...'*, *'However, a systematic correlation between ... remains largely uncharted...'*) to knit the disparate paragraphs into a seamless, unified prose.
3. **Organic Flow & Smoothness**: Eliminate all fragmented, blocky transitions; ensure every paragraph flows naturally into the next with compelling logical momentum.
4. **MANDATORY RULE - ZERO CITATION LOSS**:
   - Every scientific assertion and physical finding carries its global numerical citation (e.g., `[1]`, `[2]`, `[1-3]`, `[4, 5]`).
   - You MUST preserve EVERY SINGLE ONE of the citation numbers from [1] through [{total_refs}] next to the corresponding statement.
   - Do NOT invent new numbers, re-number, drop, or summarize away ANY citation numbers.
5. **Publication-Grade Tone**: Write in flawless, sophisticated Nature/JACS style English.

### OUTPUT FORMAT:
Respond with a strict JSON object with this exact schema (no markdown wrap, no conversational filler, just raw JSON):
{{
  "full_english_introduction": "The complete polished full English Introduction text with ALL global citations [1] through [{total_refs}]...",
  "full_chinese_translation": "The high-quality professional Chinese translation of the full Introduction preserving the exact same global citations [1] through [{total_refs}]..."
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
            {"role": "system", "content": "You are an elite academic editor. You polish and synthesize research introductions into unified text, strictly preserving all numerical citations, outputting valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 8192,
        "thinking": {"type": "disabled"}
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
            content = resp_data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            res = json.loads(content.strip())
            
            full_en = res.get("full_english_introduction", "")
            full_zh = res.get("full_chinese_translation", "")
            
            # 校验引用完整性
            expected_citations = set(range(1, total_refs + 1))
            cited_citations = extract_all_citations(full_en)
            missing_citations = expected_citations - cited_citations
            
            if missing_citations:
                print(f"  ⚠️ 首次润色生成检测到大模型遗漏了 {len(missing_citations)} 个引用编号: {sorted(missing_citations)}")
                print(f"  🔄 正在启动【引用零丢失自动修复引擎】进行精准定位回填...")
                
                missing_contexts = []
                for miss_idx in sorted(missing_citations):
                    ref_item = next((r for r in global_refs if r["global_index"] == miss_idx), None)
                    if ref_item:
                        missing_contexts.append(
                            f"- Citation [{miss_idx}]: Concept='{ref_item.get('concept_name')}', Context='{ref_item.get('logical_flow')}', Paper='{ref_item.get('title')}'"
                        )
                missing_context_str = "\n".join(missing_contexts)
                
                repair_prompt = f"""You are an elite academic manuscript editor in physical chemistry and photophysics.
In your previous polish of the Introduction, the following REQUIRED citation numbers were omitted during sentence synthesis:
{missing_context_str}

### CURRENT ENGLISH INTRODUCTION DRAFT:
{full_en}

### CURRENT CHINESE TRANSLATION DRAFT:
{full_zh}

### REPAIR INSTRUCTIONS:
1. Seamlessly insert the missing citation numbers [{', '.join(map(str, sorted(missing_citations)))}] into the corresponding scientific statements in the Introduction text where the concepts or mechanisms are discussed.
2. DO NOT delete, renumber, or alter ANY existing citation numbers.
3. Keep the overall narrative fluent, elegant, and high-impact.
4. Output the updated English Introduction and corresponding Chinese Translation with ALL citations [1] through [{total_refs}] strictly preserved.

### OUTPUT FORMAT:
Respond with a strict JSON object with this exact schema (no markdown, just raw JSON):
{{
  "full_english_introduction": "The corrected English text containing ALL citations [1] through [{total_refs}]...",
  "full_chinese_translation": "The corrected Chinese text containing ALL citations [1] through [{total_refs}]..."
}}
"""
                repair_data = {
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "You are a professional academic editor performing precise citation restoration. Output valid JSON only."},
                        {"role": "user", "content": repair_prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 8192,
                    "thinking": {"type": "disabled"}
                }
                try:
                    req2 = urllib.request.Request(url, data=json.dumps(repair_data).encode("utf-8"), headers=headers, method="POST")
                    with urllib.request.urlopen(req2, timeout=90) as response2:
                        resp_data2 = json.loads(response2.read().decode("utf-8"))
                        content2 = resp_data2["choices"][0]["message"]["content"].strip()
                        if content2.startswith("```"):
                            content2 = re.sub(r"^```(?:json)?\s*", "", content2)
                            content2 = re.sub(r"\s*```$", "", content2)
                        repaired_res = json.loads(content2.strip())
                        if repaired_res and "full_english_introduction" in repaired_res:
                            full_en = repaired_res["full_english_introduction"]
                            full_zh = repaired_res.get("full_chinese_translation", full_zh)
                            
                            new_cited = extract_all_citations(full_en)
                            new_missing = expected_citations - new_cited
                            if not new_missing:
                                print(f"  ✅ 修复成功！全篇所有 {len(expected_citations)} 篇参考文献已 100% 完整融入正文！")
                            else:
                                print(f"  ℹ️ 二次修复后仍有个别编号未直接嵌入正文: {sorted(new_missing)} (已在文末 References 清单全量呈现)")
                except Exception as e:
                    print(f"  ⚠️ 自动修复调用异常: {e}")
                    
            return {
                "full_english_introduction": full_en,
                "full_chinese_translation": full_zh
            }
    except Exception as e:
        print(f"❌ 调用 DeepSeek API 发生错误: {e}")
        return None

def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    print("=" * 80)
    print("🚀 AutoSci 引言总成与全局润色大师 (Introduction Master Assembler)")
    print("=" * 80)
    
    api_key = get_deepseek_api_key()
    if not api_key:
        print("❌ 错误: 无法加载 DeepSeek API key，请检查 D:\\ARS\\deepseek_api_key.txt！")
        return
        
    # 兼容支持 Introduction_Workspace 与 Intro_Workspace
    target_workspace = WORKSPACE_DIR
    if not target_workspace.exists():
        alt_ws = Path(r"D:\ARS\Intro_Workspace")
        if alt_ws.exists():
            target_workspace = alt_ws
        else:
            print(f"❌ 错误: 找不到工作区目录 `{WORKSPACE_DIR}`！请先运行 `write_intro_point.py` 撰写论点。")
            return
            
    json_files = list(target_workspace.glob("point_*.json"))
    if not json_files:
        print(f"❌ 错误: 工作区 `{target_workspace}` 内未找到任何已保存的 `point_*.json` 文件！")
        print("   👉 请先运行: `python D:\\ARS\\write_intro_point.py` 撰写至少一个观点。")
        return
        
    # 智能按 Point ID 数值排序
    def extract_id(p: Path) -> int:
        match = re.search(r"point_(\d+)\.json", p.name)
        return int(match.group(1)) if match else 999
        
    sorted_json_files = sorted(json_files, key=extract_id)
    print(f"[*] 成功检测到 {len(sorted_json_files)} 个已精修的论点积木:")
    
    points_data = []
    for f in sorted_json_files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            points_data.append(data)
            print(f"   📍 [论点 {data.get('point_id')}] {data.get('user_claim')[:50]}...")
        except Exception as e:
            print(f"   ⚠️ 读取 {f.name} 失败: {e}")
            
    if not points_data:
        print("❌ 错误: 没有有效的数据可供合并！")
        return
        
    # 1. 全局文献排重与重编号
    print("\n[*] 正在进行全局跨段落文献去重与全局 [1]...[N] 重新编号...")
    global_refs = []
    global_ref_mapping = {} # slug -> global_index (1-based)
    
    for p in points_data:
        for ref in p.get("references", []):
            slug = ref["slug"]
            if slug not in global_ref_mapping:
                new_idx = len(global_refs) + 1
                global_ref_mapping[slug] = new_idx
                ref_copy = dict(ref)
                ref_copy["global_index"] = new_idx
                ref_copy["used_in_points"] = [p["point_id"]]
                global_refs.append(ref_copy)
            else:
                # 记录该文献在多个 Point 中被复用
                existing_ref = next(r for r in global_refs if r["slug"] == slug)
                if p["point_id"] not in existing_ref["used_in_points"]:
                    existing_ref["used_in_points"].append(p["point_id"])
                    
    print(f"  ➜ 去重对账完毕！全篇共涉及 {len(global_refs)} 篇独立核心顶刊文献支撑。")
    
    # 2. 询问大主题
    topic = input("\n📝 请确认整篇引言的大主题/论文暂定标题 (直接回车使用默认):\n   👉 ").strip()
    if not topic:
        topic = "Efficient Triplet Energy Transfer from Perovskite Quantum Dots to Organic BODIPY Acceptors"
        
    # 3. 检索 6 篇最相似的顶刊完整引言
    all_raw_intros = load_all_raw_introductions()
    exemplar_intros = select_exemplar_introductions(topic, points_data, all_raw_intros, api_key, limit=6)
    print(f"\n✨ [范式确定] 本次全文润色成功锁定了以下 6 篇顶刊引言范文:")
    for idx, ex in enumerate(exemplar_intros, 1):
        print(f"   📖 [{idx}] {ex['title']}")
        
    # 4. 执行最终全文润色与缝合 (融合 6 篇完整引言范式)
    polished_result = stitch_and_polish_introduction(
        topic, points_data, global_ref_mapping, global_refs, exemplar_intros, api_key
    )
    if not polished_result:
        print("❌ 错误: 全文润色失败。")
        return
        
    full_en = polished_result.get("full_english_introduction", "")
    full_zh = polished_result.get("full_chinese_translation", "")
    
    # 5. 汇聚并归档所有全局 PDF
    FINAL_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    final_pdfs_dir = FINAL_REPORT_DIR / "Source_PDFs"
    if final_pdfs_dir.exists():
        try:
            shutil.rmtree(final_pdfs_dir)
        except Exception:
            pass
    final_pdfs_dir.mkdir(parents=True, exist_ok=True)
    
    exemplar_pdfs_dir = FINAL_REPORT_DIR / "Exemplar_PDFs"
    if exemplar_pdfs_dir.exists():
        try:
            shutil.rmtree(exemplar_pdfs_dir)
        except Exception:
            pass
    exemplar_pdfs_dir.mkdir(parents=True, exist_ok=True)
    
    matched_papers = load_master_registry_papers()
    paper_by_slug = {p.get("slug"): p for p in matched_papers if p.get("slug")}
    
    print("\n🔍 正在将整篇引言引用的所有原装 PDF 汇聚归档至 Source_PDFs/...")
    for ref in global_refs:
        slug = ref["slug"]
        g_idx = ref["global_index"]
        paper_record = paper_by_slug.get(slug)
        
        ref["final_pdf_found"] = False
        ref["final_pdf_name"] = None
        
        if paper_record:
            meta = paper_record.get("metadata", {})
            author_names = [a.get("name", "") for a in meta.get("authors", [])]
            first_author = author_names[0].split()[-1] if author_names else "Author"
            year = meta.get("year", "Year")
            
            pdf_path_str = paper_record.get("pdf_path")
            if pdf_path_str:
                src_pdf = Path(pdf_path_str)
                if src_pdf.exists():
                    clean_pdf_name = f"[{g_idx}] [{year}] {first_author}.pdf"
                    target_pdf_path = final_pdfs_dir / clean_pdf_name
                    try:
                        shutil.copy(str(src_pdf), str(target_pdf_path))
                        ref["final_pdf_found"] = True
                        ref["final_pdf_name"] = clean_pdf_name
                        print(f"  ➜ 🟢 [{g_idx}] ➡️ 已归档: '{clean_pdf_name}' (用于论点: {ref['used_in_points']})")
                    except Exception as e:
                        print(f"  ➜ ⚠️ 拷贝 PDF 异常: {e}")
                        
    # 归档 6 篇范文 PDF
    print("\n🔍 正在将 6 篇宏观引言范文的 PDF 拷贝至 Exemplar_PDFs/...")
    for idx, ex in enumerate(exemplar_intros, 1):
        ex_slug = ex["slug"]
        ex_record = paper_by_slug.get(ex_slug)
        ex["pdf_found"] = False
        ex["pdf_name"] = None
        if ex_record:
            meta = ex_record.get("metadata", {})
            author_names = [a.get("name", "") for a in meta.get("authors", [])]
            first_author = author_names[0].split()[-1] if author_names else "Author"
            year = meta.get("year", "Year")
            pdf_path_str = ex_record.get("pdf_path")
            if pdf_path_str:
                src_pdf = Path(pdf_path_str)
                if src_pdf.exists():
                    ex_pdf_name = f"[Exemplar_{idx}] [{year}] {first_author}.pdf"
                    target_ex_pdf = exemplar_pdfs_dir / ex_pdf_name
                    try:
                        shutil.copy(str(src_pdf), str(target_ex_pdf))
                        ex["pdf_found"] = True
                        ex["pdf_name"] = ex_pdf_name
                        print(f"  ➜ 📖 [范文 {idx}] ➡️ 已归档: '{ex_pdf_name}'")
                    except Exception:
                        pass
                        
    # 6. 生成终极手稿与全局核对指南
    ref_section_en = build_references_section(global_refs, paper_by_slug)
    
    draft_lines = [
        f"# {topic}\n",
        "## 📄 Full Academic Introduction (English - Continuous Citations)",
        f"{full_en}\n",
        f"{ref_section_en}\n",
        "## 🇨🇳 中文完整学术引言 (Chinese Translation)",
        f"{full_zh}\n",
        f"{ref_section_en}\n"
    ]
    draft_file = FINAL_REPORT_DIR / "Introduction_Final_Draft.md"
    draft_file.write_text("\n".join(draft_lines), encoding="utf-8")
    
    # 溯源核对表
    guide_lines = [
        f"# 🔍 整篇引言 (Introduction) 全局事实溯源与文献核对指南\n",
        f"**论文课题**: {topic}\n",
        "本指南按整篇论文连续引文序号 `[1]`, `[2]`, `[3]` ... 严格建立了**全局文献溯源档案**。\n",
        "所有引用的原装 PDF 已完整拷贝至 `Source_PDFs/`，6 篇宏观引言范文已拷贝至 `Exemplar_PDFs/`，双击即可查阅！\n",
        "## 🏛️ 全文宏观逻辑架构与段落流向参考的 6 篇顶刊引言范文 (Macro Narrative Exemplars)",
        "| 范文序号 | 范文 PDF 文件 (位于 `Exemplar_PDFs/`) | 完整论文标题与元数据 |",
        "|---|---|---|"
    ]
    for idx, ex in enumerate(exemplar_intros, 1):
        pdf_col = f"📖 `{ex.get('pdf_name')}`" if ex.get("pdf_found") else "📁 知识库收录"
        ex_record = paper_by_slug.get(ex["slug"], {})
        meta = ex_record.get("metadata", {})
        year = meta.get("year", "N/A")
        authors = ", ".join([a.get("name", "") for a in meta.get("authors", [])][:2])
        guide_lines.append(f"| **[范文 {idx}]** | {pdf_col} | **{ex['title']}**<br>*{authors} ({year})* |")
        
    guide_lines.append("\n## 📚 全局文献与 PDF 文件核对表")
    guide_lines.append("| 全局引文 | 物理 PDF 文件 (位于 `Source_PDFs/`) | 完整标题、作者与 DOI 元数据 | 支撑的论点编号 | 检索概念 |")
    guide_lines.append("|---|---|---|---|---|")
    for ref in global_refs:
        pdf_col = f"📁 `{ref['final_pdf_name']}`" if ref["final_pdf_found"] else "❌ 未配对"
        slug = ref["slug"]
        paper_record = paper_by_slug.get(slug, {})
        meta = paper_record.get("metadata", {})
        ext_ids = meta.get("externalIds", {}) if isinstance(meta.get("externalIds"), dict) else {}
        doi = ext_ids.get("DOI") or meta.get("doi") or ""
        doi_badge = f"<br>🔗 `DOI: {doi}`" if doi else ""
        
        title_col = f"**{ref['title']}**<br>*{ref['authors']} ({ref['year']})*{doi_badge}"
        points_str = ", ".join([f"论点 {p}" for p in ref["used_in_points"]])
        guide_lines.append(f"| **[{ref['global_index']}]** | {pdf_col} | {title_col} | `{points_str}` | `{ref['concept_name']}` |")
        
    guide_lines.append("\n## 📝 全局顶刊真题段落精细摘录 (Verbatim Literature Excerpts):\n")
    for ref in global_refs:
        points_str = ", ".join([f"论点 {p}" for p in ref["used_in_points"]])
        slug = ref["slug"]
        paper_record = paper_by_slug.get(slug, {})
        meta = paper_record.get("metadata", {})
        ext_ids = meta.get("externalIds", {}) if isinstance(meta.get("externalIds"), dict) else {}
        doi = ext_ids.get("DOI") or meta.get("doi") or ""
        
        guide_lines.append(f"### 📍 引文 [{ref['global_index']}]：{ref['title']}")
        guide_lines.append(f"- **元数据**: {ref['authors']} ({ref['year']})")
        if doi:
            guide_lines.append(f"- **DOI**: [{doi}](https://doi.org/{doi})")
        guide_lines.append(f"- **服务论点**: {points_str}")
        if ref["final_pdf_found"]:
            guide_lines.append(f"- **对应 PDF**: 请双击 `Source_PDFs/{ref['final_pdf_name']}`")
        guide_lines.append(f"- **论证流向**: {ref['logical_flow']}")
        guide_lines.append(f"- **顶刊英文原文**: > *\"{ref['original_english_text']}\"*")
        guide_lines.append("\n" + "-" * 60 + "\n")
        
    guide_file = FINAL_REPORT_DIR / "Verification_Guide_Global.md"
    guide_file.write_text("\n".join(guide_lines), encoding="utf-8")
    
    print("\n" + "=" * 80)
    print("🎉 恭喜！整篇学术引言总成与全局润色已圆满完成！")
    print(f"  ➜ 最终交付目录: {FINAL_REPORT_DIR}")
    print(f"  ➜ 1. 终极中英双语引言手稿: Introduction_Final_Report\\Introduction_Final_Draft.md")
    print(f"  ➜ 2. 全局连续重命名的原装 PDF 库: Introduction_Final_Report\\Source_PDFs\\ （[1], [2]... 双击即看）")
    print(f"  ➜ 3. 6 篇宏观引言范文 PDF 库: Introduction_Final_Report\\Exemplar_PDFs\\ （[Exemplar_1]... 双击即看）")
    print(f"  ➜ 4. 全局事实溯源与核对指南: Introduction_Final_Report\\Verification_Guide_Global.md")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
