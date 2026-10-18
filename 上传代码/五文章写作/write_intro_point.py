# -*- coding: utf-8 -*-
"""
AutoSci Introduction Point Writer (Single Point Deep RAG Station)
===================================================================================
1. 单点精修模式：输入单句学术观点/逻辑分支。
2. 呼叫 DeepSeek 提取检索概念与关键词，在 1770 个概念节点中精准捞取支撑段落。
3. 自动反查大表并拷贝原装 PDF 至 `Introduction_Workspace/Point_{ID}/Source_PDFs/`。
4. 深度生成该单点的中英双语学术展开论证段落（含数值引文 [1], [2]...）。
5. 结构化保存至 `Introduction_Workspace/point_{ID}.json` 与 `point_{ID}.md`，供后续一键合并。
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
WORKSPACE_DIR = Path(r"D:\ARS\Introduction_Workspace")

def get_deepseek_api_key() -> str | None:
    api_file = Path(DEEPSEEK_KEY_FILE_PATH)
    if api_file.exists():
        try:
            return api_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return os.environ.get("DEEPSEEK_API_KEY")

def load_master_registry_papers() -> List[Dict[str, Any]]:
    if not MASTER_REGISTRY_PATH.exists():
        return []
    try:
        data = json.loads(MASTER_REGISTRY_PATH.read_text(encoding="utf-8"))
        return data.get("matched_papers", [])
    except Exception:
        return []

def load_local_concept_chunks() -> List[Dict[str, Any]]:
    """
    智能解析本地概念 markdown 文件，
    将全库所有已提取的 Introduction Chunks 段落打平载入内存。
    """
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
                
                # 稳健提取英文原文（支持跨行引用及不同换行格式）
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

def extract_search_terms_via_api(point_text: str, api_key: str) -> Dict[str, List[str]]:
    prompt = f"""You are a world-class academic taxonomist specializing in materials science, photophysics, and energy/charge transfer.
Analyze the following Chinese logical statement (a single point from an academic introduction outline).
To construct a dialectical, deeply persuasive academic argument, deconstruct the claim into TWO distinct categories of search parameters:
1. **Supporting Concepts/Keywords**: Concepts and terms that directly support, prove, or exemplify this claim.
2. **Contrasting/Bottleneck/Counterargument Concepts/Keywords**: Concepts and terms that discuss the limitations, bottlenecks, trade-offs, controversies, or alternative/competing mechanisms related to this claim (e.g., if claiming high QY, also find non-radiative trap loss/insulating ligand barrier; if claiming FRET, also find Dexter/electron transfer competition).

### USER'S LOGICAL STATEMENT:
"{point_text}"

### OUTPUT FORMAT:
You must respond with a strict JSON object with this exact schema (no Markdown wrap, no conversational filler, just raw JSON):
{{
  "supporting_concepts": [
    "standard-kebab-case-concept-1",
    "standard-kebab-case-concept-2"
  ],
  "supporting_keywords": [
    "keyword1", "keyword2", "keyword3", "keyword4"
  ],
  "contrasting_concepts": [
    "contrasting-concept-1",
    "contrasting-concept-2"
  ],
  "contrasting_keywords": [
    "contrast_kw1", "contrast_kw2", "contrast_kw3", "contrast_kw4"
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
            {"role": "system", "content": "You are a professional academic assistant. You deconstruct claims into dialectical JSON search parameters only."},
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
            return json.loads(content.strip())
    except Exception:
        return {}

def rank_and_select_chunks_for_point(point_text: str, all_chunks: List[Dict[str, Any]], api_key: str, limit: int = 6) -> List[Dict[str, Any]]:
    print(f"\n🧠 [观点深度解构] 正在呼叫 DeepSeek 解析该观点的正方支撑与反方/瓶颈对立概念...")
    terms_dict = extract_search_terms_via_api(point_text, api_key)
    
    supp_concepts = set(terms_dict.get("supporting_concepts", []))
    supp_keywords = [k.lower() for k in terms_dict.get("supporting_keywords", [])]
    
    cont_concepts = set(terms_dict.get("contrasting_concepts", []))
    cont_keywords = [k.lower() for k in terms_dict.get("contrasting_keywords", [])]
    
    print(f"   ➜ [正向支撑概念] {list(supp_concepts)}")
    print(f"   ➜ [反向/瓶颈概念] {list(cont_concepts)}")
    print(f"   ➜ [关联学术词汇] 支持: {supp_keywords} | 对比/瓶颈: {cont_keywords}")
    
    supp_scored = []
    cont_scored = []
    
    for chunk in all_chunks:
        c_slug = chunk["concept_slug"]
        c_text_lower = chunk["original_english_text"].lower()
        
        # 正向支撑打分
        s_score = 0
        if c_slug in supp_concepts:
            s_score += 15
        s_score += sum(1 for kw in supp_keywords if kw in c_text_lower) * 2
        if s_score > 0:
            supp_scored.append((s_score, chunk, "正向立论 (Supporting)"))
            
        # 反向/瓶颈打分
        c_score = 0
        if c_slug in cont_concepts:
            c_score += 15
        c_score += sum(1 for kw in cont_keywords if kw in c_text_lower) * 2
        if c_score > 0:
            cont_scored.append((c_score, chunk, "反向/瓶颈 (Contrasting/Bottleneck)"))
            
    supp_scored.sort(key=lambda x: x[0], reverse=True)
    cont_scored.sort(key=lambda x: x[0], reverse=True)
    
    selected = []
    seen_papers = set()
    
    # 策略：前 3-4 篇选高分正方支撑，后 2-3 篇选高分反向/瓶颈对立文献，构成辩证文献集
    # 1. 选 Supporting
    for _, ch, perspective in supp_scored:
        p_slug = ch["paper_slug"]
        if p_slug not in seen_papers:
            seen_papers.add(p_slug)
            ch_copy = dict(ch)
            ch_copy["perspective"] = perspective
            selected.append(ch_copy)
        if len(selected) >= 3:
            break
            
    # 2. 选 Contrasting/Bottleneck
    for _, ch, perspective in cont_scored:
        p_slug = ch["paper_slug"]
        if p_slug not in seen_papers:
            seen_papers.add(p_slug)
            ch_copy = dict(ch)
            ch_copy["perspective"] = perspective
            selected.append(ch_copy)
        if len(selected) >= limit:
            break
            
    # 3. 若不足 6 篇，从两池剩余的高分中补齐
    for _, ch, perspective in supp_scored + cont_scored:
        p_slug = ch["paper_slug"]
        if p_slug not in seen_papers:
            seen_papers.add(p_slug)
            ch_copy = dict(ch)
            ch_copy["perspective"] = perspective
            selected.append(ch_copy)
        if len(selected) >= limit:
            break
            
    print(f"   ➜ [检索完成] 成功精选 {len(selected)} 篇高水平顶刊段落（涵盖正向立论与反向辩证挑战）作为论据。")
    return selected

def generate_point_draft(point_idx: str, point_text: str, references: List[Dict[str, Any]], api_key: str) -> Dict[str, str] | None:
    print(f"\n✍️ 正在针对该论点进行深度辩证学术写作与润色 (DeepSeek Mode)...")
    
    ref_templates_str = ""
    for idx, ref in enumerate(references, 1):
        persp = ref.get("perspective", "正向立论")
        ref_templates_str += f"Template [{idx}] ({persp}):\n"
        ref_templates_str += f"  - Perspective Role: {persp}\n"
        ref_templates_str += f"  - Logical Argument Flow: {ref['logical_flow']}\n"
        ref_templates_str += f"  - Verbatim English: \"{ref['original_english_text']}\"\n\n"
        
    prompt = f"""You are an elite academic writing consultant and top-tier journal referee in physical chemistry, photophysics, and nanomaterials.
Your task is to write a highly rigorous, dialectical, persuasive, peer-reviewed-level academic section (1-2 paragraphs) in an Introduction that thoroughly articulates, supports, and dialectically evaluates the user's specific claim below.

### USER'S CORE CLAIM / ARGUMENT:
"{point_text}"

### RETRIEVED REAL-WORLD LITERATURE TEMPLATES (Covering both Supporting Foundations and Contrasting/Bottleneck/Counterargument Challenges):
{ref_templates_str}

### STRICT CITATION & WRITING RULES:
1. **MANDATORY ANTI-PLAGIARISM & PARAPHRASING (20%+ DISSIMILARITY)**:
   - **Zero Verbatim Copying**: NEVER copy sentences or phrasing verbatim from the retrieved literature templates.
   - **Substantial Paraphrasing**: Every sentence MUST be thoroughly synthesized with **at least 20% linguistic/structural difference** from the source template, while strictly citing the reference.
2. **Dialectical & Balanced Synthesis**:
   - First, establish the core affirmative premise by citing the supporting templates (e.g. `[1-3]`).
   - Second, if contrasting/bottleneck templates are provided (e.g. `[4-6]`), introduce the counterarguments, competing mechanisms, physical bottlenecks, or unresolved challenges using sophisticated transition phrases (e.g., *"Despite these notable achievements, recent investigations have revealed that...", "However, a major bottleneck arises from...", "Nevertheless, competing pathways such as..."*).
   - This dialectical structure creates an exceptionally robust motivation for the rest of the paper.
3. **Numerical Citation**: Use ONLY standard numerical citation brackets like `[1]`, `[2]`, `[1, 2]`, `[1-3]`, `[4-6]` corresponding to the provided Template index numbers.
4. **Every statement** introducing a theoretical foundation, prior art limitation, mechanism, or physical parameter MUST cite the corresponding reference number.
5. **Professional Academic English**: Write in clean, concise, high-impact journal style (Nature/JACS/ACS Nano style).

### OUTPUT FORMAT:
Respond with a strict JSON object with this exact schema (no markdown wrap, no conversational filler, just raw JSON):
{{
  "english_text": "The detailed dialectical academic English paragraph(s) with full numerical citations [1], [2]...",
  "chinese_translation": "The high-quality professional Chinese translation preserving the exact same numerical citations [1], [2]..."
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
            {"role": "system", "content": "You are a professional academic assistant. You generate structured research text and output valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.25,
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
            return json.loads(content.strip())
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
    print("🔬 AutoSci 单点引言观点精修工作站 (Introduction Single Point Station)")
    print("=" * 80)
    
    api_key = get_deepseek_api_key()
    if not api_key:
        print("❌ 错误: 无法加载 DeepSeek API key，请检查 D:\\ARS\\deepseek_api_key.txt！")
        return
        
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. 输入论点编号与论点文本
    point_id_input = input("\n🔢 请输入当前论点的顺序编号 (如 1, 2, 3，默认为 1):\n   👉 ").strip()
    point_id = point_id_input if point_id_input else "1"
    
    print(f"\n✍️ 请输入【论点 {point_id}】的核心学术观点/逻辑分支（一句话或简短论述）：")
    point_text = input("   👉 ").strip()
    if not point_text:
        print("❌ 错误: 观点不能为空！")
        return
        
    # 2. 载入概念库
    print("\n[*] 正在解析本地 1770 个学术概念库...")
    all_chunks = load_local_concept_chunks()
    if not all_chunks:
        print("❌ 错误: 概念库为空，请确保 Step 4 已成功提取！")
        return
    print(f"  ➜ 成功载入 {len(all_chunks)} 条真实引言段落素材。")
    
    # 3. 检索最相关的 6 篇文献（正方支撑 + 反方/瓶颈辩证）
    selected_chunks = rank_and_select_chunks_for_point(point_text, all_chunks, api_key, limit=6)
    if not selected_chunks:
        print("❌ 警告: 未能找到足够匹配的概念段落。")
        return
        
    # 4. 反查大表并准备拷贝 PDF
    matched_papers = load_master_registry_papers()
    paper_by_slug = {p.get("slug"): p for p in matched_papers if p.get("slug")}
    
    point_folder = WORKSPACE_DIR / f"Point_{point_id}"
    pdfs_folder = point_folder / "Source_PDFs"
    point_folder.mkdir(parents=True, exist_ok=True)
    if pdfs_folder.exists():
        try:
            shutil.rmtree(pdfs_folder)
        except Exception:
            pass
    pdfs_folder.mkdir(parents=True, exist_ok=True)
    
    ref_list = []
    print("\n🔍 正在反查大表并将支撑原装 PDF 拷贝至工作区...")
    for idx, chunk in enumerate(selected_chunks, 1):
        slug = chunk["paper_slug"]
        paper_record = paper_by_slug.get(slug)
        
        ref_item = {
            "index": idx,
            "slug": slug,
            "perspective": chunk.get("perspective", "正向立论"),
            "concept_name": chunk["concept_name"],
            "logical_flow": chunk["logical_flow"],
            "original_english_text": chunk["original_english_text"],
            "title": "Unknown Title",
            "year": "Unknown Year",
            "authors": "Unknown Authors",
            "pdf_found": False,
            "pdf_filename": None,
            "pdf_absolute_path": None
        }
        
        if paper_record:
            meta = paper_record.get("metadata", {})
            ref_item["title"] = meta.get("title", ref_item["title"])
            ref_item["year"] = meta.get("year", ref_item["year"])
            
            author_names = [a.get("name", "") for a in meta.get("authors", [])]
            if author_names:
                ref_item["authors"] = ", ".join(author_names[:3]) + (" et al." if len(author_names) > 3 else "")
                
            pdf_path_str = paper_record.get("pdf_path")
            if pdf_path_str:
                src_pdf = Path(pdf_path_str)
                if src_pdf.exists():
                    first_author = author_names[0].split()[-1] if author_names else "Author"
                    clean_pdf_name = f"[{idx}] [{ref_item['year']}] {first_author}.pdf"
                    target_pdf_path = pdfs_folder / clean_pdf_name
                    try:
                        shutil.copy(str(src_pdf), str(target_pdf_path))
                        ref_item["pdf_found"] = True
                        ref_item["pdf_filename"] = clean_pdf_name
                        ref_item["pdf_absolute_path"] = str(target_pdf_path.resolve())
                        print(f"  ➜ 🟢 [配对成功] [{idx}] ({ref_item['perspective']}) ➡️ 已拷贝: '{clean_pdf_name}'")
                    except Exception as e:
                        print(f"  ➜ ⚠️ 拷贝 PDF 失败: {e}")
                        
        ref_list.append(ref_item)
        
    # 5. 调用 DeepSeek 生成单点草稿
    draft_result = generate_point_draft(point_id, point_text, ref_list, api_key)
    if not draft_result:
        print("❌ 错误: 生成草稿失败。")
        return
        
    # 6. 保存单点数据 (JSON 供一键合并，MD 供人工阅读)
    point_data = {
        "point_id": point_id,
        "user_claim": point_text,
        "english_text": draft_result.get("english_text", ""),
        "chinese_translation": draft_result.get("chinese_translation", ""),
        "references": ref_list
    }
    
    # 写入 JSON 数据
    json_path = WORKSPACE_DIR / f"point_{point_id}.json"
    json_path.write_text(json.dumps(point_data, ensure_ascii=False, indent=2), encoding="utf-8")
    
    # 写入单点 MD 报告与核对表
    md_lines = [
        f"# 📍 论点 {point_id}：{point_text}\n",
        "## 📝 Academic Paragraph (English)",
        f"{point_data['english_text']}\n",
        "## 🇨🇳 中文学术翻译 (Chinese)",
        f"{point_data['chinese_translation']}\n",
        "## 📚 支撑文献与事实核对表 (Fact-Checking Table)",
        "| 引文编号 | 辩证立论角色 | 物理 PDF 文件 (位于 `Source_PDFs/` 目录) | 完整标题与元数据 | 概念节点 |",
        "|---|---|---|---|---|"
    ]
    for r in ref_list:
        pdf_col = f"📁 `{r['pdf_filename']}`" if r["pdf_found"] else "❌ 未找到"
        title_col = f"**{r['title']}**<br>*{r['authors']} ({r['year']})*"
        persp_col = f"**{r.get('perspective', '正向立论')}**"
        md_lines.append(f"| **[{r['index']}]** | {persp_col} | {pdf_col} | {title_col} | `{r['concept_name']}` |")
        
    md_lines.append("\n### 🔍 顶刊真题段落摘录 (Verbatim Literature Excerpts):")
    for r in ref_list:
        md_lines.append(f"\n* **文献 [{r['index']}]** [{r.get('perspective', '正向立论')}]: *{r['title']}*")
        md_lines.append(f"  * **论证流向**: {r['logical_flow']}")
        md_lines.append(f"  * **英文原文**: > *\"{r['original_english_text']}\"*")
        
    md_path = point_folder / f"Point_{point_id}_Draft.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    
    print("\n" + "=" * 80)
    print(f"🎉 恭喜！【论点 {point_id}】单点精修完成！")
    print(f"  ➜ 1. 结构化数据已缓存至: Introduction_Workspace/point_{point_id}.json")
    print(f"  ➜ 2. 单点段落与核对文档: Introduction_Workspace/Point_{point_id}/Point_{point_id}_Draft.md")
    print(f"  ➜ 3. 对应支撑原装 PDF: Introduction_Workspace/Point_{point_id}/Source_PDFs/ （双击即开）")
    print("=" * 80)
    print("💡 下一步建议：您可以继续运行此程序精修其他论点（如 Point 2, Point 3）。")
    print("   全部论点完成后，直接运行 `python D:\\ARS\\merge_introduction.py` 即可一键合并成终极完整引言！\n")

if __name__ == "__main__":
    main()
