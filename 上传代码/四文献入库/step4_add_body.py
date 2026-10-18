#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 4: Academic Literature Deep Extraction & Body Filler (DeepSeek-V3/V4 Mode)
==============================================================================
该脚本读取 Step 2 生成的对齐索引，定位 15 篇文献的本地全文（优先读 Zotero 纯文本缓存，无则解析 PDF），
智能过滤掉最后的 References 参考文献部分，然后调用 DeepSeek API (Smart Mode - deepseek-chat)，
深度逆向提取文献的 8 大核心学术要素：
1. Problem & Context (研究背景与痛点)
2. Key idea (核心创新点)
3. Method (研究方法)
4. Experiment & Results (实验与关键结果)
5. Limitations (局限性)
6. Open questions (开放问题)
7. My take (专业点评)
8. Related (关联性)

提取完成后，脚本会精准地将这些要素回写到 D:\ARS\AutoSci-main\wiki\papers\ 下对应的 Markdown 文档中，
完美保留原有的 Frontmatter 头部元数据，实现学术知识库的“肉身填充”。
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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# =====================================================================
# ⚙️ 核心配置区 (Configuration Section) - 请在此处手动修改您的输入输出路径
# =====================================================================
# 1. 文献匹配索引路径 (已升级为全新永久文献库，若不存在则降级兼容旧版)
DEFAULT_TARGET_PATH = r"D:\ARS\Literature_Library"

# 2. AutoSci Wiki 系统根目录
WIKI_ROOT = Path(r"D:\ARS\AutoSci-main\wiki")

# 3. 辅助工具目录
TOOLS_DIR = Path(r"D:\ARS\AutoSci-main\tools")

# 4. DeepSeek API Key 存储文件的绝对路径
DEEPSEEK_KEY_FILE_PATH = r"D:\ARS\deepseek_api_key.txt"

# 5. 是否覆盖已经填充过正文的 Markdown 文件 (True: 覆盖; False: 跳过已填充的，节省 API 额度)
OVERWRITE_EXISTING = False
# =====================================================================

def append_to_keywords_registry(slugs: List[str]):
    """
    智能将一批原始图谱的 slug 标识转换、合并去重追加至全局 D:\ARS\AutoSci-main\wiki\outputs\all_related_literature_terms.txt
    """
    registry_path = Path(r"D:\ARS\AutoSci-main\wiki\outputs\all_related_literature_terms.txt")
    if not slugs:
        return
        
    acronyms = {
        "fret", "bodipy", "tas", "tta", "uc", "sc", "soc", "pdt", "isc", "soct", 
        "ttet", "mhp", "mhps", "tem", "xrd", "xps", "xas", "dft", "flim", "trpl", 
        "tcspc", "nir", "ros", "aie", "sted", "storm", "palm", "sim", "sofi", "gsh"
    }

    def to_academic(slug: str) -> str:
        if "/" in slug:
            slug = slug.split("/")[-1]
        words = slug.split("-")
        res = []
        for w in words:
            w_lower = w.lower()
            if w_lower in acronyms or w_lower in ("co", "ii", "vi"):
                res.append(w.upper())
            else:
                res.append(w.capitalize())
        text = " ".join(res)
        text = text.replace("Triplet Triplet", "Triplet-Triplet").replace("Spin Orbit", "Spin-Orbit")
        text = text.replace("Two Photon", "Two-Photon").replace("Heavy Atom", "Heavy-Atom")
        text = text.replace("Steady State", "Steady-State").replace("Time Resolved", "Time-Resolved")
        text = text.replace("Single Molecule", "Single-Molecule").replace("In Vivo", "In-Vivo").replace("D A", "D-A")
        return text

    # 读取现有词汇
    existing_phrases = set()
    if registry_path.exists():
        try:
            for line in registry_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    existing_phrases.add(line)
        except Exception:
            pass

    # 添加新词汇
    added_count = 0
    for s in slugs:
        s_clean = s.strip()
        if not s_clean or s_clean.lower() in ("index", "index.md"):
            continue
        phrase = to_academic(s_clean)
        if phrase not in existing_phrases:
            existing_phrases.add(phrase)
            added_count += 1

    if added_count > 0:
        sorted_phrases = sorted(list(existing_phrases))
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(registry_path, "w", encoding="utf-8") as f:
                f.write("# =========================================================================\n")
                f.write(f"# AutoSci 15 篇精读文献原生学术词汇列表 (共 {len(sorted_phrases)} 个)\n")
                f.write("# 可直接复制并粘贴发送至 DeepSeek 进行“白嫖”发散！\n")
                f.write("# =========================================================================\n\n")
                for phrase in sorted_phrases:
                    f.write(f"{phrase}\n")
            print(f"  📝 [词库增量同步] 顺手成功追加了 {added_count} 个全新的原生学术词汇至词库中！")
        except Exception as e:
            print(f"  ⚠️ [词库增量同步失败]: {e}")


def get_slug(title: str) -> str:
    """
    100% 照搬并硬编码 Step 3 在导入成功时所使用的官方 Schema-compliant 算法。
    彻底过滤官方定义的 40 个学术/英文停止词，消除环境差异。
    """
    text = re.sub(r"[^a-z0-9\s]", " ", title.lower())
    words = text.split()
    
    # 100% 照搬 tools/research_wiki.py 官方定义的 STOP_WORDS 集合
    STOP_WORDS = {
        "a", "an", "the", "of", "for", "in", "on", "with", "via",
        "and", "to", "by", "is", "are", "from", "that", "this",
        "its", "at", "as", "or", "be", "it", "not", "but", "we",
        "can", "do", "has", "have", "was", "were", "been", "our"
    }
    
    keywords = [w for w in words if w not in STOP_WORDS and len(w) > 1]
    if not keywords:
        keywords = [w for w in words if w]  # 兜底：保留所有词
    if not keywords:
        return "untitled"
        
    return "-".join(keywords[:6])


def get_deepseek_api_key() -> str | None:
    """获取 DeepSeek API Key"""
    api_file = DEEPSEEK_KEY_FILE_PATH
    if os.path.exists(api_file):
        try:
            with open(api_file, "r", encoding="utf-8") as f:
                key = f.read().strip()
                if key:
                    return key
        except Exception:
            pass
    return os.environ.get("DEEPSEEK_API_KEY")


def extract_full_text(pdf_path: str, cache_path: str) -> str:
    """
    优先读取 Zotero 纯文本缓存，如果没有，则读取完整的 PDF 文件。
    """
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                if content.strip():
                    return content
        except Exception as e:
            print(f"  ⚠️ 读取 Zotero 缓存失败: {e}")

    if pdf_path and os.path.exists(pdf_path):
        try:
            import pypdf
        except ImportError:
            try:
                import PyPDF2 as pypdf
            except ImportError:
                print("  ⚠️ 未安装 pypdf 或 PyPDF2，无法直接解析 PDF 全文。请运行: pip install pypdf")
                return ""
        try:
            reader = pypdf.PdfReader(pdf_path)
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            return text
        except Exception as e:
            print(f"  ⚠️ 解析 PDF 全文失败: {e}")
    return ""


def filter_references(text: str) -> str:
    """
    智能检测并截断最后的 References / 参考文献部分，保留正文内容。
    """
    # 匹配常见的参考文献标题，通常在行首，或有编号
    patterns = [
        r'\n\s*(?:References|REFERENCES|Bibliography|BIBLIOGRAPHY|LITERATURE CITED|Literature Cited)\s*\n',
        r'\n\s*\d*\.?\s*(?:References|REFERENCES|Bibliography|BIBLIOGRAPHY)\s*\n',
    ]
    
    best_idx = -1
    for pattern in patterns:
        matches = list(re.finditer(pattern, text))
        if matches:
            # 参考文献一般在文章的后半部分 (推荐大于 70% 字符位置，更加安全，防止误伤正文中的提及)
            for match in reversed(matches):
                idx = match.start()
                if idx > len(text) * 0.7:
                    if best_idx == -1 or idx < best_idx:
                        best_idx = idx
                        
    if best_idx != -1:
        truncated_len = len(text) - best_idx
        print(f"  ➜ 成功检测到参考文献部分，已在字符位置 {best_idx} 处进行截断（过滤了后半部分约 {truncated_len} 字符）。")
        return text[:best_idx]
    
    # 备用：如果没找到标准标题，但有明显的文献列表特征，可以尝试截断
    return text


def is_body_already_filled(md_path: Path) -> bool:
    """
    检查 Markdown 文件的 Body 部分是否已经填充过内容（非空占位符）。
    """
    if not md_path.exists():
        return False
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # 寻找 "## Problem & Context" 的位置
        idx = content.find("## Problem & Context")
        if idx == -1:
            return False
            
        body_part = content[idx:]
        # 移除所有二级标题（## 开头的行）以及空白字符
        headers_removed = re.sub(r'##\s+.*', '', body_part)
        non_whitespace_chars = len(headers_removed.strip())
        
        # 如果非标题、非空白字符数大于 100，说明已经填充了实质性内容
        return non_whitespace_chars > 100
    except Exception:
        return False


def is_thesis_paper(title: str, meta: Dict[str, Any] | None = None) -> bool:
    """
    根据文献元数据、标题等信息，智能判断是否为学位论文/毕业论文/硕博论文等 (Thesis / Dissertation)
    绝对避开一般的“学校”、“学院”及“PHD/Ph.D.”等词汇，防止误伤正常的期刊论文。
    """
    if meta:
        # 1. 检查 Semantic Scholar 官方分类标记（100% 准确）
        pub_types = meta.get("publicationTypes")
        if pub_types:
            if any(t.lower() in ("thesis", "dissertation") for t in pub_types):
                return True
        # 2. 检查出版渠道 (venue / journal) 是否包含特有的毕业学位论文词汇（剔除 "university", "school of", "phd", "ph.d." 等高误伤词）
        venue = (meta.get("venue") or meta.get("journal") or "").lower()
        if any(kw in venue for kw in ["dissertation", "thesis"]):
            return True

    # 3. 检查标题是否包含毕业论文特有的词组（剔除独立的 "phd" 或 "ph.d." 以防误伤）
    title_lower = title.lower()
    thesis_keywords = [
        "dissertation", "thesis", "master's thesis", "masters thesis",
        "doctoral thesis", "doctoral dissertation", "学位论文", "硕士学位论文", "博士学位论文", "毕业论文"
    ]
    if any(kw in title_lower for kw in thesis_keywords):
        return True

    return False


def is_review_paper(title: str, text: str = "", meta: Dict[str, Any] | None = None) -> bool:
    """
    根据文献元数据、标题或正文自动判断是否为综述文献（Review/Overview/Perspective/Account/Pillar/Tutorial等）
    """
    # 1. 优先使用 Semantic Scholar 官方的分类标记
    if meta:
        pub_types = meta.get("publicationTypes")
        if pub_types:
            # 只要官方标记中含有 "Review"，就 100% 判定为综述
            if any(t.lower() == "review" for t in pub_types):
                return True

    # 2. 兜底方案（Fallback）：标题关键字正则扫描
    title_lower = title.lower()
    review_keywords = [
        "review", "overview", "progress", "recent advance", "perspective", 
        "pillar", "tutorial", "account", "trends", "versatile platform", 
        "sensitizers for", "spectroscopy in", "dynamics of", "survey", "advances",
        "the four pillars", "mechanistic tool"
    ]
    if any(kw in title_lower for kw in review_keywords):
        return True
        
    # 3. 兜底方案（Fallback）：正文前 3000 个字符（包含 Abstract 和 Introduction）
    if text:
        text_lower = text[:3000].lower()
        text_review_keywords = [
            "tutorial review", "critical review", "review article", "progress report",
            "this review", "in this review", "we review", "comprehensive review"
        ]
        if any(kw in text_lower for kw in text_review_keywords):
            return True
            
    return False


def extract_body_via_deepseek(text: str, title: str, ds_key: str, meta: Dict[str, Any] | None = None) -> Dict[str, str] | None:
    """
    调用 DeepSeek API (Smart Mode) 深度逆向提取文献的 8 大学术要素。
    自动识别文献类型并路由 to 最契合的 Prompt 模板（研究型论文 vs. 综述型论文）。
    """
    # 采用官方 V4 终结点
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ds_key}"
    }
    
    is_review = is_review_paper(title, text, meta)
    print(f"    ➜ [类型识别] 自动识别文献类型为: {'【综述型文献 (Review/Perspective)】' if is_review else '【研究型文献 (Research Article)】'}")

    if is_review:
        # 针对综述型文献定制的深度提取 Prompt
        prompt = f"""You are a world-class academic orchestrator, senior peer reviewer, and leading scientist specializing in physical chemistry, materials science, organic optoelectronics, and photophysical spectroscopy. Your expertise particularly covers metal halide perovskite nanocrystals (MHPs), BODIPY dyes, photosensitizers, and advanced energy/charge transfer mechanisms (such as FRET, Dexter, Triplet-Triplet Energy Transfer (TET), Singlet Fission, and Triplet-Triplet Annihilation Upconversion (TTA-UC)).

You are performing a deep-dive, high-fidelity academic extraction of the provided scientific REVIEW paper to populate a professional research Wiki (OmegaWiki).

Paper Title: {title}

### EXTRACTION OBJECTIVE & DETAILED GUIDELINES FOR REVIEW PAPERS
Analyze the provided full review paper text (excluding references) and extract its core scientific essence into the following 8 sections. Since this is a REVIEW paper, it summarizes and compares multiple works in the field rather than presenting a single new experiment. Your output must be highly professional, rigorous, objective, and written in academic Chinese (简体中文). Focus on the structural classification, mechanistic comparisons, and quantitative SOTA benchmarks compiled by the authors.

For each section, strictly follow these detailed guidelines:

1. **problem_context (领域演进与核心痛点)**:
   - Outline the historical evolution, milestones, and development stages of the reviewed field.
   - What are the major systemic bottlenecks, common pain points, and unresolved challenges across the entire field that this review focuses on?
   - Explain the fundamental physical or chemical principles behind these bottlenecks.
   - Format: 2 detailed, logically structured paragraphs.

2. **key_idea (分类框架与核心主题)**:
   - Identify the primary classification framework, taxonomy, or structural perspective introduced by the review authors to organize the field (e.g., categorizing systems by dimensionality, or mechanism like FRET vs. Dexter, or molecular design).
   - What are the main core themes, paradigms, or design rules discussed in this review?
   - Format: 1-2 detailed paragraphs.

3. **method (主流制备与合成路线综述)**:
   - Summarize and compare the primary synthetic, preparation, and fabrication methods discussed in this review (e.g., comparing hot-injection vs. room-temperature synthesis for perovskites; different synthetic strategies for heavy-atom-free BODIPY dyes).
   - Discuss the pros, cons, applicability, and limitations of each major preparation route.
   - Format: 2-3 detailed paragraphs or structured bullet points focusing on "how materials are made in this field".

4. **experiment_results (核心表征手段与性能基准对比)**:
   - Summarize the major characterization techniques and photophysical mechanisms (e.g., fs-TA, ns-TA, TRPL, singlet oxygen trapping, upconversion) reviewed and compared across different works.
   - **CRITICAL**: You MUST extract and cite the key SOTA performance benchmarks, quantitative metrics, efficiencies, and record values compiled in this review (e.g., highest energy transfer efficiency, longest triplet lifetime, highest singlet oxygen quantum yield, record upconversion efficiency).
   - 本部分**必须按该综述讨论的核心主题或对比的文献体系，逐个提取文中提及的定量性能基准**。
   - 对于每个主题/文献体系，提取：
     - **对比对象**: 对比了哪些材料或方法？
     - **关键性能数据**: 文中引用的具体数值（如最高效率、最长寿命、最大量子产率）。
     - **数据来源**: 对应的引用文献编号或作者。
   - 输出格式为结构化的要点或表格式文本，而不是连贯段落。
   - Format: 3-4 detailed paragraphs or structured bullet points, organized by characterization method or material system comparison.

5. **limitations (全行业共性局限性)**:
   - Act as a critical reviewer. What are the common, systemic bottlenecks and limitations across the entire reviewed field as pointed out by the authors (e.g., stability under continuous illumination, toxicity of lead, synthetic complexity, low upconversion yield, scaling challenges)?
   - Format: 1-2 detailed paragraphs or structured bullet points.

6. **open_questions (未来路线图与前沿展望)**:
   - What is the future roadmap, emerging trends, or critical unresolved questions highlighted by the review authors for the next generation of research?
   - Suggest concrete future directions discussed in the review (e.g., lead-free double perovskites, near-infrared absorbing BODIPY, optimizing ligand shell density).
   - Format: 1-2 detailed paragraphs or structured bullet points.

7. **my_take (专业点评与学术洞察)**:
   - Provide an expert, objective, and critical commentary on the review's comprehensiveness, depth, and structural clarity.
   - Assess whether the review provides a clear, actionable guide and a solid theoretical framework for researchers in the field.
   - Format: 1-2 detailed paragraphs.

8. **related (关联性与知识图谱构建)**:
   - Map this review to key concepts, methods, or other seminal papers in the field.
   - **CRITICAL**: Use standard double-bracket wikilink syntax `[[concept-slug]]` or `[[paper-slug]]` where appropriate to help build a highly connected knowledge graph!
   - Examples of concepts to link: `[[fret]]`, `[[triplet-triplet-energy-transfer]]`, `[[perovskite-nanocrystals]]`, `[[bodipy-dyes]]`, `[[transient-absorption-spectroscopy]]`, `[[singlet-oxygen]]`, `[[photodynamic-therapy]]`.
   - Format: 1-2 detailed paragraphs.

### OUTPUT FORMAT REQUIREMENT
Output MUST be a strict JSON object with these exact keys:
{{
  "problem_context": "...",
  "key_idea": "...",
  "method": "...",
  "experiment_results": "...",
  "limitations": "...",
  "open_questions": "...",
  "my_take": "...",
  "related": "...",
  "raw_introduction": "The EXACT, VERBATIM full Introduction paragraphs of the paper (with standard newlines '\\n' to separate paragraphs). Do NOT translate this field. If it is exceptionally long, extract the key conceptual and prior art paragraphs, and append '[Truncated...]' at the end.",
  "raw_conclusion": "The EXACT, VERBATIM full Conclusions and Outlook paragraphs of the paper. Do NOT translate this field.",
  "methods_used": [
    {{
      "name": "The standard English name of the characterization method (e.g. 'Femtosecond Transient Absorption Spectroscopy')",
      "instrument": "The specific make, model, or manufacturer of the instrument/equipment used (e.g., 'Spectra-Physics Astrella', 'Shimadzu UV-3600 Plus'). If not explicitly mentioned in the text, write 'Unspecified'.",
      "measurement_conditions": "The specific experimental/measurement conditions (e.g., 'excited at 400 nm, room temperature, toluene solution', 'excitation power 10 uJ/cm2, delay time window 0-8 ns'). Write in concise English or academic Chinese. If not mentioned in the text, write 'Unspecified'.",
      "original_english_text": "The EXACT, VERBATIM English paragraphs/sentences extracted from the paper that describe the experimental setup, results, and discussion for this specific characterization method. You MUST extract at least 1-2 complete, verbatim sentences from the paper. Do NOT summarize, paraphrase, or leave this field empty.",
      "summary_zh": "A concise summary of the findings/results of this method in Chinese (简体中文).",
      "tags": ["1-2 tags, e.g. 'spectroscopy', 'ultrafast'"]
    }},
    ...
  ],
  "mechanisms_used": [
    {{
      "name": "The standard English name of the physical/photophysical/optical mechanism (e.g. 'Triplet-Triplet Energy Transfer', 'Singlet Fission', 'Förster Resonance Energy Transfer', 'Type-II Band Alignment')",
      "energy_levels": "Any quantitative energy level parameters discussed in relation to this mechanism (e.g. 'HOMO/LUMO of BDP is -5.6/-3.4 eV, conduction band of CsPbBr3 is -3.5 eV'). If none mentioned, write 'Unspecified'.",
      "original_english_text": "The EXACT, VERBATIM English sentences describing the energy levels, alignment, pathways, or kinetics. You MUST extract at least 1-2 complete, verbatim sentences from the paper.",
      "summary_zh": "A concise summary of this mechanism/alignment as described in the paper in Chinese (简体中文).",
      "tags": ["1-2 tags, e.g. 'mechanism', 'energy-transfer'"]
    }}
  ],
  "introduction_chunks": [
    {{
      "concept_tag": "The core academic concept this chunk is arguing about (e.g. 'triplet-sensitization', 'surface-defect-passivation', 'quantum-confinement')",
      "raw_english_chunk": "A coherent logical segment of 3-4 consecutive, verbatim English sentences from the paper's Introduction that build a specific argument, highlight a bottleneck, or introduce an idea.",
      "chinese_translation": "A highly professional, peer-reviewed-level Chinese translation of the raw_english_chunk.",
      "transition_flow": "A brief breakdown of the logical flow in this chunk (e.g. 'QDs high QY -> surface defects passivated by ligands -> insulating transport tradeoff')"
    }}
  ]
}}

**CRITICAL FORMATTING RULES**:
1. Extract ALL characterization methods discussed in the paper into the 'methods_used' array without any hardcoded limit, ensuring comprehensive coverage of the experimental techniques.
2. The JSON values (except "methods_used", "mechanisms_used", "introduction_chunks" array structures, and "original_english_text"/"raw_english_chunk"/"raw_introduction"/"raw_conclusion") must be written in professional academic Chinese (简体中文).
3. All verbatim English texts ("original_english_text", "raw_english_chunk", "raw_introduction", "raw_conclusion") MUST be the exact, verbatim English text extracted from the paper. Do NOT summarize or translate these specific fields.
4. Do NOT include any Markdown formatting (like bold `**`, headers `###`, or lists) inside the JSON string values. Use plain text with standard newlines (`\\n`) for paragraphs.
5. Ensure all double quotes inside the text are properly escaped as `\\"` to prevent JSON parsing errors.
6. Output ONLY the raw JSON object. Do not wrap it in ```json ... ``` blocks or include any conversational filler.

Paper Text:
{text}
"""
    else:
        # 针对普通研究型论文的深度提取 Prompt
        prompt = f"""You are a world-class academic orchestrator, senior peer reviewer, and leading scientist specializing in physical chemistry, materials science, organic optoelectronics, and photophysical spectroscopy. Your expertise particularly covers metal halide perovskite nanocrystals (MHPs), BODIPY dyes, photosensitizers, and advanced energy/charge transfer mechanisms (such as FRET, Dexter, Triplet-Triplet Energy Transfer (TET), Singlet Fission, and Triplet-Triplet Annihilation Upconversion (TTA-UC)).

You are performing a deep-dive, high-fidelity academic extraction of the provided scientific paper to populate a professional research Wiki (OmegaWiki).

Paper Title: {title}

### EXTRACTION OBJECTIVE & DETAILED GUIDELINES FOR RESEARCH PAPERS
Analyze the provided full paper text (excluding references) and extract its core scientific essence into the following 8 sections. Your output must be highly professional, rigorous, objective, and written in academic Chinese (简体中文). Avoid generic summaries; instead, focus on concrete chemical structures, physical mechanisms, and quantitative spectroscopic data.

For each section, strictly follow these detailed guidelines:

1. **problem_context (研究背景与痛点)**:
   - Identify the specific scientific bottleneck, challenge, or knowledge gap this paper attacks.
   - Explain the prior state-of-the-art (SOTA) and why it was insufficient or limited (e.g., in perovskites: poor stability, lead toxicity, weak quantum confinement control; in BODIPY: low triplet yield, heavy-atom dependence, short triplet lifetime).
   - Clarify the fundamental physical or chemical principles behind this bottleneck.
   - Explain why solving this problem is critical for the field.
   - Format: 2 detailed, logically structured paragraphs.

2. **key_idea (核心创新点)**:
   - Pinpoint the exact conceptual breakthrough, core hypothesis, or unique design principle proposed by this work.
   - Explain the "aha!" moment or the molecular/structural engineering strategy (e.g., using perovskite quantum dots as spin-orbit coupling promoters or triplet sensitizers to bypass heavy-metal effects in organic dyes; designing orthogonal BODIPY dimers to induce spin-orbit charge transfer intersystem crossing (SOCT-ISC)).
   - Contrast this key idea directly with conventional approaches to highlight its novelty.
   - Format: 1-2 detailed paragraphs.

3. **method (研究方法与制备路线)**:
   - This section must focus strictly on the **synthetic preparation, fabrication, and chemical assembly routes** (制备与合成方法).
   - Detail the concrete chemical synthesis steps (e.g., hot-injection synthesis of perovskite nanocrystals, organic synthesis of specific BODIPY derivatives, ligand exchange protocols, self-assembly, or thin-film deposition).
   - Specify the key materials, precursors (e.g., lead halides, cesium carbonate, BODIPY precursors), solvent systems (e.g., octadecene, toluene), ligands (e.g., oleic acid, oleylamine), and reaction temperatures.
   - Format: 2-3 detailed paragraphs or structured bullet points focusing on "how it was made".

4. **experiment_results (逐图表结构化提取)**:
   - 本部分**必须按图表顺序（Figure 1, Figure 2, ... Table 1, Table 2, ...）逐个提取实验结果**，而不是总结成段落。
   - 对论文中出现的**每一个图表**，分别提取以下三个要素：
     - **图号与目的**: 该图/表要证明什么？解决什么问题？
     - **关键数据**: 从该图中提取的定量结果（如效率%、寿命、吸收/发射峰位、速率常数等）。如果该图包含多个子图（a, b, c, d），请分别列出每个子图的关键数据。
     - **结论**: 该图/表支持什么机制或结论？
   - 请按以下结构化格式输出（每个图表独立成块）：
     ---
     **Figure 1**: [图1目的]
     - 数据: [关键定量数据]
     - 结论: [该图结论]
     
     **Figure 2**: [图2目的]
     - 数据: [关键定量数据]
     - 结论: [该图结论]
     
     ...（以此类推，涵盖所有图表）
     ---
   - 如果图表数量较多（超过8个），优先提取与光物理机制、性能数据直接相关的主要图表（如光谱数据、效率对比、寿命数据），合成与形貌表征图表可简要概括或合并描述。
   - Format: 3-4 detailed paragraphs or structured bullet points, organized by characterization method.

5. **limitations (局限性)**:
   - Be a critical, objective reviewer. Identify the boundary conditions, weaknesses, or unresolved bottlenecks of this work.
   - Discuss issues such as: stability under continuous illumination, toxicity (e.g., lead content), synthetic complexity, purification difficulties, narrow absorption ranges, or scaling challenges.
   - Evaluate whether any assumptions made by the authors are overly optimistic or fail in practical applications.
   - Format: 1-2 detailed paragraphs or structured bullet points.

6. **open_questions (开放问题与未来方向)**:
   - What are the unresolved scientific questions or remaining challenges left by this paper?
   - Suggest concrete future research directions (e.g., replacing lead with lead-free double perovskites, developing near-infrared (NIR) absorbing BODIPY, optimizing ligand shell density to improve transfer rates).
   - Format: 1-2 detailed paragraphs or structured bullet points.

7. **my_take (专业点评与学术洞察)**:
   - Provide an expert, objective, and critical commentary on the paper's overall contribution and scientific rigor.
   - Assess whether the conclusions are fully justified by the transient spectroscopy or experimental evidence.
   - Evaluate the potential long-term impact of this work on the fields of solar energy harvesting, biosensing, or photodynamic therapy.
   - Format: 1-2 detailed paragraphs.

8. **related (关联性与知识图谱构建)**:
   - Map this paper to key concepts, methods, or other papers in the field.
   - **CRITICAL**: Use standard double-bracket wikilink syntax `[[concept-slug]]` or `[[paper-slug]]` where appropriate to help build a highly connected knowledge graph!
   - Examples of concepts to link: `[[fret]]`, `[[triplet-triplet-energy-transfer]]`, `[[perovskite-nanocrystals]]`, `[[bodipy-dyes]]`, `[[transient-absorption-spectroscopy]]`, `[[singlet-oxygen]]`, `[[photodynamic-therapy]]`.
   - Format: 1-2 detailed paragraphs.

### OUTPUT FORMAT REQUIREMENT
Output MUST be a strict JSON object with these exact keys:
{{
  "problem_context": "...",
  "key_idea": "...",
  "method": "...",
  "experiment_results": "...",
  "limitations": "...",
  "open_questions": "...",
  "my_take": "...",
  "related": "...",
  "raw_introduction": "The EXACT, VERBATIM full Introduction paragraphs of the paper (with standard newlines '\\n' to separate paragraphs). Do NOT translate this field. If it is exceptionally long, extract the key conceptual and prior art paragraphs, and append '[Truncated...]' at the end.",
  "raw_conclusion": "The EXACT, VERBATIM full Conclusions and Outlook paragraphs of the paper. Do NOT translate this field.",
  "methods_used": [
    {{
      "name": "The standard English name of the characterization method (e.g. 'Femtosecond Transient Absorption Spectroscopy')",
      "instrument": "The specific make, model, or manufacturer of the instrument/equipment used (e.g., 'Spectra-Physics Astrella', 'Shimadzu UV-3600 Plus'). If not explicitly mentioned in the text, write 'Unspecified'.",
      "measurement_conditions": "The specific experimental/measurement conditions (e.g., 'excited at 400 nm, room temperature, toluene solution', 'excitation power 10 uJ/cm2, delay time window 0-8 ns'). Write in concise English or academic Chinese. If not mentioned in the text, write 'Unspecified'.",
      "original_english_text": "The EXACT, VERBATIM English paragraphs/sentences extracted from the paper that describe the experimental setup, results, and discussion for this specific characterization method. You MUST extract at least 1-2 complete, verbatim sentences from the paper. Do NOT summarize, paraphrase, or leave this field empty.",
      "summary_zh": "A concise summary of the findings/results of this method in Chinese (简体中文).",
      "tags": ["1-2 tags, e.g. 'spectroscopy', 'ultrafast'"]
    }},
    ...
  ],
  "mechanisms_used": [
    {{
      "name": "The standard English name of the physical/photophysical/optical mechanism (e.g. 'Triplet-Triplet Energy Transfer', 'Singlet Fission', 'Förster Resonance Energy Transfer', 'Type-II Band Alignment')",
      "energy_levels": "Any quantitative energy level parameters discussed in relation to this mechanism (e.g. 'HOMO/LUMO of BDP is -5.6/-3.4 eV, conduction band of CsPbBr3 is -3.5 eV'). If none mentioned, write 'Unspecified'.",
      "original_english_text": "The EXACT, VERBATIM English sentences describing the energy levels, alignment, pathways, or kinetics. You MUST extract at least 1-2 complete, verbatim sentences from the paper.",
      "summary_zh": "A concise summary of this mechanism/alignment as described in the paper in Chinese (简体中文).",
      "tags": ["1-2 tags, e.g. 'mechanism', 'energy-transfer'"]
    }}
  ],
  "introduction_chunks": [
    {{
      "concept_tag": "The core academic concept this chunk is arguing about (e.g. 'triplet-sensitization', 'surface-defect-passivation', 'quantum-confinement')",
      "raw_english_chunk": "A coherent logical segment of 3-4 consecutive, verbatim English sentences from the paper's Introduction that build a specific argument, highlight a bottleneck, or introduce an idea.",
      "chinese_translation": "A highly professional, peer-reviewed-level Chinese translation of the raw_english_chunk.",
      "transition_flow": "A brief breakdown of the logical flow in this chunk (e.g. 'QDs high QY -> surface defects passivated by ligands -> insulating transport tradeoff')"
    }}
  ]
}}

**CRITICAL FORMATTING RULES**:
1. Extract ALL characterization methods discussed in the paper into the 'methods_used' array without any hardcoded limit, ensuring comprehensive coverage of the experimental techniques.
2. The JSON values (except "methods_used", "mechanisms_used", "introduction_chunks" array structures, and "original_english_text"/"raw_english_chunk"/"raw_introduction"/"raw_conclusion") must be written in professional academic Chinese (简体中文).
3. All verbatim English texts ("original_english_text", "raw_english_chunk", "raw_introduction", "raw_conclusion") MUST be the exact, verbatim English text extracted from the paper. Do NOT summarize or translate these specific fields.
4. Do NOT include any Markdown formatting (like bold `**`, headers `###`, or lists) inside the JSON string values. Use plain text with standard newlines (`\\n`) for paragraphs.
5. Ensure all double quotes inside the text are properly escaped as `\\"` to prevent JSON parsing errors.
6. Output ONLY the raw JSON object. Do not wrap it in ```json ... ``` blocks or include any conversational filler.

Paper Text:
{text}
"""

    data = {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": "You are a professional academic assistant. You extract structured research sections from paper text and output valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"}
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
            content = resp_data["choices"][0]["message"]["content"].strip()
            
            # 1. 清理可能存在的 markdown code block 标记
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            
            # 2. 智能自愈与抢救层 (Rescue & Repair Layer)
            sections = None
            try:
                # 方案 A：优先尝试导入并使用专业的 json-repair 库进行深度自愈
                import json_repair
                sections = json_repair.loads(content.strip())
                # print("  ✨ [JSON 抢救成功] 借助 json-repair 完美自愈了学术特殊符号冲突！")
            except ImportError:
                # 方案 B：如果没有安装 json-repair，采用原生预清洗策略进行安全兜底
                try:
                    # 替换掉非有效转义的孤立反斜杠（比如 LaTeX 中的 \beta 替换为 \\beta，防止其转义后续引号导致崩溃）
                    cleaned_content = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', content.strip())
                    sections = json.loads(cleaned_content)
                except Exception as inner_e:
                    # 方案 C：如果原生清洗也失败，抛出原始错误，提示安装 json-repair
                    raise ValueError(f"{inner_e} (💡 提示: 强烈建议在终端运行 'pip install json-repair'，即可 100% 自动修复此类学术特殊字符冲突！)")

            return sections
    except Exception as e:
        print(f"  ❌ DeepSeek API 请求或解析失败: {e}")
        return None


def main():
    # 在 Windows 环境下，重新配置标准输出编码为 UTF-8 以便正确打印 Emoji 和 Unicode 字符
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    print("=" * 80)
    print("🚀 Step 4: 开始深度提取文献学术要素并填充 Wiki Body (DeepSeek Mode)")
    print("=" * 80)

    # 1. 获取 DeepSeek API Key
    ds_key = get_deepseek_api_key()
    if not ds_key:
        print("❌ 错误: 无法获取 DeepSeek API Key。请确保 D:\\ARS\\deepseek_api_key.txt 存在且包含有效的 Key。")
        sys.exit(1)
    print("✅ DeepSeek API Key 加载成功。")

    # 2. 核心路径解析 (支持直接输入文件夹路径或 json 文件路径)
    if len(sys.argv) > 1:
        input_path = Path(sys.argv[1])
    else:
        input_path = Path(DEFAULT_TARGET_PATH)

    # 加载中央大表作为对账蓝本
    central_master_path = Path(DEFAULT_TARGET_PATH) / "master_registry.json"
    central_papers = []
    if central_master_path.exists():
        try:
            with open(central_master_path, "r", encoding="utf-8") as f:
                central_papers = json.load(f).get("matched_papers", [])
        except Exception:
            pass

    matched_papers = []
    
    # 【智能物理 PDF 文件夹对账反查逻辑】
    if input_path.is_dir() and not (input_path / "master_registry.json").exists() and not (input_path / "matched_literature_index.json").exists():
        pdf_files = list(input_path.glob("*.pdf"))
        # 兼容 nested 的 Source_PDFs 目录
        if not pdf_files and (input_path / "Source_PDFs").exists():
            pdf_files = list((input_path / "Source_PDFs").glob("*.pdf"))
            
        if pdf_files and central_papers:
            print(f"🔍 检测到物理 PDF 文件夹输入，正在反查中央库为您精准对账匹配文献...")
            for pdf in pdf_files:
                # 语义比对 PDF 文件名与中央库
                best_match = None
                best_overlap = 0
                pdf_name_clean = re.sub(r"\[\d+\]", "", pdf.stem).lower() # 去掉 [1], [2] 编号前缀
                pdf_words = set(re.findall(r"\w+", pdf_name_clean)) - {"pdf", "year", "author", "and", "the", "of", "in", "with", "from", "on", "at", "by", "via", "to"}
                
                for paper in central_papers:
                    title = paper.get("metadata", {}).get("title", "")
                    title_words = set(re.findall(r"\w+", title.lower())) - {"and", "the", "of", "in", "with", "from", "on", "at", "by", "via", "to"}
                    overlap = len(pdf_words & title_words)
                    if overlap > best_overlap and overlap >= 2:
                        best_overlap = overlap
                        best_match = paper
                
                if best_match:
                    # 拷贝一条记录，并将 pdf_path 动态重置为当前输入的物理 PDF 绝对路径
                    paper_copy = json.loads(json.dumps(best_match))
                    paper_copy["pdf_path"] = str(pdf.resolve())
                    # 同时检查 cache_path 的有效性，如果原 cache 在其他地方，允许回退到 pdf 物理提取
                    matched_papers.append(paper_copy)
                    print(f"  ➜ 🟢 [对账成功] 本地 PDF: '{pdf.name}'\n       ➡️ 中央库文献: '{paper_copy['metadata'].get('title')[:60]}...'")

    # 如果没有走物理 PDF 反查，退回标准的索引文件读取逻辑
    if not matched_papers:
        if input_path.is_dir():
            # 优先读取全新物理文献库总对账表 master_registry.json，不存在则退回旧版文件名
            master_path = input_path / "master_registry.json"
            if master_path.exists():
                index_json_path = master_path
            else:
                index_json_path = input_path / "matched_literature_index.json"
        else:
            index_json_path = input_path

        if not index_json_path.exists():
            print(f"❌ 错误: 找不到对齐索引文件: '{index_json_path}'。请确保 Step 2 运行成功。")
            sys.exit(1)

        with open(index_json_path, "r", encoding="utf-8") as f:
            index_data = json.load(f)

        matched_papers = index_data.get("matched_papers", [])

    if not matched_papers:
        print("❌ 错误: 索引文件中没有已成功对齐匹配的文献数据，或输入的目录下未匹配到任何物理 PDF 文献。")
        sys.exit(1)

    print(f"✅ 成功读取并对账文献列表，共包含 {len(matched_papers)} 篇待提取文献。")
    print(f"📂 Wiki 根目录: '{WIKI_ROOT.resolve()}'")

    # 2.5 互动式测试模式选择与覆盖策略
    print("\n" + "-" * 40)
    print("🤖 请选择运行模式 (Please select run mode):")
    print("  [1] 🚀 处理全部文献 (Run All Papers)")
    print("  [2] 🧪 运行精简测试 (Test Run - limit count)")
    print("-" * 40)
    try:
        user_choice = input("请输入选项 (1 或 2，默认为 1): ").strip()
        global OVERWRITE_EXISTING
        
        if user_choice == "2":
            try:
                limit_input = input("请输入想要运行的文献上限数量 (如 3，默认为 3): ").strip()
                limit_count = int(limit_input) if limit_input else 3
                if limit_count > 0:
                    matched_papers = matched_papers[:limit_count]
                    print(f"🍊 已开启【精简测试模式】，本次将只对前 {len(matched_papers)} 篇文献进行要素提取！")
            except ValueError:
                matched_papers = matched_papers[:3]
                print("⚠️ 输入格式不正确，默认开启【精简测试】并限制为前 3 篇文献。")
            
            # 针对测试模式，默认选择覆盖
            overwrite_choice = input("👉 是否覆盖这几篇文献已有的 Wiki 正文？(y/n，默认为 y - 强制重新提取): ").strip().lower()
            if overwrite_choice == "n":
                OVERWRITE_EXISTING = False
                print("  ℹ️ 已确认：跳过已有正文的文献。")
            else:
                OVERWRITE_EXISTING = True
                print("  ➜ 🔄 已确认：开启强制覆盖，将重新生成测试文献的 Wiki 正文！")
        else:
            print("🚀 已确认：将准备处理全部符合条件的文献！")
            # 针对全量模式，默认选择跳过
            overwrite_choice = input("👉 是否覆盖库内所有文献已有的 Wiki 正文？\n   (💡 提示：DeepSeek 拥有 Prompt Caching 深度上下文缓存，重新运行相同文献的费用极低，约享 1 折优惠)\n   (y/n，默认为 n - 跳过已填充，仅处理空白文献): ").strip().lower()
            if overwrite_choice == "y":
                OVERWRITE_EXISTING = True
                print("  ➜ 🔄 已确认：开启全库强制覆盖，将重新提取并填充所有文献正文！")
            else:
                OVERWRITE_EXISTING = False
                print("  ℹ️ 已确认：采用增量安全模式，自动跳过已有正文的文献（不消耗不必要的额度）。")
    except (KeyboardInterrupt, EOFError):
        print("\n⚠️ 用户中断或终端异常，默认安全降级为：增量处理全部文献。")
        OVERWRITE_EXISTING = False
    print("-" * 40 + "\n")

    # 3. 逐篇文献处理
    success_count = 0
    skipped_count = 0
    failed_count = 0
    
    # 记录本次成功填充的文献列表，便于用户极速定位
    newly_filled_papers = []

    for idx, item in enumerate(matched_papers, 1):
        meta = item["metadata"]
        title = meta.get("title", "Unknown Title")
        pdf_path = item.get("pdf_path", "")
        cache_path = item.get("cache_path", "")
        
        # 优先读取大表持久化记录的 slug (彻底解决任何算法、运行环境对不上导致的命名打架问题)
        slug = item.get("slug")
        if not slug:
            slug = get_slug(title)
        
        md_file_path = WIKI_ROOT / "papers" / f"{slug}.md"
        
        print(f"\n[{idx}/{len(matched_papers)}] 正在处理文献: '{title[:60]}...'")
        print(f"  ➜ 匹配的 Wiki 节点: papers/{slug}.md")

        # A. 检查 Markdown 文件是否存在
        if not md_file_path.exists():
            print(f"  ⚠️ 警告: 找不到对应的 Markdown 文件 '{md_file_path.name}'，跳过该文献。")
            failed_count += 1
            continue

        # B. 检查是否为学位论文/毕业论文，若是则自动跳过
        if is_thesis_paper(title, meta):
            print("  ℹ️ 检测到该文献为学位/毕业论文 (Thesis/Dissertation)，已自动跳过。")
            skipped_count += 1
            continue

        # C. 检查是否已经填充过正文
        # 如果是特定失败的文献，我们强制运行它
        is_target_failed_paper = (slug == "rster-resonance-energy-transfer-fret-based")
        if not OVERWRITE_EXISTING and not is_target_failed_paper and is_body_already_filled(md_file_path):
            print("  ℹ️ 检测到该文献正文已填充，跳过（OVERWRITE_EXISTING = False）。")
            skipped_count += 1
            continue

        # D. 提取全文文本
        print("  📖 正在读取文献全文文本...")
        full_text = extract_full_text(pdf_path, cache_path)
        if not full_text.strip():
            print("  ❌ 错误: 无法从 Zotero 缓存或 PDF 中提取出任何文本内容。")
            failed_count += 1
            continue
        print(f"    ➜ 成功提取全文文本 ({len(full_text)} 字符)")

        # D. 智能过滤参考文献
        filtered_text = filter_references(full_text)

        # F. 调用 DeepSeek API 提取学术要素
        print("  🧠 正在调用 DeepSeek API 进行深度学术要素逆向提取 (Smart Mode)...")
        sections = extract_body_via_deepseek(filtered_text, title, ds_key, meta)
        
        if not sections:
            print("  ❌ 错误: 无法从 DeepSeek API 获取结构化学术要素。")
            failed_count += 1
            continue

        # G. 精准回写 Markdown 文件
        print("  💾 正在将学术要素精准回写至 Markdown 节点...")
        try:
            with open(md_file_path, "r", encoding="utf-8") as f:
                md_content = f.read()

            # 提取 Frontmatter
            fm_match = re.match(r"^(---\s*\n.*?\n---)", md_content, re.DOTALL)
            if not fm_match:
                print(f"  ❌ 错误: 无法解析 Markdown 文件的 Frontmatter: '{md_file_path.name}'")
                failed_count += 1
                continue
            
            frontmatter_text = fm_match.group(1)

            # 提取表征方法列表并自动建档
            methods_used = sections.get("methods_used", [])
            method_links = []
            today_str = datetime.now().strftime("%Y-%m-%d")
            
            if methods_used:
                print(f"  🛠️ 检测到该文献使用了 {len(methods_used)} 种核心表征方法，正在自动建档与双向链接...")
                methods_dir = WIKI_ROOT / "methods"
                methods_dir.mkdir(parents=True, exist_ok=True)
                
                for m in methods_used:
                    m_name = m.get("name", "").strip()
                    m_orig = m.get("original_english_text", "").strip()
                    m_sum = m.get("summary_zh", "").strip()
                    m_tags = m.get("tags", [])
                    m_inst = m.get("instrument", "").strip()
                    m_cond = m.get("measurement_conditions", "").strip()
                    if not m_name or (not m_orig and not m_sum):
                        continue
                        
                    # 组合描述内容
                    m_desc_blocks = []
                    if m_inst and m_inst.lower() != "unspecified":
                        m_desc_blocks.append(f"**使用仪器 (Instrument Model):** {m_inst}")
                    if m_cond and m_cond.lower() != "unspecified":
                        m_desc_blocks.append(f"**测量条件 (Measurement Conditions):** {m_cond}")
                    if m_orig:
                        m_orig_escaped = m_orig.replace("\n", "\n> ")
                        m_desc_blocks.append(f"**文献英文原文 (Original English Text):**\n> {m_orig_escaped}")
                    if m_sum:
                        m_desc_blocks.append(f"**中文学术提炼 (Chinese Summary):**\n{m_sum}")
                    m_desc = "\n\n".join(m_desc_blocks)
                        
                    m_slug = get_slug(m_name)
                    method_links.append(f"[[{m_slug}]]")
                    m_file_path = methods_dir / f"{m_slug}.md"
                    
                    # 检查该方法是否已存在
                    if m_file_path.exists():
                        try:
                            with open(m_file_path, "r", encoding="utf-8") as mf:
                                m_content = mf.read()
                            
                            # 提取方法的 Frontmatter
                            mfm_match = re.match(r"^---\s*\n(.*?)\n---", m_content, re.DOTALL)
                            if mfm_match:
                                mfm_text = mfm_match.group(1)
                                # 简单解析 source_papers 列表
                                source_papers = []
                                paper_ref = f"papers/{slug}"
                                
                                # 收集现有的 source_papers
                                for line in mfm_text.split("\n"):
                                    if line.strip().startswith("-") or line.strip().startswith("  -"):
                                        p_slug = line.replace("-", "").replace("\"", "").replace("'", "").strip()
                                        if p_slug and p_slug not in source_papers:
                                            source_papers.append(p_slug)
                                            
                                if paper_ref not in source_papers:
                                    source_papers.append(paper_ref)
                                    
                                # 重构 Frontmatter
                                new_mfm_lines = ["---"]
                                for line in mfm_text.split("\n"):
                                    if "source_papers" in line:
                                        break
                                    if line.strip() and not line.strip().startswith("-") and not line.strip().startswith("  -"):
                                        new_mfm_lines.append(line)
                                new_mfm_lines.append("source_papers:")
                                for sp in source_papers:
                                    new_mfm_lines.append(f"  - \"{sp}\"")
                                new_mfm_lines.append(f"date_updated: \"{today_str}\"")
                                new_mfm_lines.append("---")
                                
                                # 追加新的文献描述到正文末尾
                                body_idx = m_content.find("---", mfm_match.end())
                                if body_idx != -1:
                                    m_body = m_content[body_idx + 3:].strip()
                                else:
                                    m_body = m_content[mfm_match.end():].strip()
                                    
                                # 检查是否已经存在该文献的描述，避免重复追加
                                paper_header = f"### [[{slug}]] 中的描述与结果"
                                if paper_header not in m_body:
                                    m_body += f"\n\n{paper_header}\n{m_desc}"
                                    
                                with open(m_file_path, "w", encoding="utf-8") as mf:
                                    mf.write("\n".join(new_mfm_lines) + "\n\n" + m_body)
                        except Exception as e:
                            print(f"    ⚠️ 更新方法文件 '{m_slug}.md' 失败: {e}")
                    else:
                        # 创建全新方法文件
                        try:
                            m_tags_str = "\n".join([f"  - \"{t}\"" for m_t in m_tags for t in (m_t if isinstance(m_t, list) else [m_t])])
                            if not m_tags_str:
                                m_tags_str = '  - "spectroscopy"'
                            new_m_content = f"""---
name: "{m_name}"
slug: "{m_slug}"
type: "protocol"
tags:
{m_tags_str}
source_papers: ["{slug}"]
date_updated: "{today_str}"
---

# {m_name}

## Overview
这是一个在钙钛矿和染料研究中常用的表征方法。

## Descriptions in Papers (文献中的具体描述与结果)

### [[{slug}]] 中的描述与结果
{m_desc}
"""
                            with open(m_file_path, "w", encoding="utf-8") as mf:
                                mf.write(new_m_content)
                        except Exception as e:
                            print(f"    ⚠️ 创建方法文件 '{m_slug}.md' 失败: {e}")

            # 提取讨论物理机制/能级参数列表并自动建档
            mechanisms_used = sections.get("mechanisms_used", [])
            mechanism_links = []
            if mechanisms_used:
                print(f"  🌌 检测到该文献讨论了 {len(mechanisms_used)} 种核心物理机制/能级结构，正在自动建档与双向链接...")
                mechanisms_dir = WIKI_ROOT / "mechanisms"
                mechanisms_dir.mkdir(parents=True, exist_ok=True)
                
                for mech in mechanisms_used:
                    mech_name = mech.get("name", "").strip()
                    mech_levels = mech.get("energy_levels", "").strip()
                    mech_orig = mech.get("original_english_text", "").strip()
                    mech_sum = mech.get("summary_zh", "").strip()
                    mech_tags = mech.get("tags", [])
                    if not mech_name or (not mech_orig and not mech_sum):
                        continue
                        
                    # 组合描述内容
                    mech_desc_blocks = []
                    if mech_levels and mech_levels.lower() != "unspecified":
                        mech_desc_blocks.append(f"**能级与定量参数 (Energy Levels):** {mech_levels}")
                    if mech_orig:
                        mech_orig_escaped = mech_orig.replace("\n", "\n> ")
                        mech_desc_blocks.append(f"**文献英文原文 (Original English Text):**\n> {mech_orig_escaped}")
                    if mech_sum:
                        mech_desc_blocks.append(f"**中文学术提炼 (Chinese Summary):**\n{mech_sum}")
                    mech_desc = "\n\n".join(mech_desc_blocks)
                        
                    mech_slug = get_slug(mech_name)
                    mechanism_links.append(f"[[{mech_slug}]]")
                    mech_file_path = mechanisms_dir / f"{mech_slug}.md"
                    
                    # 检查该机制是否已存在
                    if mech_file_path.exists():
                        try:
                            with open(mech_file_path, "r", encoding="utf-8") as mf:
                                mech_content = mf.read()
                            
                            # 提取机制的 Frontmatter
                            mfm_match = re.match(r"^---\s*\n(.*?)\n---", mech_content, re.DOTALL)
                            if mfm_match:
                                mfm_text = mfm_match.group(1)
                                source_papers = []
                                paper_ref = f"papers/{slug}"
                                
                                # 收集现有的 source_papers
                                for line in mfm_text.split("\n"):
                                    if line.strip().startswith("-") or line.strip().startswith("  -"):
                                        p_slug = line.replace("-", "").replace("\"", "").replace("'", "").strip()
                                        if p_slug and p_slug not in source_papers:
                                            source_papers.append(p_slug)
                                            
                                if paper_ref not in source_papers:
                                    source_papers.append(paper_ref)
                                    
                                # 重构 Frontmatter
                                new_mfm_lines = ["---"]
                                for line in mfm_text.split("\n"):
                                    if "source_papers" in line:
                                        break
                                    if line.strip() and not line.strip().startswith("-") and not line.strip().startswith("  -"):
                                        new_mfm_lines.append(line)
                                new_mfm_lines.append("source_papers:")
                                for sp in source_papers:
                                    new_mfm_lines.append(f"  - \"{sp}\"")
                                new_mfm_lines.append(f"date_updated: \"{today_str}\"")
                                new_mfm_lines.append("---")
                                
                                # 追加新的文献描述到正文末尾
                                body_idx = mech_content.find("---", mfm_match.end())
                                if body_idx != -1:
                                    mech_body = mech_content[body_idx + 3:].strip()
                                else:
                                    mech_body = mech_content[mfm_match.end():].strip()
                                    
                                # 检查是否已经存在该文献的描述，避免重复追加
                                paper_header = f"### [[{slug}]] 中的描述与结果"
                                if paper_header not in mech_body:
                                    mech_body += f"\n\n{paper_header}\n{mech_desc}"
                                    
                                with open(mech_file_path, "w", encoding="utf-8") as mf:
                                    mf.write("\n".join(new_mfm_lines) + "\n\n" + mech_body)
                        except Exception as e:
                            print(f"    ⚠️ 更新机制文件 '{mech_slug}.md' 失败: {e}")
                    else:
                        # 创建全新机制文件
                        try:
                            mech_tags_str = "\n".join([f"  - \"{t}\"" for m_t in mech_tags for t in (m_t if isinstance(m_t, list) else [m_t])])
                            if not mech_tags_str:
                                mech_tags_str = '  - "mechanism"'
                            new_mech_content = f"""---
name: "{mech_name}"
slug: "{mech_slug}"
type: "mechanism"
tags:
{mech_tags_str}
source_papers: ["{slug}"]
date_updated: "{today_str}"
---

# {mech_name}

## Overview
这是一个在物理化学和光动力学中讨论的核心物理机制。

## Descriptions in Papers (文献中的具体描述与结果)

### [[{slug}]] 中的描述与结果
{mech_desc}
"""
                            with open(mech_file_path, "w", encoding="utf-8") as mf:
                                mf.write(new_mech_content)
                        except Exception as e:
                            print(f"    ⚠️ 创建机制文件 '{mech_slug}.md' 失败: {e}")

            # 提取引言论证段落并增量追加至学术概念库
            introduction_chunks = sections.get("introduction_chunks", [])
            concept_links = []
            if introduction_chunks:
                print(f"  ✍️ 检测到该文献包含 {len(introduction_chunks)} 段引言逻辑段落，正在自动增量追加至学术概念库...")
                concepts_dir = WIKI_ROOT / "concepts"
                concepts_dir.mkdir(parents=True, exist_ok=True)
                
                for chunk in introduction_chunks:
                    c_tag = chunk.get("concept_tag", "").strip()
                    c_orig = chunk.get("raw_english_chunk", "").strip()
                    c_trans = chunk.get("chinese_translation", "").strip()
                    c_flow = chunk.get("transition_flow", "").strip()
                    
                    if not c_tag or not c_orig:
                        continue
                        
                    c_slug = get_slug(c_tag)
                    concept_links.append(f"[[{c_slug}]]")
                    c_file_path = concepts_dir / f"{c_slug}.md"
                    
                    c_orig_escaped = c_orig.replace("\n", "\n> ")
                    chunk_block = f"""### [[{slug}]] 中的引言段落 (Introduction Chunk)
**论证流向 (Logical Flow):** {c_flow}

**文献英文原文 (Original English Text):**
> {c_orig_escaped}

**中文翻译与学术提炼 (Chinese Translation):**
{c_trans}"""

                    if c_file_path.exists():
                        try:
                            with open(c_file_path, "r", encoding="utf-8") as cf:
                                c_content = cf.read()
                            
                            # 检查是否已经存在该文献的描述，避免重复追加
                            paper_header = f"### [[{slug}]] 中的引言段落"
                            if paper_header not in c_content:
                                new_c_content = c_content.strip() + f"\n\n{chunk_block}\n"
                                with open(c_file_path, "w", encoding="utf-8") as cf:
                                    cf.write(new_c_content)
                        except Exception as e:
                            print(f"    ⚠️ 更新概念文件 '{c_slug}.md' 追加引言段落失败: {e}")
                    else:
                        # 创建全新概念文件
                        try:
                            c_title = c_tag.replace('-', ' ').title()
                            new_c_content = f"""---
title: "{c_title}"
slug: "{c_slug}"
maturity: "stable"
importance: 5
tags: ["concept"]
key_papers:
  - "{slug}"
linked_ideas: []
---

# {c_title}

## Definition
从本地文献库中自动提取并构建的学术概念节点。

## Introduction Chunks (引言论证段落库)

{chunk_block}
"""
                            with open(c_file_path, "w", encoding="utf-8") as cf:
                                cf.write(new_c_content)
                        except Exception as e:
                            print(f"    ⚠️ 创建概念文件 '{c_slug}.md' 失败: {e}")

            # 将表征方法、物理机制和概念的超链接追加到文献的 Related 部分
            related_text = sections.get('related', '').strip()
            if method_links:
                related_text += f"\n\n- **使用到的核心表征方法**: " + ", ".join(method_links)
            if mechanism_links:
                related_text += f"\n\n- **讨论的核心物理机制**: " + ", ".join(mechanism_links)
            if concept_links:
                related_text += f"\n\n- **涉及的引言核心概念**: " + ", ".join(concept_links)

            # 组装新内容 (包含全量原文留存字段)
            new_md_content = f"""{frontmatter_text}

## Problem & Context
{sections.get('problem_context', '').strip()}

## Key idea
{sections.get('key_idea', '').strip()}

## Method
{sections.get('method', '').strip()}

## Experiment & Results
{sections.get('experiment_results', '').strip()}

## Limitations
{sections.get('limitations', '').strip()}

## Open questions
{sections.get('open_questions', '').strip()}

## My take
{sections.get('my_take', '').strip()}

## Related
{related_text}

## Raw Introduction
{sections.get('raw_introduction', '').strip()}

## Raw Conclusion
{sections.get('raw_conclusion', '').strip()}
"""
            with open(md_file_path, "w", encoding="utf-8") as f:
                f.write(new_md_content)
                
            # 顺手提取当前文献中 ## Related 的所有原始 wiki-links 概念与表征方法，并自动增量追加至中央词库
            current_slugs = []
            # 1. 提取 methods 词汇
            for m in methods_used:
                m_name = m.get("name", "").strip()
                if m_name:
                    current_slugs.append(get_slug(m_name))
            # 2. 从 related 文本中提取所有双括号
            wiki_link_pattern = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
            matches = wiki_link_pattern.findall(related_text)
            for m in matches:
                if m.strip():
                    current_slugs.append(m.strip())
                    
            if current_slugs:
                append_to_keywords_registry(current_slugs)

            print(f"  🎉 成功！文献学术要素已完美填充至 '{md_file_path.name}'。")
            success_count += 1
            newly_filled_papers.append((title, md_file_path))
            
            # 适当延迟，避免 API 速率限制
            time.sleep(1.0)
            
        except Exception as e:
            print(f"  ❌ 写入 Markdown 文件时发生异常: {e}")
            failed_count += 1

    print("\n" + "=" * 80)
    print("✨ Step 4 任务执行完毕！")
    print(f"📊 统计结果: 成功填充 {success_count} 篇 | 跳过 {skipped_count} 篇 | 失败 {failed_count} 篇")
    
    if newly_filled_papers:
        print("\n🔥 [本轮成功填充文献清单] (可以通过以下绝对路径在 Obsidian / 编辑器中快速打开):")
        for f_idx, (f_title, f_path) in enumerate(newly_filled_papers, 1):
            print(f"  👉 [{f_idx}] {f_title[:50]}...")
            print(f"       📂 绝对路径: {f_path.resolve()}")
            
    print("\n✨ 文献的深度学术要素已完美注入 OmegaWiki 系统！")
    print("=" * 80)


if __name__ == "__main__":
    main()
