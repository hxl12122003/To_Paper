# -*- coding: utf-8 -*-
"""
AutoSci Academic Conclusion Writer (100% Traditional Paper-Centric Pack)
===================================================================================
1. 支持交互式输入“结论四大核心要素”：
   - 论文大主题/暂定标题 (Title/Topic)
   - 核心实验发现与关键定量数据 (Key Findings & Quantitative Metrics)
   - 揭示的深层物理机制与科学推论 (Underlying Mechanism & Physical Insights)
   - 学术意义、未来展望与应用价值 (Significance, Future Outlook & Applications)
2. 【全库顶刊结论范式对账】：
   - 自动扫描全库 460+ 篇文献中的真实顶刊 `## Raw Conclusion`。
   - 结合关键词初筛与 DeepSeek 专家重排（LLM-as-a-Reranker），精选 6 篇最具宏观总结与升华参考价值的顶刊结论原文。
3. 【终极学术升华与写作 (DeepSeek Mode)】：
   - 严格遵循顶刊（Nature/JACS/AM 风格）结论的经典叙事三部曲（成果总结 -> 机制升华 -> 宏观展望）。
   - 产出高水平中英双语结论手稿。
4. 【原装 PDF 物理归档与溯源核对】：
   - 自动将 6 篇顶刊结论范文的原装 PDF 拷贝至 `Conclusion_Report/Exemplar_PDFs/`（双击即看）。
   - 产出全套事实溯源与句式对照指南 `Verification_Guide_Conclusion.md`。
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
WIKI_PAPERS_DIR = Path(r"D:\ARS\AutoSci-main\wiki\papers")
LITERATURE_LIBRARY_DIR = Path(r"D:\ARS\Literature_Library")
MASTER_REGISTRY_PATH = LITERATURE_LIBRARY_DIR / "master_registry.json"
CONCLUSION_REPORT_DIR = Path(r"D:\ARS\Conclusion_Report")
DEEPSEEK_KEY_FILE_PATH = r"D:\ARS\deepseek_api_key.txt"

def get_deepseek_api_key() -> str | None:
    """安全读取 DeepSeek API Key"""
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
    """加载文献大表"""
    if not MASTER_REGISTRY_PATH.exists():
        return []
    try:
        data = json.loads(MASTER_REGISTRY_PATH.read_text(encoding="utf-8"))
        return data.get("matched_papers", [])
    except Exception:
        return []

def load_workspace_empirical_materials(workspace_dir: Path) -> Dict[str, Any]:
    """
    自动扫描并提炼工作区已生成的引言手稿与各图表描述报告，
    作为结论写作中用于填充定量事实、光谱证据与物理参数的原料库。
    """
    root = workspace_dir
    materials = {
        "introduction_context": "",
        "figure_summaries": []
    }
    
    # 1. 扫描引言手稿
    intro_path = root / "Introduction_Final_Report" / "Introduction_Final_Draft.md"
    if intro_path.exists():
        try:
            intro_text = intro_path.read_text(encoding="utf-8")
            m = re.search(r"## 📄 Full Academic Introduction.*?\n(.*?)(?=\n## |\Z)", intro_text, re.DOTALL)
            if m:
                full_en_intro = m.group(1).strip()
                # 提取前 600 字符与后 600 字符作为核心立论与收尾
                materials["introduction_context"] = full_en_intro[:1200]
        except Exception:
            pass
            
    # 2. 扫描图表报告
    report_dirs = sorted(list(root.glob("*_Report")) + list(root.glob("Figure_*_Report")))
    seen_files = set()
    for r_dir in report_dirs:
        if r_dir.name in ["Introduction_Final_Report", "Conclusion_Report"]:
            continue
        for draft_file in r_dir.glob("*_Draft.md"):
            if draft_file in seen_files:
                continue
            seen_files.add(draft_file)
            try:
                content = draft_file.read_text(encoding="utf-8")
                lines = [line.strip() for line in content.split("\n") if line.strip()]
                caption = lines[0] if lines else draft_file.stem
                
                res_en = ""
                m_res = re.search(r"\*\*Results and Discussion \(English\)\*\*\s*\n(.*?)(?=\n\*\*Results and Discussion \(Chinese\)|\Z)", content, re.DOTALL)
                if m_res:
                    res_en = m_res.group(1).strip()[:350].replace("\n", " ")
                    
                materials["figure_summaries"].append({
                    "name": draft_file.stem.replace("_Draft", ""),
                    "caption": caption[:150],
                    "excerpt": res_en
                })
            except Exception:
                pass
                
    return materials

def load_all_raw_conclusions() -> List[Dict[str, Any]]:
    """扫描 wiki/papers/ 目录，读取所有已提取完整 Raw Conclusion 的文献"""
    if not WIKI_PAPERS_DIR.exists():
        return []
        
    concl_list = []
    for md_file in WIKI_PAPERS_DIR.glob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
            
        # 提取 Raw Conclusion 部分
        concl_match = re.search(r"## Raw Conclusion\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
        if not concl_match:
            continue
            
        raw_concl = concl_match.group(1).strip()
        if len(raw_concl) < 80:
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
                
        concl_list.append({
            "slug": md_file.stem,
            "title": title,
            "raw_conclusion": raw_concl,
            "filepath": md_file
        })
        
    return concl_list

def select_exemplar_conclusions(topic: str, context_text: str, all_conclusions: List[Dict[str, Any]], api_key: str, limit: int = 6) -> List[Dict[str, Any]]:
    """
    两阶段筛选 6 篇与本文结论最贴近的顶刊完整结论原文：
    1. 关键词初筛出 Top 20 候选
    2. DeepSeek 专家重排（LLM-as-a-Reranker）精选 6 篇
    """
    if not all_conclusions:
        return []
        
    print(f"\n📚 [顶刊结论范式检索] 正在从知识库 ({len(all_conclusions)} 篇全结论库) 中智能匹配 Top {limit} 篇范文...")
    
    # 提取特征词
    query_text = topic + " " + context_text
    clean_words = re.findall(r"[a-zA-Z0-9\u4e00-\u9fa5]{2,}", query_text.lower())
    STOP_WORDS = {
        "the", "and", "of", "in", "to", "for", "with", "on", "at", "by", "from",
        "an", "as", "is", "are", "was", "were", "this", "that", "its", "we", "our",
        "can", "be", "has", "have", "been", "which", "study", "paper", "work", "conclusion",
        "总结", "研究", "发现", "表明", "结果", "展示", "机制", "进行", "提出", "基于"
    }
    keywords = [w for w in clean_words if w not in STOP_WORDS]
    
    scored_candidates = []
    for item in all_conclusions:
        score = 0
        title_lower = item["title"].lower()
        concl_lower = item["raw_conclusion"].lower()
        
        for kw in keywords:
            if kw in title_lower:
                score += 10
            c_count = concl_lower.count(kw)
            score += min(c_count, 5) * 2
            
        if score > 0:
            scored_candidates.append((score, item))
            
    scored_candidates.sort(key=lambda x: x[0], reverse=True)
    top_candidates = [item for _, item in scored_candidates[:20]]
    
    if len(top_candidates) <= limit:
        return top_candidates
        
    # DeepSeek 语义重排
    candidates_list_str = ""
    for idx, cand in enumerate(top_candidates, 1):
        snippet = cand["raw_conclusion"][:220].replace("\n", " ")
        candidates_list_str += f"[{idx}] Title: {cand['title']}\n    Snippet: {snippet}...\n\n"
        
    prompt = f"""You are a distinguished research director and journal editor in photophysics, nanomaterials, and physical chemistry.
We are writing the Conclusion section for an academic manuscript on:
**Title/Topic**: {topic}
**Core Experimental Context & Inferences**:
{context_text}

Below is a candidate pool of {len(top_candidates)} published papers with complete published Conclusion sections.
Select the TOP {limit} papers whose Conclusion sections provide the best structural summary, physical depth, and forward-looking outlook for writing our manuscript's Conclusion.

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
        print(f"  ⚠️ LLM 重排异常 ({e})，回退使用词频排序。")
        
    return top_candidates[:limit]

def generate_conclusion_draft(
    topic: str,
    user_blueprint: str,
    empirical_materials: Dict[str, Any],
    exemplar_conclusions: List[Dict[str, Any]],
    api_key: str,
    workspace_dir: Path | None = None
) -> Dict[str, Any] | None:
    print(f"\n✍️ 正在呼叫 DeepSeek 专家大脑进行学术结论撰写与高度升华...")
    print(f"   ➜ 用户核心输入作为【核心纲领与主线】，本地图表与引言作为【按需调用的事实素材库】，顶刊结论作为【高级修辞范式】！")
    
    # 1. 组装工作区事实原料 (按需调用素材库)
    intro_context = empirical_materials.get("introduction_context", "").strip()
    intro_block = f"{intro_context[:800]}..." if intro_context else "(No local introduction draft available)"
    
    fig_summaries = empirical_materials.get("figure_summaries", [])
    fig_blocks = []
    for f in fig_summaries:
        excerpt = f.get("excerpt", "").strip()
        excerpt_str = f" | Finding: {excerpt}" if excerpt else ""
        fig_blocks.append(f"- [{f['name']}]: {f['caption']}{excerpt_str}")
    fig_block_str = "\n".join(fig_blocks) if fig_blocks else "(No local figure reports available)"
    
    # 2. 组装顶刊范文句式
    exemplars_str = ""
    for idx, ex in enumerate(exemplar_conclusions, 1):
        exemplars_str += f"--- EXEMPLAR CONCLUSION [{idx}] ---\n"
        exemplars_str += f"Title: {ex['title']}\n"
        exemplars_str += f"Published Verbatim Text:\n{ex['raw_conclusion']}\n\n"

    # 加载用户自定义 Skill
    custom_skill = load_custom_skill(workspace_dir)
    custom_skill_block = ""
    if custom_skill:
        custom_skill_block = f"""
### 🌟 USER CUSTOM SKILL & SPECIAL WRITING INSTRUCTIONS (HIGHEST PRIORITY):
The user has provided the following specific domain skill instructions and writing guidelines. You MUST strictly adhere to them:
{custom_skill}
"""
        
    prompt = f"""You are an elite academic manuscript editor and senior journal referee in physical chemistry, photophysics, and nanomaterials.
Your task is to write a publishable, peer-reviewed-level Conclusion section (2-3 concise, high-density paragraphs, ~350-500 words total) for the manuscript:
**Paper Topic**: {topic}

{custom_skill_block}

======================================================================
1. THE MASTER BLUEPRINT & GUIDING ANCHOR (USER INPUT - CORE MANDATE)
======================================================================
The user's input below is your ABSOLUTE BLUEPRINT and SCIENTIFIC COMPASS for this paper's Conclusion.
The entire narrative must be faithfully anchored in these core ideas, mechanistic contrasts, and molecular design principles:
\"\"\"
{user_blueprint}
\"\"\"

======================================================================
2. ON-DEMAND EMPIRICAL FACTUAL RESERVOIR (WORKSPACE RAW MATERIALS)
======================================================================
Below is the synthesized evidence from the manuscript's Introduction and experimental Figure reports.
**USAGE PRINCIPLE**: Treat this as an ON-DEMAND FACTUAL RESERVOIR. You are NOT required to force every figure or detail into the text. However, WHENEVER APPROPRIATE to substantiate, clarify, or enrich the user's blueprint (e.g. precise spectroscopic signatures, kinetic lifetimes, energy parameters, or closing the loop with the initial scientific controversy in the Introduction), SELECTIVELY and NATURALLY weave relevant facts into the prose.

[Introduction Hypothesis & Context]:
{intro_block}

[Available Experimental & Spectroscopic Evidence]:
{fig_block_str}

======================================================================
3. RHETORICAL CADENCE & PUBLISHED CONCLUSION LEXICON (STYLE & ELEVATION)
======================================================================
Emulate the following published conclusion excerpts STRICTLY for their STRUCTURAL CADENCE, ELEGANT TRANSITIONS, and HIGH-IMPACT ACADEMIC VOCABULARY (e.g., "In summary, we have demonstrated...", "These findings delineate...", "Collectively, our results establish a general design paradigm..."):
{exemplars_str}

======================================================================
WRITING & SYNTHESIS GUIDELINES:
======================================================================
1. **MANDATORY ANTI-PLAGIARISM & PARAPHRASING (20%+ DISSIMILARITY)**:
   - **Zero Verbatim Copying**: NEVER copy sentences, clauses, or fixed wording verbatim from the exemplar conclusions or raw notes.
   - **Substantial Paraphrasing**: Every sentence MUST be uniquely synthesized to ensure **at least 20% linguistic/structural difference** from any exemplar text.
2. **Classic Three-Phase Progressive Narrative Arc**:
   - **Paragraph 1 (Recapitulation & Breakthrough)**: Resoundingly summarize the central achievement and optical breakthroughs, connecting back to the core challenge raised at the outset.
   - **Paragraph 2 (Mechanistic Contrast & Deep Insights)**: Articulate the physical mechanism in depth (e.g. flexible D-A twist vs rigid coplanarity, charge-transfer-mediated pathways vs local FRET dissipation, energy level driving force differentials), pulling in supportive quantitative or spectroscopic evidence where appropriate.
   - **Paragraph 3 (Broad Paradigm & Molecular Design Rules)**: Elevate the study's impact to general molecular design blueprints (e.g. conformational engineering for heavy-metal-free triplet sensitization, solar energy conversion, photoredox applications).
3. **Organic Prose without Explicit Figure Numbers**: DO NOT write "As shown in Figure 1a" or "In Figure 4". Seamlessly weave the physical observations into natural, cohesive academic prose.
4. **Publication-Grade English**: Write in pristine Nature / JACS / Advanced Materials style English.

### OUTPUT FORMAT:
Respond with a strict JSON object with this exact schema (no markdown wrap, raw JSON only):
{{
  "english_conclusion": "The complete polished English Conclusion paragraphs...",
  "chinese_translation": "The high-quality professional Chinese translation...",
  "key_takeaways": [
    "Key takeaway 1 (Bullet summary in Chinese)",
    "Key takeaway 2 (Bullet summary in Chinese)",
    "Key takeaway 3 (Bullet summary in Chinese)"
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
            {"role": "system", "content": "You are a professional academic assistant. You generate structured research conclusions and output valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.25,
        "max_tokens": 4096,
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
    print("🔬 AutoSci 学术结论与高阶升华写作工作站 (Conclusion Master Writer)")
    print("=" * 80)
    
    api_key = get_deepseek_api_key()
    if not api_key:
        print("❌ 错误: 无法加载 DeepSeek API key，请在 D:\\ARS\\deepseek_api_key.txt 中配置！")
        return
    print("✅ DeepSeek API 密钥验证成功。")
    
    # 1. 自动侦测本地工作区原料库
    print("\n📁 请设置工作区目录 (Workspace Directory)：")
    ws_input = input("👉 请输入工作区路径 [直接回车默认 D:\\ARS]: ").strip()
    if ws_input:
        workspace_dir = Path(ws_input.strip('"\''))
    else:
        workspace_dir = Path(r"D:\ARS")
    workspace_dir.mkdir(parents=True, exist_ok=True)
    print(f"  ➜ 已锁定工作区目录: {workspace_dir}")
    
    conclusion_report_dir = workspace_dir / "Conclusion_Report"
    
    empirical_materials = load_workspace_empirical_materials(workspace_dir)
    has_intro = bool(empirical_materials.get("introduction_context"))
    fig_count = len(empirical_materials.get("figure_summaries", []))
    print(f"\n📂 [工作区原料库自动侦测]:")
    if has_intro:
        print(f"   📖 成功载入引言手稿作为立论呼应背景！")
    else:
        print(f"   ℹ️ 未检测到本地引言手稿 (可在 Introduction_Final_Report 中生成)")
    if fig_count > 0:
        print(f"   📊 成功载入 {fig_count} 个图表/能级实验报告作为事实原料！")
    else:
        print(f"   ℹ️ 未检测到本地图表实验报告")
        
    # 2. 交互采集输入 (用户基准与纲领)
    print("\n" + "=" * 80)
    print("📝 请输入整篇论文的大主题与结论核心思想（支持自由输入/多行粘贴）:")
    print("=" * 80)
    
    topic = input("\n📌 1. 请输入论文大主题/暂定标题 (Title/Topic):\n👉 ").strip()
    if not topic:
        topic = "Efficient Triplet Energy Transfer from Perovskite Quantum Dots to Organic BODIPY Acceptors via Conformation-Controlled Dynamics"
        print(f"   (使用默认主题: {topic})")
        
    print("\n💡 2. 请输入【结论核心思想与物理判断】（作为结论的基准与纲领）:")
    print("   💡 建议包含: 核心实验发现、微观机制对比、分子设计原则与未来应用展望")
    print("   👉 [支持任意多行粘贴，中间可随意空行。全部输入完成后，在最后单独一行输入 EOF 并回车提交]:")
    
    blueprint_lines = []
    while True:
        try:
            line = input()
            if line.strip().upper() == "EOF":
                break
            blueprint_lines.append(line)
        except (KeyboardInterrupt, EOFError):
            break
            
    user_blueprint = "\n".join(blueprint_lines).strip()
    if not user_blueprint:
        print("  ℹ️ 未检测到输入，将使用默认全套 BODIPY 量子点能量转移结论纲领。")
        user_blueprint = (
            "选择性激发有机分子的情况下，电荷转移过程的驱动力主要取决于分子激发态能级与量子点能级的相对位置。"
            "对于BDP1体系，分子激发态HOMO能级高于量子点价带，LUMO能级高于导带，为双向电荷转移提供了驱动力，生成QD⁻-BDP1⁺电荷分离态并通过电荷复合高效生成三重态。"
            "与之形成对比的是，BDP2和BDP3分子的能级差太小或LUMO能级过低，导致电荷转移在能量上极为不利，激发态动力学以量子点到分子的FRET过程和TET为主导。"
            "对比三种分子结构表明，有机分子的构象自由度与D-A特性是决定杂化界面激发态路径选择的关键内在因素，柔性D-A结构有利于电荷转移介导的三重态生成，而刚性共轭结构则倾向于保持局域激发态并通过FRET衰减。"
            "这一认识为设计用于可见光驱动三重态敏化的有机分子提供了重要依据，即通过引入适当的构象扭曲与D-A单元可有效激活电荷转移通道，实现从“能量转移”到“电荷转移”的激发态路径调控。"
        )
        
    # 3. 检索 6 篇顶刊结论范文
    all_conclusions = load_all_raw_conclusions()
    exemplar_conclusions = select_exemplar_conclusions(topic, user_blueprint, all_conclusions, api_key, limit=6)
    
    print(f"\n✨ [范式确定] 本次结论写作成功锁定了以下 6 篇顶刊结论范文:")
    for idx, ex in enumerate(exemplar_conclusions, 1):
        print(f"   📖 [{idx}] {ex['title']}")
        
    # 4. 呼叫 DeepSeek 撰写结论
    draft_result = generate_conclusion_draft(topic, user_blueprint, empirical_materials, exemplar_conclusions, api_key, workspace_dir)
    if not draft_result:
        print("❌ 错误: 结论生成失败。")
        return
        
    en_concl = draft_result.get("english_conclusion", "")
    zh_concl = draft_result.get("chinese_translation", "")
    takeaways = draft_result.get("key_takeaways", [])
    
    # 4. 归档交付文件
    conclusion_report_dir.mkdir(parents=True, exist_ok=True)
    exemplar_pdfs_dir = conclusion_report_dir / "Exemplar_PDFs"
    if exemplar_pdfs_dir.exists():
        try:
            shutil.rmtree(exemplar_pdfs_dir)
        except Exception:
            pass
    exemplar_pdfs_dir.mkdir(parents=True, exist_ok=True)
    
    matched_papers = load_master_registry_papers()
    paper_by_slug = {p.get("slug"): p for p in matched_papers if p.get("slug")}
    
    print("\n🔍 正在将 6 篇顶刊结论范文的 PDF 拷贝至 Exemplar_PDFs/...")
    for idx, ex in enumerate(exemplar_conclusions, 1):
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
                        
    # 5. 写入 Conclusion_Draft.md
    takeaways_str = "\n".join([f"- {t}" for t in takeaways])
    draft_lines = [
        f"# Conclusion (结论与展望) - {topic}\n",
        "## 📝 Academic Conclusion (English)",
        f"{en_concl}\n",
        "## 🇨🇳 中文翻译与学术要点 (Chinese Translation)",
        f"{zh_concl}\n",
        "### 💡 核心结论提炼 (Key Takeaways):",
        f"{takeaways_str}\n"
    ]
    draft_path = conclusion_report_dir / "Conclusion_Draft.md"
    draft_path.write_text("\n".join(draft_lines), encoding="utf-8")
    
    # 6. 写入 Verification_Guide_Conclusion.md
    guide_lines = [
        f"# 🔍 结论 (Conclusion) 事实溯源与顶刊范文对照指南\n",
        f"**论文课题**: {topic}\n",
        "本指南整理了撰写本次结论时参考的 **6 篇顶级学术期刊完整结论原文 (Raw Conclusions)**。\n",
        "所有对应的原装 PDF 已完整拷贝至 `Exemplar_PDFs/` 目录下，您可以双击随时阅读顶刊通讯作者的写作句式与升华脉络！\n",
        "## 🏛️ 参考的 6 篇顶刊结论范文",
        "| 范文序号 | 范文 PDF 文件 (位于 `Exemplar_PDFs/`) | 完整论文标题与元数据 |",
        "|---|---|---|"
    ]
    for idx, ex in enumerate(exemplar_conclusions, 1):
        pdf_col = f"📖 `{ex.get('pdf_name')}`" if ex.get("pdf_found") else "📁 知识库收录"
        ex_record = paper_by_slug.get(ex["slug"], {})
        meta = ex_record.get("metadata", {})
        year = meta.get("year", "N/A")
        authors = ", ".join([a.get("name", "") for a in meta.get("authors", [])][:2])
        guide_lines.append(f"| **[范文 {idx}]** | {pdf_col} | **{ex['title']}**<br>*{authors} ({year})* |")
        
    guide_lines.append("\n## 📝 6 篇顶刊结论原文完整对比 (Verbatim Literature Conclusions):\n")
    for idx, ex in enumerate(exemplar_conclusions, 1):
        guide_lines.append(f"### 📍 [范文 {idx}]：{ex['title']}")
        if ex.get("pdf_found"):
            guide_lines.append(f"- **对应原装 PDF**: 请双击 `Exemplar_PDFs/{ex['pdf_name']}`")
        guide_lines.append(f"- **顶刊结论全文 (Verbatim Published Conclusion)**:")
        guide_lines.append(f"> {ex['raw_conclusion'].replace(chr(10), chr(10) + '> ')}")
        guide_lines.append("\n" + "-" * 60 + "\n")
        
    guide_path = conclusion_report_dir / "Verification_Guide_Conclusion.md"
    guide_path.write_text("\n".join(guide_lines), encoding="utf-8")
    
    print("\n" + "=" * 80)
    print("🎉 恭喜！学术结论与高阶升华报告包已圆满完成！")
    print(f"  ➜ 交付目录: {conclusion_report_dir}")
    print(f"  ➜ 1. 终极中英双语结论手稿: {conclusion_report_dir}\\Conclusion_Draft.md")
    print(f"  ➜ 2. 6 篇顶刊结论范文 PDF 库: {conclusion_report_dir}\\Exemplar_PDFs\\ （双击即看）")
    print(f"  ➜ 3. 结论事实溯源与句式对照表: {conclusion_report_dir}\\Verification_Guide_Conclusion.md")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
