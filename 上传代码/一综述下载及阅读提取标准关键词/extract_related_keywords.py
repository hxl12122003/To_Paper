#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_related_keywords.py
==========================
全景学术概念词表提取与两两/三三矩阵检索组合生成器
"""

import os
import re
import sys
import json
import itertools
import argparse
from pathlib import Path
from typing import Set, List, Dict

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

DEFAULT_WORKSPACE = Path(r"D:\ARS")
DEFAULT_WIKI_PAPERS_DIR = Path(r"D:\ARS\AutoSci-main\wiki\papers")
DEFAULT_OUTPUT_DIR = Path(r"D:\ARS\AutoSci-main\wiki\outputs")
CONCEPTS_TXT_PATH = DEFAULT_WORKSPACE / "all_review_concepts.txt"
GROUPED_KEYWORDS_TXT_PATH = DEFAULT_WORKSPACE / "分组关键词.txt"
COMBINATIONS_TXT_PATH = DEFAULT_WORKSPACE / "关键词两词加部分三词组合.txt"
DEEPSEEK_KEY_FILE = DEFAULT_WORKSPACE / "deepseek_api_key.txt"

ACRONYMS = {
    "fret", "bodipy", "tas", "tta", "uc", "sc", "soc", "pdt", "isc", "soct", 
    "ttet", "mhp", "mhps", "tem", "xrd", "xps", "xas", "dft", "flim", "trpl", 
    "tcspc", "nir", "ros", "aie", "sted", "storm", "palm", "sim", "sofi", "gsh",
    "led", "oled", "plqy", "ta", "fs", "ns", "ps"
}

def clean_slug_to_academic_english(slug: str) -> str:
    if "/" in slug:
        slug = slug.split("/")[-1]
    words = slug.split("-")
    result_words = []
    for w in words:
        w_lower = w.lower().strip()
        if not w_lower:
            continue
        if w_lower in ACRONYMS or w_lower in ("co", "ii", "vi", "iv", "iii"):
            result_words.append(w.upper())
        else:
            result_words.append(w.capitalize())
    text = " ".join(result_words)
    text = text.replace("Triplet Triplet", "Triplet-Triplet").replace("Spin Orbit", "Spin-Orbit")
    text = text.replace("Two Photon", "Two-Photon").replace("Heavy Atom", "Heavy-Atom")
    text = text.replace("Steady State", "Steady-State").replace("Time Resolved", "Time-Resolved")
    text = text.replace("Single Molecule", "Single-Molecule").replace("In Vivo", "In-Vivo").replace("D A", "D-A")
    return text

def get_deepseek_api_key() -> str:
    if DEEPSEEK_KEY_FILE.exists():
        try:
            return DEEPSEEK_KEY_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return os.environ.get("DEEPSEEK_API_KEY", "").strip()

def extract_pdf_texts(pdf_dir: Path, max_pages: int = 5) -> str:
    if not fitz or not pdf_dir.exists():
        return ""
    all_text = []
    for pdf_path in list(pdf_dir.glob("*.pdf"))[:10]:
        try:
            doc = fitz.open(str(pdf_path))
            pages_text = []
            for i in range(min(len(doc), max_pages)):
                pages_text.append(doc[i].get_text())
            doc.close()
            all_text.append(f"=== Document: {pdf_path.name} ===\n" + "\n".join(pages_text))
        except Exception as e:
            print(f"  ⚠️ 读取 PDF '{pdf_path.name}' 异常: {e}")
    return "\n\n".join(all_text)

def extract_concepts_via_llm(raw_text: str, ds_key: str) -> List[str]:
    if not ds_key or not raw_text:
        return []
    import urllib.request
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ds_key}"
    }
    prompt = f"""You are a professional literature curator and senior photophysics/materials scientist.
Analyze the provided scientific review text and extract a COMPREHENSIVE list of 100-200 specialized academic concept phrases, terminology, and keywords.
Categories to cover thoroughly:
1. Chemical materials, nano-structures, donors/acceptors, dyes, complexes
2. Photophysical mechanisms & excited-state dynamics
3. Advanced characterization and spectroscopic methods
4. Functional properties & design parameters

Output requirement:
Return ONLY a valid JSON array of strings, where each string is a standard, publication-grade academic English term/phrase. Do not wrap in markdown or add conversational text.

Text:
{raw_text[:28000]}
"""
    data = {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": "You extract structured academic terminology lists in JSON array format."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"}
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            content = res_json["choices"][0]["message"]["content"].strip()
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return parsed
            elif isinstance(parsed, dict):
                for v in parsed.values():
                    if isinstance(v, list):
                        return v
    except Exception as e:
        print(f"  ⚠️ LLM 概念词提取请求异常: {e}")
    return []

def extract_all_concepts(pdf_folder: Path = None, wiki_papers_dir: Path = None) -> List[str]:
    academic_phrases: Set[str] = set()
    wiki_dir = wiki_papers_dir or DEFAULT_WIKI_PAPERS_DIR

    if wiki_dir.exists():
        wiki_link_pattern = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
        md_files = list(wiki_dir.glob("*.md"))
        print(f"📖 正在扫描 Markdown 知识库 ({len(md_files)} 篇文献)...")
        for fpath in md_files:
            try:
                content = fpath.read_text(encoding="utf-8")
                related_idx = content.find("## Related")
                related_part = content[related_idx:] if related_idx != -1 else content
                matches = wiki_link_pattern.findall(related_part)
                for m in matches:
                    s = m.strip()
                    if s and s.lower() not in ("index", "index.md"):
                        academic_phrases.add(clean_slug_to_academic_english(s))
            except Exception:
                pass

    pdf_dir = pdf_folder
    if not pdf_dir or not pdf_dir.exists():
        for cand in [DEFAULT_WORKSPACE / "review_pdfs", DEFAULT_WORKSPACE / "pdf_download"]:
            if cand.exists() and list(cand.glob("*.pdf")):
                pdf_dir = cand
                break

    if pdf_dir and pdf_dir.exists() and list(pdf_dir.glob("*.pdf")):
        print(f"📄 正在通读综述 PDF 文件: '{pdf_dir.resolve()}' ...")
        raw_pdf_text = extract_pdf_texts(pdf_dir)
        if raw_pdf_text:
            ds_key = get_deepseek_api_key()
            if ds_key:
                print("🤖 正在调用 DeepSeek 全景提炼专业学术概念词表 (100~200+ 词组)...")
                llm_terms = extract_concepts_via_llm(raw_pdf_text, ds_key)
                for t in llm_terms:
                    if isinstance(t, str) and len(t.strip()) > 2:
                        academic_phrases.add(t.strip())

    sorted_phrases = sorted(list(academic_phrases), key=lambda x: x.lower())
    
    CONCEPTS_TXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONCEPTS_TXT_PATH, "w", encoding="utf-8") as f:
        f.write("# =========================================================================\n")
        f.write(f"# AutoSci 综述全景学术概念词表 (共提炼出 {len(sorted_phrases)} 个专业学术词组)\n")
        f.write("# 可直接复制整篇内容，发送给 DeepSeek/ChatGPT 聊天框进行结构化分组！\n")
        f.write("# =========================================================================\n\n")
        for phrase in sorted_phrases:
            f.write(f"{phrase}\n")

    try:
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (DEFAULT_OUTPUT_DIR / "all_related_literature_terms.txt").write_text(CONCEPTS_TXT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:
        pass

    print(f"\n🎉 概念词全景提取完成！共提炼出 {len(sorted_phrases)} 个概念词组。")
    print(f"👉 已保存至: '{CONCEPTS_TXT_PATH}'")
    return sorted_phrases

def parse_groups_from_text(group_text: str) -> List[List[str]]:
    try:
        if group_text.strip():
            GROUPED_KEYWORDS_TXT_PATH.write_text(group_text.strip(), encoding="utf-8")
    except Exception:
        pass

    groups = []
    lines = group_text.strip().splitlines()
    for line in lines:
        line_s = line.strip()
        if not line_s or line_s.startswith("#"):
            continue
        if ":" in line_s:
            line_s = line_s.split(":", 1)[1].strip()
        elif "：" in line_s:
            line_s = line_s.split("：", 1)[1].strip()
        kws = [k.strip() for k in re.split(r'[,;，；]', line_s) if k.strip()]
        if kws:
            groups.append(kws)
    return groups

def generate_matrix_combinations(groups: List[List[str]], output_path: Path = None) -> List[str]:
    if len(groups) < 2:
        print("⚠️ 警告: 关键词分组不足 2 组，无法生成跨组组合。")
        return []

    combinations = []
    seen = set()

    for (i, grp_a), (j, grp_b) in itertools.combinations(enumerate(groups), 2):
        for kw_a in grp_a:
            for kw_b in grp_b:
                pair = f"{kw_a}, {kw_b}"
                pair_norm = f"{min(kw_a.lower(), kw_b.lower())}::{max(kw_a.lower(), kw_b.lower())}"
                if pair_norm not in seen:
                    seen.add(pair_norm)
                    combinations.append(pair)

    if len(groups) >= 3:
        top1_kws = [grp[0] for grp in groups if grp]
        for triplet in itertools.combinations(top1_kws, 3):
            t_str = f"{triplet[0]}, {triplet[1]}, {triplet[2]}"
            t_norm = "::".join(sorted([k.lower() for k in triplet]))
            if t_norm not in seen:
                seen.add(t_norm)
                combinations.append(t_str)

    target_file = output_path or COMBINATIONS_TXT_PATH
    target_file.parent.mkdir(parents=True, exist_ok=True)
    with open(target_file, "w", encoding="utf-8") as f:
        f.write("# =========================================================================\n")
        f.write(f"# AutoSci 关键词两两组合与核心三三组合 (共 {len(combinations)} 组检索式)\n")
        f.write("# 用于 Step 1.5 批量矩阵检索与饱和度分析\n")
        f.write("# =========================================================================\n\n")
        for c in combinations:
            f.write(f"{c}\n")

    return combinations

def group_concepts_via_llm(research_desc: str, concepts: List[str], ds_key: str) -> str:
    if not ds_key or not concepts:
        return ""
    import urllib.request
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ds_key}"
    }
    sample_concepts = "\n".join(concepts[:150])
    prompt = f"""You are an expert literature search strategist.
Based on the following research topic/experimental description, select the most relevant terms from the Provided Concepts List, and organize them into 3 to 5 logical orthogonal keyword groups (e.g. Group 1: Donors/Materials, Group 2: Acceptors/Dyes, Group 3: Energy Transfer Mechanisms, Group 4: Characterization).

Each group should have 3 to 5 synonyms or related terms, listed in descending order of relevance.

Research Topic/Description:
{research_desc}

Provided Concepts List:
{sample_concepts}

Output format requirement:
Output ONLY plain text lines, with each group formatted as:
Group 1 [Category]: Term 1, Term 2, Term 3
Group 2 [Category]: Term 1, Term 2, Term 3
...
Do not include any conversational text or markdown code fences.
"""
    data = {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": "You output structured keyword groups in plain text."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 1024
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=45) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            return res_json["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  ⚠️ LLM 关键词分组异常: {e}")
        return ""

def main():
    parser = argparse.ArgumentParser(description="AutoSci Full Review Concepts Extractor & Matrix Combiner")
    parser.add_argument("folder_path", nargs="?", type=str, help="指定 PDF 或 Markdown 文件夹路径 (可选)")
    args = parser.parse_args()

    input_path = Path(args.folder_path) if args.folder_path else None
    extract_all_concepts(pdf_folder=input_path)

if __name__ == "__main__":
    main()
