# -*- coding: utf-8 -*-
"""
AutoSci Full Introduction Master Station (Outline-Guided Paragraph RAG Studio)
===================================================================================
架构核心：【大纲统领下的分段精准推进 (Outline-Guided Paragraph RAG)】
1. 【全局大纲驱动】：以整篇引言的 4 段式宏观叙事大纲为故事线骨架。
2. 【分段精准击破】：每一段独立从 2000+ 学术概念库中按需检索 Top 8 候选文献。
3. 【自上而下择优录用】：大模型根据本段目标与全篇大纲，自主择优引用 3~6 篇最契合的文献，不契合的坚决舍弃，绝不强行堆砌。
4. 【动态上文传递】：撰写后文时自动注入前序段落正文，确保起承转合行云流水、一气呵成。
5. 【全局重排与物理归档】：自动分配全局连续引文 `[1]`, `[2]`...，生成 Nature 级 References，物理拷贝所有引用的原装 PDF 并生成全套事实核对指南。
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
WIKI_CONCEPTS_DIR = Path(r"D:\ARS\AutoSci-main\wiki\concepts")
LITERATURE_LIBRARY_DIR = Path(r"D:\ARS\Literature_Library")
MASTER_REGISTRY_PATH = LITERATURE_LIBRARY_DIR / "master_registry.json"
DEEPSEEK_KEY_FILE_PATH = r"D:\ARS\deepseek_api_key.txt"
FINAL_REPORT_DIR = Path(r"D:\ARS\Introduction_Final_Report")

def get_deepseek_api_key() -> str | None:
    api_file = Path(DEEPSEEK_KEY_FILE_PATH)
    if api_file.exists():
        try:
            return api_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return os.environ.get("DEEPSEEK_API_KEY")

def load_custom_skill(workspace_dir: Path | None = None) -> str:
    """加载用户自定义 Skill MD 或 Prompt 扩展 (支持环境变量、工作区 custom_skill.md 或全局配置)"""
    env_skill = os.environ.get("AUTOSCI_CUSTOM_SKILL", "").strip()
    if env_skill:
        return env_skill
    env_file = os.environ.get("AUTOSCI_SKILL_FILE", "").strip()
    if env_file and Path(env_file).exists():
        try:
            return Path(env_file).read_text(encoding="utf-8").strip()
        except Exception:
            pass
    if workspace_dir:
        ws_skill = workspace_dir / "custom_skill.md"
        if ws_skill.exists():
            try:
                return ws_skill.read_text(encoding="utf-8").strip()
            except Exception:
                pass
    return ""

def load_master_registry_papers() -> List[Dict[str, Any]]:
    if not MASTER_REGISTRY_PATH.exists():
        return []
    try:
        data = json.loads(MASTER_REGISTRY_PATH.read_text(encoding="utf-8"))
        return data.get("matched_papers", [])
    except Exception:
        return []

def load_local_concept_chunks() -> List[Dict[str, Any]]:
    """智能解析本地概念 markdown 文件，载入全库所有已提取的 Introduction Chunks"""
    chunks = []
    if not WIKI_CONCEPTS_DIR.exists():
        return []
        
    for file_path in WIKI_CONCEPTS_DIR.glob("*.md"):
        try:
            content = file_path.read_text(encoding="utf-8")
            fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
            concept_name = file_path.stem
            if fm_match:
                fm_text = fm_match.group(1)
                title_match = re.search(r'title:\s*"([^"]+)"', fm_text)
                if title_match:
                    concept_name = title_match.group(1)
            
            sections = re.split(r"###\s+\[\[(.*?)\]\]\s*中的引言段落", content)
            for i in range(1, len(sections), 2):
                paper_slug = sections[i].strip()
                sec_body = sections[i+1]
                
                flow_match = re.search(r"\*\*论证流向\s*\(Logical Flow\):\*\*\s*(.*?)(\n|$)", sec_body)
                flow = flow_match.group(1).strip() if flow_match else "Unspecified"
                
                # 稳健提取英文原文
                eng_text = ""
                eng_split = re.split(r"\*\*文献英文原文\s*\(Original English Text\):\*\*", sec_body)
                if len(eng_split) > 1:
                    raw_block = re.split(r"\*\*中文翻译与学术提炼|\n###|\Z", eng_split[1])[0]
                    lines = [line.strip().lstrip(">").strip() for line in raw_block.strip().split("\n") if line.strip()]
                    eng_text = " ".join(lines)
                    eng_text = re.sub(r"\s+", " ", eng_text)
                
                # 提取中文翻译
                chinese_trans = ""
                trans_split = re.split(r"\*\*中文翻译与学术提炼\s*\(Chinese Translation\):\*\*", sec_body)
                if len(trans_split) > 1:
                    chinese_trans = re.split(r"\n###|\Z", trans_split[1])[0].strip()
                
                if eng_text:
                    chunks.append({
                        "concept_slug": file_path.stem,
                        "concept_name": concept_name,
                        "paper_slug": paper_slug,
                        "logical_flow": flow,
                        "original_english_text": eng_text,
                        "chinese_translation": chinese_trans
                    })
        except Exception:
            pass
    return chunks

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

def decompose_user_thoughts_to_outline(
    topic: str,
    raw_thoughts: str,
    api_key: str
) -> List[Dict[str, Any]]:
    """
    呼叫 DeepSeek 根据用户自由输入的研究思路/要点草稿，
    智能规划并自适应拆解为 3 至 6 个逻辑严密、层层递进的学术引言段落大纲。
    """
    prompt = f"""You are a distinguished research director and senior journal editor (e.g., JACS, Nature Communications, Advanced Materials).
A researcher has provided their raw research ideas, experimental narrative, and key points for an academic Introduction section.

### PAPER TITLE / TOPIC:
"{topic}"

### USER'S RAW THOUGHTS & INTRODUCTION OUTLINE:
\"\"\"
{raw_thoughts}
\"\"\"

### TASK:
Analyze the researcher's input and intelligently decompose and structure the Introduction into **3 to 6 cohesive, progressive, and logically robust narrative blocks (paragraphs)**.

### ARCHITECTURAL PRINCIPLES (3 to 6 Blocks):
1. **Block 1 (Significance & Foundation)**: Broad optoelectronic/physical significance, material advantages, and strategic value.
2. **Block 2 (Bottlenecks & Physical Dilemmas)**: Intrinsic trade-offs, efficiency bottlenecks, loss pathways, or challenges in traditional approaches.
3. **Block 3 / Intermediate Blocks (Strategic Evolution / Mechanistic Controversy)**: Hybridization opportunities, specific molecular/interfacial mechanics, and unresolved scientific controversies (e.g. conformational effects, energy driving forces, competition between TET, FRET, and charge separation).
4. **Final Block (This Work & System Design - Herein...)**: The specific experimental systems compared (e.g. molecular structures, flexible vs rigid), experimental/spectroscopic techniques, revealed physical mechanisms, and broader design rules.

*Note: Choose the optimal number of blocks (between 3 and 6) based on the richness and complexity of the user's input.*

### OUTPUT FORMAT:
Respond with a strict JSON object with this exact schema (no markdown wrap, raw JSON only):
{{
  "blocks": [
    {{
      "para_idx": 1,
      "title": "Short Descriptive Title (e.g., 宏观背景与重要性)",
      "goal": "Detailed logical target and scientific points for this paragraph, written clearly so that literature can be retrieved and argued effectively."
    }},
    {{
      "para_idx": 2,
      "title": "Short Descriptive Title (e.g., 传统受体瓶颈与物理矛盾)",
      "goal": "Detailed logical target and scientific points for paragraph 2..."
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
            {"role": "system", "content": "You are a professional academic manuscript editor. You decompose research ideas into 3-6 logical paragraphs and output valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
        "thinking": {"type": "disabled"}
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
            content = resp_data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            res = json.loads(content.strip())
            blocks = res.get("blocks", [])
            if isinstance(blocks, list) and len(blocks) >= 2:
                for idx, b in enumerate(blocks, 1):
                    b["para_idx"] = idx
                return blocks
    except Exception as e:
        print(f"  ⚠️ 自动拆解逻辑大纲异常 ({e})，启用智能默认拆解方案。")
        
    return [
        {"para_idx": 1, "title": "宏观背景与体系优势", "goal": raw_thoughts[:200]},
        {"para_idx": 2, "title": "传统瓶颈与物理矛盾", "goal": "分析传统方案在效率、稳定性与能量损失方面的瓶颈"},
        {"para_idx": 3, "title": "杂化体系与微观机制争议", "goal": "阐述杂化体系界面能量/电荷转移的动力学竞争与争议"},
        {"para_idx": 4, "title": "本文系统工作与设计原则", "goal": "总结本文选取的对比体系、表征手段与核心物理规律"}
    ]

def extract_search_terms_for_paragraph(
    topic: str,
    para_idx: int,
    para_goal: str,
    api_key: str
) -> Dict[str, List[str]]:
    """利用 DeepSeek 从当前段落目标中提炼中英文学术关键词与概念搜索词"""
    prompt = f"""You are a senior academic taxonomist in photophysics, nanomaterials, and physical chemistry.
We are writing an academic manuscript on:
**Paper Topic**: {topic}

### PARAGRAPH {para_idx} GOAL & LOGICAL TARGET:
"{para_goal}"

### TASK:
Extract two categories of search parameters to retrieve the best supporting literature excerpts from our database:
1. **Target Concept Slugs & English Keywords**: Standard academic concepts and keywords (e.g., 'perovskite-quantum-dots', 'triplet-energy-transfer', 'intersystem-crossing', 'conformation-controlled').
2. **Contrasting/Bottleneck Terms**: Terms related to limitations, losses, or trade-offs (e.g., 'auger-recombination', 'heavy-atom-effect', 'fret-competition', 'radiative-loss').

### OUTPUT FORMAT:
Respond with a strict JSON object (no markdown wrap, raw JSON only):
{{
  "supporting_concepts": ["concept-slug-1", "concept-slug-2", "concept-slug-3"],
  "supporting_keywords": ["keyword1", "keyword2", "keyword3", "keyword4"],
  "contrasting_concepts": ["bottleneck-slug-1", "bottleneck-slug-2"],
  "contrasting_keywords": ["loss1", "tradeoff2", "limitation3"]
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
            {"role": "system", "content": "You are a professional taxonomy extractor. Output valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "thinking": {"type": "disabled"}
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
            content = resp_data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            return json.loads(content.strip())
    except Exception as e:
        print(f"  ⚠️ 提取段落关键词微小异常: {e}")
        return {
            "supporting_concepts": [],
            "supporting_keywords": [w for w in re.findall(r"[a-zA-Z]{3,}", para_goal.lower())],
            "contrasting_concepts": [],
            "contrasting_keywords": []
        }

def rank_and_select_candidates_for_paragraph(
    para_goal: str,
    search_terms: Dict[str, List[str]],
    all_chunks: List[Dict[str, Any]],
    paper_by_slug: Dict[str, Any],
    api_key: str,
    limit: int = 8
) -> List[Dict[str, Any]]:
    """两阶段为当前段落精选 Top 8 候选文献片段（粗筛 + DeepSeek 语义精排）"""
    supp_concepts = [c.lower() for c in search_terms.get("supporting_concepts", [])]
    supp_kws = [k.lower() for k in search_terms.get("supporting_keywords", [])]
    cont_concepts = [c.lower() for c in search_terms.get("contrasting_concepts", [])]
    cont_kws = [k.lower() for k in search_terms.get("contrasting_keywords", [])]

    # 1. 粗筛打分
    scored_chunks = []
    seen_papers = set()
    
    for chunk in all_chunks:
        c_slug = chunk["concept_slug"].lower()
        c_name = chunk["concept_name"].lower()
        orig_text = chunk["original_english_text"].lower()
        flow = chunk["logical_flow"].lower()
        p_slug = chunk["paper_slug"]
        
        score = 0
        perspective = "正向立论"
        
        for sc in supp_concepts:
            if sc in c_slug:
                score += 15
        for sk in supp_kws:
            if sk in c_name:
                score += 8
            if sk in orig_text:
                score += min(orig_text.count(sk), 4) * 2
            if sk in flow:
                score += 4
                
        cont_score = 0
        for cc in cont_concepts:
            if cc in c_slug:
                cont_score += 15
        for ck in cont_kws:
            if ck in c_name:
                cont_score += 8
            if ck in orig_text:
                cont_score += min(orig_text.count(ck), 4) * 2
            if ck in flow:
                cont_score += 4
                
        if cont_score > score:
            score = cont_score
            perspective = "瓶颈/矛盾/对比"
            
        if score > 0:
            paper_meta = paper_by_slug.get(p_slug, {}).get("metadata", {})
            title = paper_meta.get("title") or chunk["paper_slug"].replace("-", " ").title()
            year = paper_meta.get("year", "N/A")
            authors_list = paper_meta.get("authors", [])
            authors_str = format_authors(authors_list)
            
            chunk_copy = dict(chunk)
            chunk_copy["score"] = score
            chunk_copy["perspective"] = perspective
            chunk_copy["title"] = title
            chunk_copy["year"] = year
            chunk_copy["authors"] = authors_str
            scored_chunks.append((score, chunk_copy))
            
    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    
    # 保证候选文献多样性 (同篇论文只取最高分的一个片段)
    pre_candidates = []
    for _, item in scored_chunks:
        p_slug = item["paper_slug"]
        if p_slug not in seen_papers:
            seen_papers.add(p_slug)
            pre_candidates.append(item)
        if len(pre_candidates) >= 20:
            break
            
    if len(pre_candidates) <= limit:
        return pre_candidates
        
    # 2. DeepSeek 语义精排出 Top 8
    candidates_desc = ""
    for idx, cand in enumerate(pre_candidates, 1):
        snippet = cand["original_english_text"][:220].replace("\n", " ")
        candidates_desc += f"[Cand {idx}] Title: {cand['title']} ({cand['year']})\n    Perspective: {cand['perspective']}\n    Logical Flow: {cand['logical_flow']}\n    Excerpt: \"{snippet}...\"\n\n"
        
    prompt = f"""You are a principal investigator in photophysics and materials science.
We are writing a specific paragraph of an academic Introduction on the following topic:
**Paragraph Target**: "{para_goal}"

Below is a pool of {len(pre_candidates)} candidate literature excerpts from our local library.
Select the TOP {limit} most authoritative, methodologically relevant, and persuasive candidate excerpts that best serve to construct this specific paragraph.

### CANDIDATE POOL:
{candidates_desc}

### OUTPUT FORMAT:
Respond with a strict JSON object (no markdown wrap, raw JSON only):
{{
  "selected_indices": [1, 2, 4, 7, 9, 12, 15, 18]
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
            {"role": "system", "content": "You are a professional literature selector. Output valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "thinking": {"type": "disabled"}
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
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
                if isinstance(i, int) and 1 <= i <= len(pre_candidates):
                    selected.append(pre_candidates[i - 1])
            if len(selected) >= 4:
                return selected[:limit]
    except Exception as e:
        print(f"  ⚠️ LLM 精排异常 ({e})，回退使用综合得分排序。")
        
    return pre_candidates[:limit]

def generate_paragraph_with_selective_citations(
    topic: str,
    full_outline_text: str,
    para_idx: int,
    para_goal: str,
    previous_paragraphs_text: str,
    candidates: List[Dict[str, Any]],
    api_key: str,
    workspace_dir: Path | None = None
) -> Dict[str, Any] | None:
    """呼叫 DeepSeek 在全局大纲统领下撰写当前自然段，并自主择优引用候选文献"""
    
    # 构建候选文献池供模型按需选用
    candidates_prompt_block = ""
    for idx, cand in enumerate(candidates, 1):
        cand_id = f"CAND_{idx}"
        cand["cand_id"] = cand_id
        candidates_prompt_block += f"[{cand_id}] Paper: {cand['title']} ({cand['authors']}, {cand['year']})\n"
        candidates_prompt_block += f"    Role: {cand['perspective']} | Concept: {cand['concept_name']}\n"
        candidates_prompt_block += f"    Verbatim Excerpt: \"{cand['original_english_text']}\"\n\n"
        
    prev_context = previous_paragraphs_text.strip() if previous_paragraphs_text.strip() else "(This is Paragraph 1, no preceding text.)"

    # 加载用户自定义 Skill
    custom_skill = load_custom_skill(workspace_dir)
    custom_skill_block = ""
    if custom_skill:
        custom_skill_block = f"""
### 🌟 USER CUSTOM SKILL & SPECIAL WRITING INSTRUCTIONS (HIGHEST PRIORITY):
The user has provided the following specific domain skill instructions and writing guidelines. You MUST strictly adhere to them:
{custom_skill}
"""
    
    prompt = f"""You are a world-class academic writing consultant and senior editor in physical chemistry, photophysics, and nanomaterials.
We are writing a high-impact, peer-reviewed Introduction (Nature/JACS standard) for the manuscript:
**Paper Topic**: {topic}

{custom_skill_block}

### COMPLETE 4-ACT INTRODUCTION OUTLINE (THE OVERALL NARRATIVE ARC):
{full_outline_text}

### PRECEDING PARAGRAPHS ALREADY WRITTEN (FOR SEAMLESS TRANSITIONS & RHETORICAL CONTINUITY):
{prev_context}

---

### YOUR CURRENT MISSION:
Write **Paragraph {para_idx}** based on the following specific paragraph objective:
"{para_goal}"

### AVAILABLE CANDIDATE LITERATURE EXCERPTS FOR THIS PARAGRAPH:
{candidates_prompt_block}

### WRITING & SELECTIVE CITATION GUIDELINES:
1. **MANDATORY ANTI-PLAGIARISM & PARAPHRASING (20%+ DISSIMILARITY)**:
   - **Zero Verbatim Copying**: NEVER copy phrases or sentences verbatim from candidate excerpts or benchmark papers.
   - **Substantial Paraphrasing**: Every sentence MUST be thoroughly rephrased and synthesized so that there is **at least 20% linguistic/structural difference** compared to any literature excerpt.
2. **Top-Down Narrative Integration**:
   - Seamlessly connect with the preceding text. Maintain natural rhetorical momentum, sharp scientific tension, and fluent transition.
   - Do NOT write in a mechanical 'point-by-point' or 'paper-by-paper' summary style. Write a cohesive, elegant academic paragraph.
3. **SELECTIVE CITATION (CRUCIAL)**:
   - You have {len(candidates)} candidate papers available ([CAND_1] to [CAND_{len(candidates)}]).
   - **Selectively cite ONLY the candidate papers that genuinely and authoritatively support the scientific statements in this paragraph (typically 3 to 6 papers).**
   - If a candidate paper deviates from the main narrative or is redundant, **DO NOT CITE IT**. We strictly prioritize narrative elegance over forced citations.
   - Mark citations in the text using exact tags like `[CAND_1]`, `[CAND_2]`, or `[CAND_1, CAND_3]`.
4. **Publication-Grade Style**: Use sophisticated, precise vocabulary suitable for JACS / Nature Communications.

### OUTPUT FORMAT:
Respond with a strict JSON object with this exact schema (no markdown wrap, raw JSON only):
{{
  "english_paragraph": "The polished English paragraph with selective [CAND_X] citations...",
  "chinese_translation": "The high-quality professional Chinese translation preserving the exact same [CAND_X] tags...",
  "used_candidate_ids": ["CAND_1", "CAND_2", "CAND_5"]
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
            {"role": "system", "content": "You are an elite academic manuscript writer. Output valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
        "thinking": {"type": "disabled"}
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=90) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
            content = resp_data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            return json.loads(content.strip())
    except Exception as e:
        print(f"❌ 调用 DeepSeek 撰写第 {para_idx} 段发生错误: {e}")
        return None

def build_references_section(global_refs: List[Dict[str, Any]], paper_by_slug: Dict[str, Any]) -> str:
    lines = ["## 📚 References\n"]
    for ref in global_refs:
        g_idx = ref["global_index"]
        slug = ref["paper_slug"]
        paper_record = paper_by_slug.get(slug, {})
        meta = paper_record.get("metadata", {})
        
        authors_raw = meta.get("authors", [])
        authors_str = format_authors(authors_raw) if authors_raw else ref.get("authors", "Anon.")
        raw_title = meta.get("title") or ref.get("title") or "Untitled Paper"
        clean_title = re.sub(r"\s+", " ", raw_title).strip().rstrip(".")
        
        venue = meta.get("venue")
        if not venue and isinstance(meta.get("journal"), dict):
            venue = meta.get("journal", {}).get("name")
        venue_str = f" *{venue.strip()}*" if venue and venue.strip() else ""
        year = meta.get("year") or ref.get("year") or "n.d."
        
        ext_ids = meta.get("externalIds", {}) if isinstance(meta.get("externalIds"), dict) else {}
        doi = ext_ids.get("DOI") or meta.get("doi") or ""
        doi_str = f" https://doi.org/{doi.strip()}" if doi else ""
        
        ref_line = f"[{g_idx}] {authors_str} {clean_title}.{venue_str} ({year}).{doi_str}"
        lines.append(ref_line)
        
    return "\n".join(lines)

def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    print("=" * 80)
    print("🌟 AutoSci 引言全篇大师级工作站 (Outline-Guided Master Introduction Studio)")
    print("=" * 80)
    
    api_key = get_deepseek_api_key()
    if not api_key:
        print("❌ 错误: 无法加载 DeepSeek API key，请检查 D:\\ARS\\deepseek_api_key.txt！")
        return
        
    # 0. 交互定义工作区文件夹 (支持任意自定义项目目录，默认 D:\ARS)
    print("\n📁 请设置工作区目录 (Workspace Directory)：")
    ws_input = input("👉 请输入工作区路径 [直接回车默认 D:\\ARS]: ").strip()
    if ws_input:
        workspace_dir = Path(ws_input.strip('"\''))
    else:
        workspace_dir = Path(r"D:\ARS")
    workspace_dir.mkdir(parents=True, exist_ok=True)
    print(f"  ➜ 已锁定工作区目录: {workspace_dir}")
    
    final_report_dir = workspace_dir / "Introduction_Final_Report"
    
    # 1. 载入本地知识库与大表
    all_chunks = load_local_concept_chunks()
    if not all_chunks:
        print("❌ 错误: 本地概念库为空，请先运行 Step 4！")
        return
    print(f"[*] 📚 成功载入本地 {len(all_chunks)} 个学术引言论证段落。")
    
    matched_papers = load_master_registry_papers()
    paper_by_slug = {p.get("slug"): p for p in matched_papers if p.get("slug")}
    print(f"[*] 📖 成功载入中心文献库 {len(matched_papers)} 篇文献元数据与 PDF 索引。")
    
    # 2. 交互式获取用户思路并智能规划 3~6 个学术段落
    print("\n" + "=" * 80)
    print("📝 请输入整篇引言的研究大主题与您的核心研究思路（支持自由粘贴文字/草稿/要点）:")
    print("=" * 80)
    
    topic = input("\n📌 1. 请输入论文暂定标题 / 核心研究课题 (Title / Topic):\n👉 ").strip()
    if not topic:
        topic = "Efficient Triplet Energy Transfer from Perovskite Quantum Dots to Organic BODIPY Acceptors via Conformation-Controlled Dynamics"
        print(f"   (使用默认课题: {topic})")
        
    print("\n💡 2. 请输入整篇引言的研究思路/背景草稿/实验要点 (自由输入，中英皆可):")
    print("   👉 [支持任意多行粘贴，中间可随意空行。全部输入完成后，在最后单独一行输入 EOF 并回车提交]:")
    
    thoughts_lines = []
    while True:
        try:
            line = input()
            if line.strip().upper() == "EOF":
                break
            thoughts_lines.append(line)
        except (EOFError, KeyboardInterrupt):
            break
            
    raw_thoughts = "\n".join(thoughts_lines).strip()
    if not raw_thoughts:
        print("  ℹ️ 未检测到详细输入，将启用全套量子点敏化BODIPY三重态研究逻辑。")
        raw_thoughts = (
            "半导体钙钛矿量子点（CsPbX3）因优越光学性质成为三重态敏化理想捕光天线，但强限域导致俄歇复合。"
            "BODIPY染料光稳定性好但本征ISC极低，重原子修饰有毒性且降解稳定性。"
            "构建QD-BODIPY杂化体系可突破限制，但分子构象自由度（meso单键扭曲 vs 刚性共面）与D-A驱动力对TET/FRET竞争规律仍不清楚。"
            "本文选取柔性BDP1与刚性BDP2/BDP3，结合飞秒/纳秒瞬态吸收，阐明分子构象对激发态动力学的调控机制，建立分子设计原则。"
        )
        
    print(f"\n🧠 正在呼叫 DeepSeek 根据您的研究思路，自动智能规划 3~6 个递进学术段落...")
    active_outline = decompose_user_thoughts_to_outline(topic, raw_thoughts, api_key)
    
    print(f"\n✨ 已为您自适应规划出 {len(active_outline)} 个递进学术段落大纲:")
    for b in active_outline:
        print(f"   📖 [段落 {b['para_idx']}] {b['title']}: {b['goal'][:60]}...")
        
    full_outline_text = "\n".join([f"Block {item['para_idx']} ({item['title']}): {item['goal']}" for item in active_outline])
    
    # 3. 分段精准推进
    written_paragraphs = []
    global_refs = []
    global_ref_mapping = {} # paper_slug -> global_index (1-based)
    
    for item in active_outline:
        p_idx = item["para_idx"]
        p_goal = item["goal"]
        p_title = item["title"]
        
        print("\n" + "=" * 60)
        print(f"🚀 [正在攻坚第 {p_idx}/{len(active_outline)} 段] {p_title}")
        print("=" * 60)
        print(f"  🎯 段落目标: {p_goal[:60]}...")
        
        # 1) 提炼搜索关键词
        print("  🔍 正在提炼当前段落的学术概念与中英文搜索特征词...")
        search_terms = extract_search_terms_for_paragraph(topic, p_idx, p_goal, api_key)
        
        # 2) 智能粗筛 + 精排候选文献
        print("  📚 正在从全库匹配精选 Top 8 候选支撑文献...")
        candidates = rank_and_select_candidates_for_paragraph(p_goal, search_terms, all_chunks, paper_by_slug, api_key, limit=8)
        print(f"  ➜ 锁定 {len(candidates)} 篇高相关候选文献:")
        for c_idx, c in enumerate(candidates, 1):
            print(f"     [{c_idx}] [{c['perspective']}] {c['title'][:55]}... ({c['year']})")
            
        # 3) 注入上下文与前序段落，呼叫 DeepSeek 自主择优撰写
        print(f"  ✍️ 正在呼叫 DeepSeek 结合全局大纲与前文进行深度撰写与择优引证...")
        previous_text = "\n\n".join([p["english_text"] for p in written_paragraphs])
        
        res = generate_paragraph_with_selective_citations(
            topic, full_outline_text, p_idx, p_goal, previous_text, candidates, api_key, workspace_dir
        )
        if not res:
            print(f"❌ 第 {p_idx} 段撰写失败，流程中断。")
            return
            
        raw_en_para = res.get("english_paragraph", "")
        raw_zh_para = res.get("chinese_translation", "")
        used_cand_ids = res.get("used_candidate_ids", [])
        
        # 4) 解析该段实际引用的文献，更新全局引文索引
        cand_map = {c["cand_id"]: c for c in candidates}
        actually_used_refs = []
        for cid in used_cand_ids:
            if cid in cand_map:
                actually_used_refs.append(cand_map[cid])
                
        # 容错：从正文中正则扫一遍确保无遗漏
        found_cids = re.findall(r"CAND_(\d+)", raw_en_para)
        for num_str in found_cids:
            cid = f"CAND_{num_str}"
            if cid in cand_map and cand_map[cid] not in actually_used_refs:
                actually_used_refs.append(cand_map[cid])
                
        print(f"  ✨ 第 {p_idx} 段撰写完成！自主择优录用了 {len(actually_used_refs)} 篇文献支撑。")
        for ref_item in actually_used_refs:
            p_slug = ref_item["paper_slug"]
            if p_slug not in global_ref_mapping:
                new_global_idx = len(global_refs) + 1
                global_ref_mapping[p_slug] = new_global_idx
                ref_item["global_index"] = new_global_idx
                ref_item["used_in_paragraphs"] = [p_idx]
                global_refs.append(ref_item)
            else:
                existing_item = next(r for r in global_refs if r["paper_slug"] == p_slug)
                if p_idx not in existing_item["used_in_paragraphs"]:
                    existing_item["used_in_paragraphs"].append(p_idx)
                    
        # 5) 将该段中的 [CAND_X] 替换为全局统一的连续序号 [1], [2]...
        clean_en_para = raw_en_para
        clean_zh_para = raw_zh_para
        for cand in candidates:
            cid = cand["cand_id"]
            p_slug = cand["paper_slug"]
            g_idx = global_ref_mapping.get(p_slug)
            if g_idx:
                clean_en_para = re.sub(rf"\[{cid}\]", f"[{g_idx}]", clean_en_para)
                clean_zh_para = re.sub(rf"\[{cid}\]", f"[{g_idx}]", clean_zh_para)
            else:
                clean_en_para = re.sub(rf"\[{cid}\]", "", clean_en_para)
                clean_zh_para = re.sub(rf"\[{cid}\]", "", clean_zh_para)
                
        written_paragraphs.append({
            "para_idx": p_idx,
            "title": p_title,
            "english_text": clean_en_para.strip(),
            "chinese_text": clean_zh_para.strip(),
            "used_refs": actually_used_refs
        })
        
    # 4. 全局收尾与文件交付
    print("\n" + "=" * 80)
    print(f"🎉 {len(active_outline)} 个自然段全篇撰写完成！正在统筹构建最终交付档案...")
    print("=" * 80)
    
    full_english_text = "\n\n".join([p["english_text"] for p in written_paragraphs])
    full_chinese_text = "\n\n".join([p["chinese_text"] for p in written_paragraphs])
    
    final_report_dir.mkdir(parents=True, exist_ok=True)
    source_pdfs_dir = final_report_dir / "Source_PDFs"
    if source_pdfs_dir.exists():
        try:
            shutil.rmtree(source_pdfs_dir)
        except Exception:
            pass
    source_pdfs_dir.mkdir(parents=True, exist_ok=True)
    
    # 拷贝并规范重命名所有真实引用的 PDF
    print(f"🔍 正在归档全篇引用的 {len(global_refs)} 篇顶刊原装 PDF 至 Source_PDFs/...")
    for ref in global_refs:
        p_slug = ref["paper_slug"]
        g_idx = ref["global_index"]
        paper_record = paper_by_slug.get(p_slug)
        
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
                    target_pdf_path = source_pdfs_dir / clean_pdf_name
                    try:
                        shutil.copy(str(src_pdf), str(target_pdf_path))
                        ref["final_pdf_found"] = True
                        ref["final_pdf_name"] = clean_pdf_name
                        print(f"  ➜ 🟢 [{g_idx}] ➡️ 已归档: '{clean_pdf_name}'")
                    except Exception as e:
                        print(f"  ➜ ⚠️ 拷贝 PDF 异常: {e}")
                        
    # 生成 References 引用列表
    references_section = build_references_section(global_refs, paper_by_slug)
    
    # 生成最终 Markdown 手稿
    draft_lines = [
        f"# {topic}\n",
        "## 📄 Full Academic Introduction (English - Continuous Citations)",
        f"{full_english_text}\n",
        f"{references_section}\n",
        "## 🇨🇳 中文完整学术引言 (Chinese Translation)",
        f"{full_chinese_text}\n",
        f"{references_section}\n"
    ]
    draft_file = final_report_dir / "Introduction_Final_Draft.md"
    draft_file.write_text("\n".join(draft_lines), encoding="utf-8")
    
    # 生成全局溯源核对指南
    guide_lines = [
        f"# 🔍 整篇引言 (Introduction) 全局事实溯源与文献核对指南\n",
        f"**论文课题**: {topic}\n",
        f"**叙事模式**: 大纲统领下的分段精准推进 (Outline-Guided Paragraph RAG)\n",
        f"本指南按整篇论文连续引文序号 `[1]`, `[2]`, `[3]` ... 严格建立了**全局文献溯源档案**。\n",
        f"所有引用的原装 PDF ({len(global_refs)} 篇) 已完整拷贝至 `Source_PDFs/`，双击即可查阅！\n",
        "## 📚 全局文献与 PDF 文件核对表",
        "| 全局引文 | 物理 PDF 文件 (位于 `Source_PDFs/`) | 完整标题、作者与 DOI 元数据 | 支撑的段落 | 概念/机制 |",
        "|---|---|---|---|---|"
    ]
    for ref in global_refs:
        pdf_col = f"📁 `{ref['final_pdf_name']}`" if ref["final_pdf_found"] else "❌ 未配对"
        p_slug = ref["paper_slug"]
        paper_record = paper_by_slug.get(p_slug, {})
        meta = paper_record.get("metadata", {})
        ext_ids = meta.get("externalIds", {}) if isinstance(meta.get("externalIds"), dict) else {}
        doi = ext_ids.get("DOI") or meta.get("doi") or ""
        doi_badge = f"<br>🔗 `DOI: {doi}`" if doi else ""
        
        title_col = f"**{ref['title']}**<br>*{ref['authors']} ({ref['year']})*{doi_badge}"
        paras_str = ", ".join([f"第 {p} 段" for p in ref["used_in_paragraphs"]])
        guide_lines.append(f"| **[{ref['global_index']}]** | {pdf_col} | {title_col} | `{paras_str}` | `{ref['concept_name']}` |")
        
    guide_lines.append("\n## 📝 全局顶刊真题段落精细摘录 (Verbatim Literature Excerpts):\n")
    for ref in global_refs:
        paras_str = ", ".join([f"第 {p} 段" for p in ref["used_in_paragraphs"]])
        p_slug = ref["paper_slug"]
        paper_record = paper_by_slug.get(p_slug, {})
        meta = paper_record.get("metadata", {})
        ext_ids = meta.get("externalIds", {}) if isinstance(meta.get("externalIds"), dict) else {}
        doi = ext_ids.get("DOI") or meta.get("doi") or ""
        
        guide_lines.append(f"### 📍 引文 [{ref['global_index']}]：{ref['title']}")
        guide_lines.append(f"- **元数据**: {ref['authors']} ({ref['year']})")
        if doi:
            guide_lines.append(f"- **DOI**: [{doi}](https://doi.org/{doi})")
        guide_lines.append(f"- **支撑段落**: {paras_str}")
        if ref["final_pdf_found"]:
            guide_lines.append(f"- **对应 PDF**: 请双击 `Source_PDFs/{ref['final_pdf_name']}`")
        guide_lines.append(f"- **论证流向**: {ref['logical_flow']}")
        guide_lines.append(f"- **顶刊英文原文**: > *\"{ref['original_english_text']}\"*")
        guide_lines.append("\n" + "-" * 60 + "\n")
        
    guide_file = final_report_dir / "Verification_Guide_Global.md"
    guide_file.write_text("\n".join(guide_lines), encoding="utf-8")
    
    print("\n" + "=" * 80)
    print("🎉 恭喜！整篇学术引言已全部生成完成！")
    print(f"  ➜ 最终交付目录: {final_report_dir}")
    print(f"  ➜ 1. 终极中英双语引言手稿: {final_report_dir}\\Introduction_Final_Draft.md")
    print(f"  ➜ 2. 全局连续重命名的原装 PDF 库: {final_report_dir}\\Source_PDFs\\ （[1], [2]... 双击即看）")
    print(f"  ➜ 3. 全局事实溯源与核对指南: {final_report_dir}\\Verification_Guide_Global.md")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
