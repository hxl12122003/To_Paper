# -*- coding: utf-8 -*-
"""
AutoSci Full Experimental & SI Studio (全篇实验规程与测试条件整装工作站)
===================================================================================
【整章全量一次性输入 · 每种材料/测试各拉3篇顶刊 · 零特定课题硬编码】
1. 极简全量交互：
   - 模式 1：全篇化学合成与样品制备 (Synthesis & Preparation Section)
   - 模式 2：全篇仪器表征与测试测量条件 (Instrumentation & Characterization Section)
   - 用户只需一次性粘贴完整的实验记录/技术要点草稿。
2. 实体智能拆解与多路精准检索：
   - 自动识别输入中包含的各个材料、反应步骤或测试手段；
   - 针对【每一种材料/制备步骤】分别从 wiki/papers (## Method) 精准检索 3 篇顶刊合成范式；
   - 针对【每一种表征技术/仪器】分别从 wiki/methods 精准检索 3 篇顶刊仪器型号与实测条件。
3. 一次性整章出稿：
   - 呼叫 DeepSeek 结合各材料/仪器的专属顶刊范式，一次性生成符合 JACS / Nature SI 规范的长篇实验章节；
   - 统一采用过去被动语态 (Past Passive Voice)，输出中英双语手稿与核心参数表。
4. PDF 池化与溯源核对：
   - 自动将所有涉及的各篇顶刊原装 PDF 汇聚归档至 `Exemplar_PDFs/`；
   - 生成清晰明确的分项对照指南 `Verification_Guide_Experimental.md`。
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
WIKI_METHODS_DIR = Path(r"D:\ARS\AutoSci-main\wiki\methods")
WIKI_PAPERS_DIR = Path(r"D:\ARS\AutoSci-main\wiki\papers")
LITERATURE_LIBRARY_DIR = Path(r"D:\ARS\Literature_Library")
MASTER_REGISTRY_PATH = LITERATURE_LIBRARY_DIR / "master_registry.json"
DEEPSEEK_KEY_FILE_PATH = r"D:\ARS\deepseek_api_key.txt"
OUTPUT_BASE_DIR = Path(r"D:\ARS\Experimental_Report")

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

def safe_slugify(text: str) -> str:
    clean = re.sub(r"[^\w\s-]", "", text.strip().lower())
    clean = re.sub(r"[\s_]+", "-", clean)
    return clean[:50].strip("-") if clean else "experimental-section"

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

# ==============================================================================
# 第一步：智能实体拆解 (自动识别包含哪些材料/步骤或哪些测试手段)
# ==============================================================================

def segment_raw_notes_into_items(
    raw_notes: str,
    section_type: str,
    api_key: str
) -> List[Dict[str, str]]:
    """
    呼叫 DeepSeek 快速分析用户粘贴的一整篇实验记录，
    自动切分为若干个具体的子模块（材料合成项 或 表征测试项）。
    """
    prompt = f"""You are an elite academic manuscript editor in chemistry and materials science.
A researcher has pasted their comprehensive raw experimental notes for the **{section_type}** of a scientific paper.

### RESEARCHER'S RAW EXPERIMENTAL NOTES:
\"\"\"
{raw_notes}
\"\"\"

### TASK:
Analyze the input and identify all distinct sub-items present in the text:
- If this is a **Synthesis / Sample Preparation** section: identify distinct chemical materials, precursors, synthesis steps, or hybrid assembly procedures (e.g., 'Synthesis of Precursor A', 'Preparation of Quantum Dots', 'Ligand Exchange Assembly').
- If this is an **Instrumentation / Characterization** section: identify distinct measurement techniques (e.g., 'Steady-State UV-Vis & PL Spectroscopy', 'Femtosecond Transient Absorption Spectroscopy', 'Time-Resolved Photoluminescence (TRPL)').

### OUTPUT FORMAT:
Respond with a strict JSON object (no markdown wrap, raw JSON only):
{{
  "items": [
    {{
      "item_name": "Standard English Title (e.g., Synthesis of CsPbBr3 Quantum Dots)",
      "chinese_name": "中文简短名称 (例如: CsPbBr3量子点合成)",
      "relevant_notes": "The specific portion of the user's notes and parameters describing this item"
    }}
  ]
}}
"""
    url = "https://api.deepseek.com/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a professional academic experimental taxonomy parser. Output valid JSON only."},
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
            items = res.get("items", [])
            if isinstance(items, list) and items:
                return items
    except Exception as e:
        print(f"  ⚠️ 自动拆解子项微小异常 ({e})，将整体作为一个大项处理。")
        
    return [{
        "item_name": "General Experimental Procedure",
        "chinese_name": "实验操作与测试规程",
        "relevant_notes": raw_notes
    }]

# ==============================================================================
# 第二步：多路靶向检索 (每个材料/每个仪器各自精准拉取 3 篇顶刊范式)
# ==============================================================================

def search_synthesis_exemplars_for_item(
    item_name: str,
    item_notes: str,
    paper_by_slug: Dict[str, Any],
    limit: int = 3
) -> List[Dict[str, Any]]:
    """针对单一合成材料/步骤，在 wiki/papers/ 的 ## Method 中检索 3 篇最贴合的顶刊配方"""
    if not WIKI_PAPERS_DIR.exists():
        return []
        
    query_text = f"{item_name} {item_notes}".lower()
    raw_tokens = re.findall(r"[a-zA-Z0-9\u4e00-\u9fa5]{2,}", query_text)
    STOP_WORDS = {"and", "the", "for", "with", "from", "using", "into", "after", "then", "under", "合成", "制备", "反应", "方法"}
    keywords = [w for w in raw_tokens if w not in STOP_WORDS]
    
    candidates = []
    seen_papers = set()
    
    for md_file in WIKI_PAPERS_DIR.glob("*.md"):
        p_slug = md_file.stem
        if p_slug in seen_papers:
            continue
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
            
        m_match = re.search(r"## Method\s*\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
        if not m_match:
            continue
        m_text = m_match.group(1).strip()
        if len(m_text) < 50:
            continue
            
        title_lower = p_slug.replace("-", " ")
        m_text_lower = m_text.lower()
        
        score = sum(15 for kw in keywords if kw in title_lower)
        score += sum(3 for kw in keywords if kw in m_text_lower)
        
        if score > 0:
            seen_papers.add(p_slug)
            meta = paper_by_slug.get(p_slug, {}).get("metadata", {})
            candidates.append({
                "score": score,
                "slug": p_slug,
                "title": meta.get("title") or title_lower.title(),
                "year": meta.get("year", "N/A"),
                "authors": format_authors(meta.get("authors", [])),
                "excerpt": m_text[:600]
            })
            if len(candidates) >= 20:
                break
                
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:limit]

def search_instrument_exemplars_for_item(
    item_name: str,
    item_notes: str,
    paper_by_slug: Dict[str, Any],
    limit: int = 3
) -> List[Dict[str, Any]]:
    """针对单一表征测试/仪器，在 wiki/methods/ 中检索 3 篇最贴合的顶刊仪器型号与实测条件"""
    if not WIKI_METHODS_DIR.exists():
        return []
        
    query_text = f"{item_name} {item_notes}".lower()
    raw_tokens = re.findall(r"[a-zA-Z0-9\u4e00-\u9fa5]{2,}", query_text)
    STOP_WORDS = {"and", "the", "for", "with", "spectroscopy", "spectra", "measurement", "test", "测试", "光谱", "分析"}
    keywords = [w for w in raw_tokens if w not in STOP_WORDS]
    
    candidates = []
    seen_papers = set()
    
    for md_file in WIKI_METHODS_DIR.glob("*.md"):
        file_stem = md_file.stem.lower()
        file_score = sum(15 for kw in keywords if kw in file_stem)
        
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
            
        if file_score == 0:
            content_lower = content.lower()
            file_score = sum(2 for kw in keywords if kw in content_lower)
            if file_score < 4:
                continue
                
        sections = re.split(r"###\s+\[\[(.*?)\]\]\s*中的描述与结果", content)
        for i in range(1, len(sections), 2):
            p_slug = sections[i].strip()
            if p_slug in seen_papers:
                continue
            sec_body = sections[i+1]
            
            inst_match = re.search(r"\*\*使用仪器\s*\(Instrument Model\):\*\*\s*(.*?)(\n|$)", sec_body)
            inst = inst_match.group(1).strip() if inst_match else ""
            cond_match = re.search(r"\*\*测量条件\s*\(Measurement Conditions\):\*\*\s*(.*?)(\n|$)", sec_body)
            cond = cond_match.group(1).strip() if cond_match else ""
            
            eng_split = re.split(r"\*\*文献英文原文\s*\(Original English Text\):\*\*", sec_body)
            orig_text = ""
            if len(eng_split) > 1:
                raw_block = re.split(r"\*\*中文学术提炼|\n###|\Z", eng_split[1])[0]
                orig_text = " ".join([l.strip().lstrip(">").strip() for l in raw_block.strip().split("\n") if l.strip()])
                
            snippet = f"Instrument: {inst} | Conditions: {cond} | Text: {orig_text[:400]}" if (inst or cond) else orig_text[:400]
            if len(snippet) < 30:
                continue
                
            seen_papers.add(p_slug)
            meta = paper_by_slug.get(p_slug, {}).get("metadata", {})
            
            b_score = file_score
            if inst and inst.lower() != "unspecified":
                b_score += 10
            if cond and cond.lower() != "unspecified":
                b_score += 10
            if orig_text:
                b_score += 5
                
            candidates.append({
                "score": b_score,
                "slug": p_slug,
                "title": meta.get("title") or p_slug.replace("-", " ").title(),
                "year": meta.get("year", "N/A"),
                "authors": format_authors(meta.get("authors", [])),
                "excerpt": snippet
            })
            if len(candidates) >= 15:
                break
                
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:limit]

# ==============================================================================
# 第三步：一次性生成完整 SI / Experimental 章节手稿
# ==============================================================================

def generate_complete_experimental_chapter(
    section_type: str,
    chapter_title: str,
    items_with_exemplars: List[Dict[str, Any]],
    api_key: str,
    workspace_dir: Path | None = None
) -> Dict[str, Any] | None:
    """呼叫 DeepSeek 结合所有子项及其对应的专属顶刊范文，一次性输出完整的长篇 SI 章节"""
    
    context_blocks = []
    for idx, item in enumerate(items_with_exemplars, 1):
        item_title = item["item_name"]
        raw_notes = item["relevant_notes"]
        exs = item.get("exemplars", [])
        
        ex_str = ""
        for e_idx, e in enumerate(exs, 1):
            ex_str += f"   * Benchmark [{e_idx}]: {e['title']} ({e['year']}) -> \"{e['excerpt'][:220].replace(chr(10), ' ')}...\"\n"
            
        block = f"### SUBSECTION {idx}: {item_title}\n"
        block += f"- **User Raw Records / Details**:\n\"\"\"{raw_notes}\"\"\"\n"
        block += f"- **3 Specific Literature Benchmarks for this item**:\n{ex_str if ex_str else '   *(Standard top-tier phrasing)*'}\n"
        context_blocks.append(block)
        
    all_context_str = "\n".join(context_blocks)

    # 加载用户自定义 Skill
    custom_skill = load_custom_skill(workspace_dir)
    custom_skill_block = ""
    if custom_skill:
        custom_skill_block = f"""
### 🌟 USER CUSTOM SKILL & SPECIAL WRITING INSTRUCTIONS (HIGHEST PRIORITY):
The user has provided the following specific domain skill instructions and writing guidelines. You MUST strictly adhere to them:
{custom_skill}
"""
    
    prompt = f"""You are an elite academic manuscript editor for Nature, JACS, and Advanced Materials.
Your task is to write a comprehensive, publishable, and peer-reviewed-level **{section_type}** for the Supporting Information (SI) or Experimental Section of an academic paper.

{custom_skill_block}

### CHAPTER WORKING TITLE:
"{chapter_title}"

### INPUT BREAKDOWN ACROSS ALL EXPERIMENTAL SUB-ITEMS:
{all_context_str}

### WRITING RULES:
1. **MANDATORY ANTI-PLAGIARISM & PARAPHRASING (20%+ DISSIMILARITY)**:
   - **Zero Verbatim Copying**: NEVER copy experimental descriptions verbatim from literature benchmarks.
   - **Substantial Paraphrasing**: Every sentence MUST be uniquely synthesized and rephrased to ensure **at least 20% linguistic/structural difference** from published templates while strictly preserving all chemical quantities, temperatures, and steps.
2. **One-Shot Complete Chapter Assembly**:
   - Write a cohesive, full-length academic section covering ALL subsections listed above.
   - For Synthesis: begin with a standard "Materials and Reagents" specification (listing common purities, solvents, and suppliers), followed by clear numbered subsections (e.g., "Synthesis of Compound 1", "Preparation of Quantum Dots", "Assembly Protocol").
   - For Instrumentation: organize by technique (e.g., "Steady-State Spectroscopy", "Femtosecond Transient Absorption Spectroscopy", "Single-Particle Imaging"), articulating exact laser wavelengths, repetition rates, optical paths, and detection windows.
3. **Strict Past Passive Voice**:
   - Every operational sentence MUST strictly adhere to formal chemical protocol phrasing (e.g., *"was dissolved in...", "were stirred at 120 °C under vacuum for 1 h", "the reaction was quenched with...", "spectra were acquired on a..."*).
4. **100% Faithful to User Parameters**:
   - Faithfully retain all user-specified numbers, molar ratios, temperatures, times, concentrations, and centrifuge speeds. Do NOT omit user facts or alter data.
5. **EXPLICIT PLACEHOLDER MARKING FOR UNVERIFIED METADATA (NO SILENT HALLUCINATION)**:
   - For standard SI formatting elements (e.g. chemical purity percentages like '98%', vendor/supplier names like 'Sigma-Aldrich', or instrument model numbers) that were NOT explicitly specified in the user's raw notes:
   - DO NOT silently hallucinate them as verified facts!
   - Visibly mark all suggested/inferred values with asterisks and a clear tag so readers know they are placeholders to verify or delete, for example:
     `PbBr2 [**99.999%**, **Sigma-Aldrich** (to verify)]`, or `...were purchased from [**Sigma-Aldrich or Macklin** (to verify)]...`
     (In Chinese: `溴化铅 [**99.999%**，**Sigma-Aldrich** (待核对)]`)
   - Append an explicit footnote at the end of the Materials paragraph:
     `*(Note: Items marked with [**... (to verify)**] are literature standard placeholders. Authors should confirm with actual laboratory bottle labels or delete.)*`
6. **Professional Bilingual Delivery**:
   - Provide the complete, pristine English section suitable directly for manuscript submission.
   - Provide an accurate, peer-reviewed-level Chinese translation for verification.

### OUTPUT FORMAT:
Respond with a strict JSON object (no markdown wrap, raw JSON only):
{{
  "chapter_title": "{chapter_title}",
  "english_full_text": "The complete, polished English chapter containing all formatted subsections in past passive voice...",
  "chinese_full_text": "The complete professional Chinese translation...",
  "summary_table": [
    {{"item": "Sub-item Name", "key_parameters": "Key parameters, conditions, or yields extracted from this subsection"}}
  ]
}}
"""
    url = "https://api.deepseek.com/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a professional academic experimental section writer. Output valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 8192,
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
        print(f"❌ 调用 DeepSeek 撰写整章发生错误: {e}")
        return None

# ==============================================================================
# 第四步：文件归档与核对指南生成
# ==============================================================================

def archive_full_chapter_report(
    workspace_dir: Path,
    chapter_title: str,
    draft_data: Dict[str, Any],
    all_exemplar_papers: List[Dict[str, Any]],
    items_with_exemplars: List[Dict[str, Any]],
    paper_by_slug: Dict[str, Any]
) -> Path:
    """归档完整报告、拷贝所有去重后的顶刊原装 PDF 并生成分项核对指南"""
    slug = safe_slugify(chapter_title)
    output_base_dir = workspace_dir / "Experimental_Report"
    report_dir = output_base_dir / f"{slug}_Report"
    report_dir.mkdir(parents=True, exist_ok=True)
    
    exemplar_pdfs_dir = report_dir / "Exemplar_PDFs"
    if exemplar_pdfs_dir.exists():
        try:
            shutil.rmtree(exemplar_pdfs_dir)
        except Exception:
            pass
    exemplar_pdfs_dir.mkdir(parents=True, exist_ok=True)
    
    # 拷贝所有引用的原装 PDF
    print(f"\n🔍 正在将参考的 {len(all_exemplar_papers)} 篇顶刊原装 PDF 拷贝至 Exemplar_PDFs/...")
    for idx, ex in enumerate(all_exemplar_papers, 1):
        p_slug = ex.get("slug")
        p_record = paper_by_slug.get(p_slug)
        ex["pdf_found"] = False
        ex["pdf_name"] = None
        if p_record:
            meta = p_record.get("metadata", {})
            author_names = [a.get("name", "") for a in meta.get("authors", [])]
            first_author = author_names[0].split()[-1] if author_names else "Author"
            year = meta.get("year", "Year")
            pdf_path_str = p_record.get("pdf_path")
            if pdf_path_str:
                src_pdf = Path(pdf_path_str)
                if src_pdf.exists():
                    clean_pdf_name = f"[{idx}] [{year}] {first_author}.pdf"
                    target_pdf_path = exemplar_pdfs_dir / clean_pdf_name
                    try:
                        shutil.copy(str(src_pdf), str(target_pdf_path))
                        ex["pdf_found"] = True
                        ex["pdf_name"] = clean_pdf_name
                        print(f"  ➜ 📖 [范文 {idx}] ➡️ 已归档: '{clean_pdf_name}'")
                    except Exception as e:
                        print(f"  ➜ ⚠️ 拷贝 PDF 异常: {e}")
                        
    # 写入 Draft.md
    en_text = draft_data.get("english_full_text", "")
    zh_text = draft_data.get("chinese_full_text", "")
    summary_table = draft_data.get("summary_table", [])
    
    draft_lines = [
        f"# {chapter_title}\n",
        "## 📄 Supporting Information / Experimental Section (English)",
        f"{en_text}\n",
        "## 🇨🇳 中文翻译与实验要点 (Chinese Translation)",
        f"{zh_text}\n"
    ]
    
    if summary_table:
        draft_lines.append("## 📊 实验与测试参数总览表 (Summary of Conditions & Protocols)")
        draft_lines.append("| 子项目 (Item) | 关键操作参数 / 测试条件 (Key Parameters & Conditions) |")
        draft_lines.append("|---|---|")
        for row in summary_table:
            draft_lines.append(f"| **{row.get('item')}** | `{row.get('key_parameters')}` |")
        draft_lines.append("\n")
        
    draft_path = report_dir / f"{slug}_Draft.md"
    draft_path.write_text("\n".join(draft_lines), encoding="utf-8")
    
    # 写入 Verification Guide (按子项清晰列出参考文献)
    guide_lines = [
        f"# 🔍 实验规程与测试条件分项溯源指南: {chapter_title}\n",
        f"本指南按子模块详细记录了在撰写本次实验手稿时，知识库为**每种材料/每种测试方法**精准匹配的专属顶刊范文。\n",
        f"全章共计参考 **{len(all_exemplar_papers)} 篇独立顶刊原装文献**，PDF 已完整拷贝至 `Exemplar_PDFs/` 目录！\n",
        "## 🏛️ 参考顶刊文献总览表",
        "| 序号 | 物理 PDF 文件 (位于 `Exemplar_PDFs/`) | 完整论文标题与元数据 |",
        "|---|---|---|"
    ]
    for idx, ex in enumerate(all_exemplar_papers, 1):
        pdf_col = f"📖 `{ex.get('pdf_name')}`" if ex.get("pdf_found") else "📁 知识库收录"
        guide_lines.append(f"| **[{idx}]** | {pdf_col} | **{ex['title']}**<br>*{ex['authors']} ({ex['year']})* |")
        
    guide_lines.append("\n## 📝 各子项专属顶刊范文摘录对照表:\n")
    for item in items_with_exemplars:
        guide_lines.append(f"### 📍 【子项】{item['item_name']} ({item.get('chinese_name', '')})")
        guide_lines.append(f"- **用户原始输入记录**: > *{item['relevant_notes'][:200]}...*")
        guide_lines.append("- **该项匹配的专属顶刊范式**:")
        for ex in item.get("exemplars", []):
            ex_pdf = f" (双击 `Exemplar_PDFs/{ex['pdf_name']}`)" if ex.get("pdf_name") else ""
            guide_lines.append(f"  * **{ex['title']}** ({ex['year']}){ex_pdf}:")
            snippet = ex.get("excerpt", "").replace("\n", "\n    > ")
            guide_lines.append(f"    > {snippet}")
        guide_lines.append("\n" + "-" * 60 + "\n")
        
    guide_path = report_dir / "Verification_Guide_Experimental.md"
    guide_path.write_text("\n".join(guide_lines), encoding="utf-8")
    
    return report_dir

# ==============================================================================
# CLI 主入口
# ==============================================================================

def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    print("=" * 80)
    print("🧪 AutoSci 全篇实验与测试条件整装大师 (Full Experimental & SI Studio)")
    print("=" * 80)
    
    # 1. 载入文献大表
    api_key = get_deepseek_api_key()
    if not api_key:
        print("❌ 错误: 无法加载 DeepSeek API key，请在 D:\\ARS\\deepseek_api_key.txt 中配置！")
        return
        
    print("\n📁 请设置工作区目录 (Workspace Directory)：")
    ws_input = input("👉 请输入工作区路径 [直接回车默认 D:\\ARS]: ").strip()
    if ws_input:
        workspace_dir = Path(ws_input.strip('"\''))
    else:
        workspace_dir = Path(r"D:\ARS")
    workspace_dir.mkdir(parents=True, exist_ok=True)
    print(f"  ➜ 已锁定工作区目录: {workspace_dir}")
    
    matched_papers = load_master_registry_papers()
    paper_by_slug = {p.get("slug"): p for p in matched_papers if p.get("slug")}
    print(f"[*] 📚 成功载入中心文献库 {len(matched_papers)} 篇文献元数据与 PDF 索引。")
    
    print("\n请选择您要一次性撰写的完整实验章节类型：")
    print("  [1] 🧪 全篇化学合成与样品制备 (Synthesis & Preparation Section)")
    print("      (一次性输入所有前驱体、不同分子合成、纳米晶制备与配体交换组装步骤)")
    print("  [2] 🔬 全篇仪器表征与测试条件 (Characterization & Instrumentation Section)")
    print("      (一次性输入所有稳态光谱、瞬态吸收、TRPL、单线态氧等仪器的测试条件)")
    
    choice = input("\n👉 请选择模式 [1 或 2，默认 1]: ").strip()
    if not choice:
        choice = "1"
        
    is_synthesis = (choice == "1")
    section_type = "Synthesis and Sample Preparation" if is_synthesis else "Characterization and Instrumentation"
    default_title = "Synthetic Procedures and Sample Preparation" if is_synthesis else "Characterization Techniques and Instrumentation"
    
    print(f"\n📌 请输入本实验章节的标题 [直接回车使用默认: {default_title}]:")
    title_input = input("👉 ").strip()
    chapter_title = title_input if title_input else default_title
    
    print(f"\n💡 请直接粘贴您的【整篇原始实验记录 / 所有操作步骤 / 所有测试条件】:")
    print("   👉 [支持任意多行粘贴，中间可随意空行。全部输入完成后，在最后单独一行输入 EOF 并回车提交]:")
    
    note_lines = []
    while True:
        try:
            line = input()
            if line.strip().upper() == "EOF":
                break
            note_lines.append(line)
        except (KeyboardInterrupt, EOFError):
            break
            
    raw_notes = "\n".join(note_lines).strip()
    if not raw_notes:
        print("  ⚠️ 输入为空，流程结束。")
        return
        
    # 第一步：智能切分包含的子项
    print(f"\n🧠 正在智能分析您的实验记录，自动识别包含的各个独立材料/步骤或测试手段...")
    sub_items = segment_raw_notes_into_items(raw_notes, section_type, api_key)
    print(f"  ✨ 成功识别出 {len(sub_items)} 个独立子模块:")
    for idx, item in enumerate(sub_items, 1):
        print(f"     [{idx}] {item['item_name']} ({item.get('chinese_name', '')})")
        
    # 第二步：多路靶向检索（每种材料/每种仪器各拉 3 篇）
    print(f"\n🔍 正在为每一个子模块分别在知识库中匹配检索 3 篇专属顶刊范式...")
    all_exemplar_papers = []
    seen_exemplar_slugs = set()
    
    for idx, item in enumerate(sub_items, 1):
        i_name = item["item_name"]
        i_notes = item["relevant_notes"]
        print(f"  ⏳ [{idx}/{len(sub_items)}] 正在检索: {i_name}...")
        
        if is_synthesis:
            exs = search_synthesis_exemplars_for_item(i_name, i_notes, paper_by_slug, limit=3)
        else:
            exs = search_instrument_exemplars_for_item(i_name, i_notes, paper_by_slug, limit=3)
            
        item["exemplars"] = exs
        print(f"     ➜ 命中 {len(exs)} 篇顶刊专属范文: {', '.join([e['title'][:30] + '...' for e in exs])}")
        
        for e in exs:
            if e["slug"] not in seen_exemplar_slugs:
                seen_exemplar_slugs.add(e["slug"])
                all_exemplar_papers.append(e)
                
    print(f"  📚 检索完毕！全章累计锁定 {len(all_exemplar_papers)} 篇高权威顶刊原装范式支持。")
    
    # 第三步：一次性生成完整长篇章节手稿
    print(f"\n✍️ 正在呼叫 DeepSeek 专家大脑一次性翻译并整装为出版级 {section_type} 规范手稿 (Past Passive Voice)...")
    draft_data = generate_complete_experimental_chapter(section_type, chapter_title, sub_items, api_key, workspace_dir)
    if not draft_data:
        print("❌ 错误: 生成失败。")
        return
        
    # 第四步：文件归档
    report_dir = archive_full_chapter_report(workspace_dir, chapter_title, draft_data, all_exemplar_papers, sub_items, paper_by_slug)
    
    print("\n" + "=" * 80)
    print(f"🎉 搞定！整篇【{chapter_title}】已全部规范化出稿！")
    print(f"  ➜ 交付目录: {report_dir}")
    print(f"  ➜ 1. 出版级中英文整章手稿与参数表: {report_dir.name}\\*_Draft.md")
    print(f"  ➜ 2. 汇聚归档的 {len(all_exemplar_papers)} 篇顶刊原装 PDF: {report_dir.name}\\Exemplar_PDFs\\ （双击即看）")
    print(f"  ➜ 3. 各子项专属顶刊范式核对指南: {report_dir.name}\\Verification_Guide_Experimental.md")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
