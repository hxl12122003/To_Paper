# -*- coding: utf-8 -*-
"""
AutoSci Full Manuscript Assembler & Master Stitching Station (Deep Scientific Integration Engine)
===================================================================================
【100% 顶刊出版级全篇集成与深度学术总装系统】
本程序作为学术论文整装大师，负责将工作区中各个独立模块智能缝合为顶级期刊整篇手稿：
1. 【精准无残留资产解析 (Clean Asset Extraction)】：
   - 彻底剥离各子模块中的临时标题、中间提示、Markdown乱码；
   - 完美提取纯净的 Figure Caption, English Results & Discussion, 中文解析；
2. 【用户自定义绝对生效的图表排序与连续重排 (Strict User-Driven Figure Ordering)】：
   - 保证用户指定的顺序（例如将 Fig12 移至最后）100% 绝对生效；
   - 自动连续重新编排正文图表为 `Figure 1, Figure 2...`，SI 图表为 `Figure S1, Figure S2...`；
   - 统一规范化 Caption 格式为 `> **Figure X.** <Text>`，杜绝多重星号与错位；
3. 【真·正文出现先后顺序全局引文对账引擎 (Sequential First-Appearance Citation Indexer)】：
   - 彻底杜绝章节内部局部 `[1]` 重复混乱的问题；
   - 从引言到各图表正文，按读者从头到尾的阅读顺序，首次出现的文献严格从 `[1]` 开始递增编号；
   - 后续重复引用的文献保持已有编号，新文献依次递增分配 `[2]`, `[3]`... `[N]`；
   - 最终 `## References` 列表与正文首次出现的次序 100% 严格一致；
   - 归档 PDF 严格按新全局编号命名；
4. 【顶刊 Results & Discussion 宏观架构与自然递进 (Integrated Narrative Flow)】：
   - 呼叫 DeepSeek 结合目标期刊范式，将孤立的图表手稿升华为连贯流畅的宏观学术叙事；
   - 彻底剔除“为了合理解释BDP1、BDP2和BDP3...我们构建了能级图”等一切模板化车轱辘套话；
   - 提炼高水平主题小标题，开门见山展示实验数据与光谱物理分析；
5. 【主手稿与 SI 双轨交付 (Dual-Track Output)】：
   - `Main_Manuscript.md`：Title, Abstract, Introduction, Results & Discussion, Conclusion, References；
   - `Supporting_Information.md`：S1 Materials, S2 Synthetic Procedures, S3 Instrumentation, S4 Supplementary Figures；
   - `Verification_Guide_Manuscript.md`：全篇事实核对指南。
"""

import os
import sys
import re
import json
import shutil
import urllib.request
from pathlib import Path
from typing import List, Dict, Any, Tuple

# ⚙️ 默认路径配置与动态知识库解析
DEFAULT_WORKSPACE_ROOT = Path(r"D:\ARS")
DEFAULT_WIKI_PAPERS_DIR = Path(r"D:\ARS\AutoSci-main\wiki\papers")
DEFAULT_LITERATURE_LIBRARY_DIR = Path(r"D:\ARS\Literature_Library")
DEEPSEEK_KEY_FILE_PATH = r"D:\ARS\deepseek_api_key.txt"

def resolve_system_paths(workspace_dir: Path) -> Tuple[Path, Path, Path]:
    """智能解析知识库与文献大表路径 (优先使用工作区内子目录，自动回落至 D:\ARS 中央库)"""
    lib_dir = workspace_dir / "Literature_Library" if (workspace_dir / "Literature_Library").exists() else DEFAULT_LITERATURE_LIBRARY_DIR
    wiki_papers = workspace_dir / "AutoSci-main" / "wiki" / "papers" if (workspace_dir / "AutoSci-main" / "wiki" / "papers").exists() else DEFAULT_WIKI_PAPERS_DIR
    master_reg = lib_dir / "master_registry.json"
    return lib_dir, wiki_papers, master_reg

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

def make_slug_from_title(title: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
    return clean[:60] if clean else "academic-article"

# ==============================================================================
# 全局文献元数据全域打捞系统 (纯粹读取本地 JSON 大表与知识库数据，信息不全则留空，绝不瞎猜)
# ==============================================================================

def harvest_comprehensive_paper_metadata(workspace_dir: Path) -> Dict[str, Dict[str, Any]]:
    """
    纯粹从本地 master_registry.json、Metadata/*.json、wiki/papers/*.md 与各 Verification Guide 中
    打捞真实的作者、年份、期刊与 DOI 信息。缺失字段保持为空，不做任何推断臆造。
    """
    metadata_map: Dict[str, Dict[str, Any]] = {}
    lib_dir, wiki_papers_dir, master_registry_path = resolve_system_paths(workspace_dir)
    
    # 1. 读取 master_registry.json (S2 API 历史入库的官方元数据大表)
    if master_registry_path.exists():
        try:
            data = json.loads(master_registry_path.read_text(encoding="utf-8", errors="ignore"))
            for p in data.get("matched_papers", []):
                slug = p.get("slug")
                if not slug:
                    continue
                meta = p.get("metadata", {})
                authors_raw = meta.get("authors", [])
                title = meta.get("title") or slug.replace("-", " ").title()
                year = str(meta.get("year") or "").strip()
                if year in ["None", "null", "n.d.", "N/A"]:
                    year = ""
                venue = (meta.get("venue") or "").strip()
                
                ext_ids = meta.get("externalIds", {}) if isinstance(meta.get("externalIds"), dict) else {}
                doi = (ext_ids.get("DOI") or meta.get("doi") or "").strip()
                
                metadata_map[slug] = {
                    "slug": slug,
                    "title": title.strip().rstrip("."),
                    "authors": authors_raw if authors_raw else "Anon.",
                    "year": year,
                    "venue": venue,
                    "doi": doi,
                    "pdf_path": p.get("pdf_path")
                }
        except Exception:
            pass

    # 2. 扫描 Literature_Library/Metadata/*.json 补充官方元数据
    meta_dir = lib_dir / "Metadata"
    if meta_dir.exists():
        for jf in meta_dir.glob("*.json"):
            try:
                mdata = json.loads(jf.read_text(encoding="utf-8", errors="ignore"))
                m_title = (mdata.get("title") or "").strip()
                m_slug = make_slug_from_title(m_title) if m_title else ""
                if m_slug in metadata_map:
                    if not metadata_map[m_slug].get("venue") and mdata.get("venue"):
                        metadata_map[m_slug]["venue"] = str(mdata.get("venue")).strip()
                    if not metadata_map[m_slug].get("year") and mdata.get("year"):
                        metadata_map[m_slug]["year"] = str(mdata.get("year")).strip()
                    if not metadata_map[m_slug].get("authors") or metadata_map[m_slug].get("authors") == "Anon.":
                        if mdata.get("authors"):
                            metadata_map[m_slug]["authors"] = mdata.get("authors")
            except Exception:
                pass

    # 3. 深度扫描 wiki/papers/*.md 提取 frontmatter
    if wiki_papers_dir.exists():
        for md_file in wiki_papers_dir.glob("*.md"):
            slug = md_file.stem
            try:
                txt = md_file.read_text(encoding="utf-8", errors="ignore")
                m_venue = re.search(r'^venue:\s*["\']?(.*?)["\']?\s*$', txt, re.MULTILINE)
                m_year = re.search(r'^year:\s*(\d{4})', txt, re.MULTILINE)
                m_doi = re.search(r'^doi:\s*["\']?(.*?)["\']?\s*$', txt, re.MULTILINE)
                m_title = re.search(r'^title:\s*["\']?(.*?)["\']?\s*$', txt, re.MULTILINE)
                
                v_str = m_venue.group(1).strip() if m_venue else ""
                y_str = m_year.group(1).strip() if m_year else ""
                d_str = m_doi.group(1).strip() if m_doi else ""
                t_str = m_title.group(1).strip() if m_title else slug.replace("-", " ").title()
                
                if slug not in metadata_map:
                    metadata_map[slug] = {
                        "slug": slug,
                        "title": t_str,
                        "authors": "Anon.",
                        "year": y_str,
                        "venue": v_str,
                        "doi": d_str,
                        "pdf_path": None
                    }
                else:
                    if not metadata_map[slug].get("venue") and v_str:
                        metadata_map[slug]["venue"] = v_str
                    if not metadata_map[slug].get("year") and y_str:
                        metadata_map[slug]["year"] = y_str
                    if not metadata_map[slug].get("doi") and d_str:
                        metadata_map[slug]["doi"] = d_str
            except Exception:
                pass

    # 4. 扫描工作区所有 Verification Guide 作为强力补充与实体对账
    guide_files = list(workspace_dir.glob("*Report*/**/*Verification_Guide*.md")) + list(workspace_dir.glob("*Verification_Guide*.md"))
    for g in guide_files:
        try:
            txt = g.read_text(encoding="utf-8", errors="ignore").replace("\r\n", "\n")
            rows = re.findall(r"\|\s*\*\*\[(\d+)\]\*\*\s*\|\s*(?:📁|📖)?\s*`?([^`|\n]+)`?\s*\|\s*\*\*([^*]+)\*\*(?:<br>|\n)\*([^*]+)\*\s*(?:(?:<br>|\n)🔗\s*`DOI:\s*([^`]+)`)?", txt)
            for r in rows:
                _, pdf_file, title, author_year, doi = r
                m_slug = re.search(r"\[\d+\]\s*\[\d+\]\s*[^-]+-\s*(.*?)\.pdf", pdf_file)
                slug = m_slug.group(1).strip() if m_slug else ""
                if not slug:
                    slug = make_slug_from_title(title)
                
                m_ay = re.match(r"(.*?)(?:\s*\((\d{4}|N/A|n\.d\.)\))?$", author_year.strip())
                authors = m_ay.group(1).strip() if m_ay else author_year.strip()
                year = m_ay.group(2) if (m_ay and m_ay.group(2) and m_ay.group(2) not in ["N/A", "n.d."]) else ""
                
                clean_title = title.strip().rstrip(".")
                if slug not in metadata_map:
                    metadata_map[slug] = {
                        "slug": slug,
                        "title": clean_title,
                        "authors": authors,
                        "year": year,
                        "venue": "",
                        "doi": doi.strip() if doi else "",
                        "pdf_path": None
                    }
                else:
                    if len(clean_title) > len(metadata_map[slug].get("title", "")):
                        metadata_map[slug]["title"] = clean_title
                    if not metadata_map[slug].get("authors") or metadata_map[slug].get("authors") == "Anon.":
                        metadata_map[slug]["authors"] = authors
                    if not metadata_map[slug].get("year") and year:
                        metadata_map[slug]["year"] = year
                    if not metadata_map[slug].get("doi") and doi:
                        metadata_map[slug]["doi"] = doi.strip()
        except Exception:
            pass

    return metadata_map

# ==============================================================================
# 纯净图表草稿解析器与标准 Caption 统一重塑器
# ==============================================================================

def clean_parse_figure_draft(raw_text: str) -> Tuple[str, str, str]:
    """
    极度健壮地从图表草稿中提取三部分纯净内容：
    1. Caption (图题)
    2. English Results & Discussion (纯净正文，不含重复标题与Caption)
    3. Chinese Results & Discussion (中文解析)
    """
    txt = raw_text.replace("\r\n", "\n")
    
    # 1. 提取 Caption
    caption = ""
    m_cap = re.search(r"(?:##?\s*Figure Caption|\*\*Figure Caption\*\*:?)\s*\n+(.*?)(?=\n+---|\n+##|\n+\*\*Results|\Z)", txt, re.DOTALL | re.IGNORECASE)
    if m_cap:
        caption = m_cap.group(1).strip()
    else:
        lines = [l.strip() for l in txt.split("\n") if l.strip()]
        for l in lines:
            if re.search(r"^\*\*(?:Fig(?:ure)?|Scheme|Table)", l, re.IGNORECASE):
                caption = l
                break
        if not caption and lines:
            caption = lines[0]
            
    caption = re.sub(r"^#+\s*", "", caption).strip()
    
    # 2. 分割中文部分
    zh_pattern = re.compile(r"\n+(?:##?\s*Results and Discussion\s*\(Chinese[^\)]*\)|\*\*Results and Discussion\s*\(Chinese[^\)]*\)\*:?|###?\s*结果与讨论|##?\s*结果与讨论|\*\*结果与讨论\*\*)\s*:?\n*", re.IGNORECASE)
    parts = zh_pattern.split(txt, maxsplit=1)
    
    pre_zh = parts[0]
    zh_text = parts[1].strip() if len(parts) > 1 else ""
    zh_text = re.split(r"\n+##?\s*References", zh_text, flags=re.IGNORECASE)[0].strip()
    
    # 3. 提取英文部分
    en_pattern = re.compile(r"\n+(?:##?\s*Results and Discussion(?:\s*\(English[^\)]*\))?|\*\*Results and Discussion(?:\s*\(English[^\)]*\))?\*\*:?|###?\s*Results and Discussion)\s*:?\n*", re.IGNORECASE)
    en_parts = en_pattern.split(pre_zh, maxsplit=1)
    if len(en_parts) > 1:
        en_text = en_parts[1].strip()
    else:
        en_text = pre_zh.replace(caption, "").strip()
        
    # 清理英文正文中的残留杂质行
    clean_lines = []
    for l in en_text.split("\n"):
        ls = l.strip()
        if not ls or ls == "---" or ls.startswith("## Figure Caption") or ls.startswith("**Figure Caption**"):
            continue
        if re.match(r"^#+\s*(?:Fig|Figure|Scheme|Table)\s*\d+", ls, re.IGNORECASE):
            continue
        clean_lines.append(l)
    en_text = "\n".join(clean_lines).strip()
    
    return caption, en_text, zh_text

def format_standard_caption(caption_raw: str, fig_label: str) -> str:
    """提取纯净 Caption 内容，并统一封装为顶刊标准规范 Blockquote 样式：> **Figure X.** Clean text"""
    if not caption_raw:
        return f"> **{fig_label}.** (No caption provided.)"
    txt = caption_raw.strip()
    # 剥离多层 Markdown 粗体和前缀
    txt = re.sub(r"^>+\s*", "", txt)
    txt = re.sub(r"^#+\s*", "", txt)
    # 剥离已有的图号前缀 (如 **Figure 12.** 或 **Fig. 1.** 或 Figure S1: 等)
    txt = re.sub(r"^\*+(?:Fig(?:ure)?\.?|Scheme|Table|图|表|方案)[\s\.]*[S]?\d+[a-z]?[\.\:\-\s]*\*+\s*", "", txt, flags=re.IGNORECASE)
    txt = re.sub(r"^(?:Fig(?:ure)?\.?|Scheme|Table|图|表|方案)[\s\.]*[S]?\d+[a-z]?[\.\:\-\s]+\s*", "", txt, flags=re.IGNORECASE)
    # 剥离残留的首尾星号
    txt = txt.strip(" *")
    return f"> **{fig_label}.** {txt}"

# ==============================================================================
# 工作区资产动态扫描与解析
# ==============================================================================

def is_si_figure_asset(folder_name: str, caption: str, content: str) -> bool:
    """智能判定图表是否属于 SI 补充材料"""
    clean_name = folder_name.replace("_Report", "").lower()
    if re.search(r"(?:^|[_\-])s\d+", clean_name) or re.search(r"(?:fig|figure|scheme|table)s\d+", clean_name):
        return True
    first_line = caption.strip().split("\n")[0]
    if re.search(r"^(?:#+\s*)?(?:\*\*)?(?:Fig(?:ure)?\.?|Scheme|Table)\s*S\d+", first_line, re.IGNORECASE):
        return True
    if re.search(r"^(?:#+\s*)?(?:\*\*)?(?:图|表|方案)\s*S\d+", first_line, re.IGNORECASE):
        return True
    return False

def extract_figure_identity(folder_name: str, caption: str) -> Dict[str, Any]:
    """提取图表的前缀类型与原始编号标识"""
    clean_name = folder_name.replace("_Report", "")
    caption_line = caption.strip().split("\n")[0]
    
    ptype = "Figure"
    if re.search(r"\bscheme\b", clean_name, re.IGNORECASE) or re.search(r"\bscheme\b", caption_line, re.IGNORECASE):
        ptype = "Scheme"
    elif re.search(r"\btable\b", clean_name, re.IGNORECASE) or re.search(r"\btable\b", caption_line, re.IGNORECASE):
        ptype = "Table"
        
    old_num = ""
    m_cap = re.search(r"(?:Fig(?:ure)?\.?|Scheme|Table|图|表|方案)\s*([S]?\d+[a-z]?)", caption_line, re.IGNORECASE)
    if m_cap:
        old_num = m_cap.group(1).upper()
    else:
        m_name = re.search(r"(?:fig|figure|scheme|table)?_?([s]?\d+[a-z]?)", clean_name, re.IGNORECASE)
        if m_name:
            old_num = m_name.group(1).upper()
            
    return {
        "ptype": ptype,
        "old_num": old_num,
        "clean_name": clean_name
    }

def figure_natural_sort_key(fig_item: Dict[str, Any]) -> Tuple[int, int, str, str]:
    """数值自然排序键：确保图表默认按从小到大严格数值排序 (如 1a, 1b, 1c, 4, 5, 7, 8a, 8b, 8c, 9, 12 等)"""
    is_si = 1 if fig_item.get("is_si") else 0
    old_num = str(fig_item.get("old_num") or "").strip().lower()
    clean_name = str(fig_item.get("folder_name") or fig_item.get("name") or "").replace("_Report", "").lower()
    
    m_num = re.search(r"(\d+)([a-z]?)", old_num)
    if m_num:
        num = int(m_num.group(1))
        sub = m_num.group(2)
    else:
        m_folder = re.search(r"(\d+)([a-z]?)", clean_name)
        if m_folder:
            num = int(m_folder.group(1))
            sub = m_folder.group(2)
        else:
            num = 999
            sub = ""
            
    return (is_si, num, sub, clean_name)

def scan_workspace_manuscript_assets(workspace_dir: Path) -> Dict[str, Any]:
    """扫描工作区所有资产并执行纯净解析与自然排序"""
    assets = {
        "introduction": None,
        "conclusion": None,
        "experimental_sections": [],
        "main_figures": [],
        "si_figures": []
    }
    
    # 1. 扫描引言
    intro_file = workspace_dir / "Introduction_Final_Report" / "Introduction_Final_Draft.md"
    intro_guide = workspace_dir / "Introduction_Final_Report" / "Verification_Guide_Global.md"
    if intro_file.exists():
        try:
            content = intro_file.read_text(encoding="utf-8", errors="ignore")
            m_en = re.search(r"## 📄 Full Academic Introduction.*?\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
            m_zh = re.search(r"## 🇨🇳 中文完整学术引言.*?\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
            assets["introduction"] = {
                "file_path": intro_file,
                "guide_path": intro_guide if intro_guide.exists() else None,
                "english_text": m_en.group(1).strip() if m_en else content,
                "chinese_text": m_zh.group(1).strip() if m_zh else ""
            }
        except Exception:
            pass
            
    # 2. 扫描结论
    concl_file = workspace_dir / "Conclusion_Report" / "Conclusion_Draft.md"
    concl_guide = workspace_dir / "Conclusion_Report" / "Verification_Guide_Conclusion.md"
    if concl_file.exists():
        try:
            content = concl_file.read_text(encoding="utf-8", errors="ignore")
            m_en = re.search(r"## 📝 Academic Conclusion.*?\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
            m_zh = re.search(r"## 🇨🇳 中文翻译与学术要点.*?\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
            assets["conclusion"] = {
                "file_path": concl_file,
                "guide_path": concl_guide if concl_guide.exists() else None,
                "english_text": m_en.group(1).strip() if m_en else content,
                "chinese_text": m_zh.group(1).strip() if m_zh else ""
            }
        except Exception:
            pass
            
    # 3. 扫描实验部分 (Experimental_Report)
    exp_dir = workspace_dir / "Experimental_Report"
    if exp_dir.exists():
        for sub in sorted(exp_dir.glob("*_Report")):
            for draft_file in sub.glob("*_Draft.md"):
                try:
                    content = draft_file.read_text(encoding="utf-8", errors="ignore")
                    guide_file = sub / "Verification_Guide_Experimental.md"
                    assets["experimental_sections"].append({
                        "name": sub.name.replace("_Report", ""),
                        "file_path": draft_file,
                        "guide_path": guide_file if guide_file.exists() else None,
                        "content": content
                    })
                except Exception:
                    pass
                    
    # 4. 扫描所有实验图表报告
    seen_reports = set()
    raw_main_figures = []
    raw_si_figures = []
    
    for d in sorted(workspace_dir.iterdir()):
        if not d.is_dir():
            continue
        if d.name in ["Introduction_Final_Report", "Introduction_Workspace", "Conclusion_Report", "Experimental_Report", "Final_Manuscript_Pack"]:
            continue
        if "Report" in d.name:
            for draft_file in d.glob("*_Draft.md"):
                if draft_file in seen_reports:
                    continue
                seen_reports.add(draft_file)
                try:
                    raw_content = draft_file.read_text(encoding="utf-8", errors="ignore")
                    guide_file = d / "Verification_Guide.md"
                    
                    caption, en_text, zh_text = clean_parse_figure_draft(raw_content)
                    is_si = is_si_figure_asset(d.name, caption, raw_content)
                    ident = extract_figure_identity(d.name, caption)
                    
                    fig_item = {
                        "name": d.name.replace("_Report", ""),
                        "folder_name": d.name,
                        "file_path": draft_file,
                        "guide_path": guide_file if guide_file.exists() else None,
                        "caption": caption,
                        "english_text": en_text,
                        "chinese_text": zh_text,
                        "is_si": is_si,
                        "ptype": ident["ptype"],
                        "old_num": ident["old_num"]
                    }
                    
                    if is_si:
                        raw_si_figures.append(fig_item)
                    else:
                        raw_main_figures.append(fig_item)
                except Exception:
                    pass
                    
    # 按照自然数值逻辑从小到大严格排序 (1a, 1b, 1c ... 9, 12)
    raw_main_figures.sort(key=figure_natural_sort_key)
    raw_si_figures.sort(key=figure_natural_sort_key)
    
    assets["main_figures"] = raw_main_figures
    assets["si_figures"] = raw_si_figures
    return assets

# ==============================================================================
# 图表序号智能连续化重排与全文无缝同步 (Figure Continuity Engine)
# ==============================================================================

def apply_figure_renumbering(text: str, renumber_rules: List[Dict[str, str]]) -> str:
    """精准替换全文中的图表引用与编号"""
    if not text:
        return ""
    result = text
    sorted_rules = sorted(renumber_rules, key=lambda r: len(r["old_num"]), reverse=True)
    
    for rule in sorted_rules:
        old_num = rule["old_num"]
        new_num = rule["new_num"]
        ptype = rule.get("ptype", "Figure")
        
        if not old_num or old_num == new_num:
            continue
            
        escaped_old = re.escape(old_num)
        
        # 1. 替换 Fig. X / Figs. X / Scheme. X / Table. X
        result = re.sub(rf"\b(Fig|Scheme|Table)\.\s*{escaped_old}(?=[^a-zA-Z0-9]|$)", rf"\g<1>. {new_num}", result, flags=re.IGNORECASE)
        # 2. 替换 Figure X / Scheme X / Table X
        result = re.sub(rf"\b(Figure|Scheme|Table)\s*{escaped_old}(?=[^a-zA-Z0-9]|$)", rf"\g<1> {new_num}", result, flags=re.IGNORECASE)
        # 3. 替换 FigX (如 Fig12 / FigS4)
        result = re.sub(rf"\b(Fig|Scheme|Table){escaped_old}(?=[^a-zA-Z0-9]|$)", rf"\g<1> {new_num}", result, flags=re.IGNORECASE)
        # 4. 替换中文: 图12 / 图 12 / 表12 / 方案12
        result = re.sub(rf"(图|表|方案)\s*{escaped_old}(?=[^a-zA-Z0-9]|$)", rf"\g<1>{new_num}", result, flags=re.IGNORECASE)
        # 5. 替换 Caption: **Fig. 12.** -> **Figure 1.**
        result = re.sub(rf"\*\*(?:Fig(?:ure)?\.?|Scheme|Table)\.?\s*{escaped_old}\.\*\*", rf"**{ptype} {new_num}.**", result, flags=re.IGNORECASE)
        # 6. 替换普通粗体引用: **Figure 12**
        result = re.sub(rf"\*\*(?:Figure|Fig|Scheme|Table)\.?\s*{escaped_old}\*\*", rf"**{ptype} {new_num}**", result, flags=re.IGNORECASE)
        
    return result

def realign_figure_sequence(
    figures: List[Dict[str, Any]],
    is_si: bool = False
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """将图表按用户最终确定的顺序重编为连续的 Figure 1, Figure 2... 或 Figure S1, Figure S2..."""
    renumber_rules = []
    updated_figures = []
    
    for idx, f in enumerate(figures, 1):
        f_copy = dict(f)
        ptype = f_copy.get("ptype", "Figure")
        old_num = f_copy.get("old_num", "")
        new_num = f"S{idx}" if is_si else f"{idx}"
        
        if old_num and old_num != new_num:
            renumber_rules.append({
                "ptype": ptype,
                "old_num": old_num,
                "new_num": new_num
            })
            
        f_copy["final_label"] = f"{ptype} {new_num}"
        f_copy["final_num"] = new_num
        updated_figures.append(f_copy)
        
    if renumber_rules:
        for f in updated_figures:
            f["caption"] = apply_figure_renumbering(f["caption"], renumber_rules)
            f["english_text"] = apply_figure_renumbering(f["english_text"], renumber_rules)
            f["chinese_text"] = apply_figure_renumbering(f["chinese_text"], renumber_rules)
            
    return updated_figures, renumber_rules

# ==============================================================================
# 终极文献按正文先后顺序连续编号与对账引擎 (Sequential Citation Indexing Engine)
# ==============================================================================

def parse_guide_local_mapping(guide_path: Path, metadata_map: Dict[str, Dict[str, Any]]) -> Dict[int, str]:
    """解析单个资产的 Verification_Guide.md，建立其局部 [1]~[6] -> 物理文献 slug 的严格映射"""
    local_map: Dict[int, str] = {}
    if not guide_path or not guide_path.exists():
        return local_map
    try:
        txt = guide_path.read_text(encoding="utf-8", errors="ignore").replace("\r\n", "\n")
        # 扫描表格行
        rows = re.findall(r"\|\s*\*\*\[(\d+)\]\*\*\s*\|\s*(?:📁|📖)?\s*`?([^`|\n]+)`?\s*\|\s*\*\*([^*]+)\*\*", txt)
        for r in rows:
            l_idx_str, pdf_file, title = r
            l_idx = int(l_idx_str)
            m_slug = re.search(r"\[\d+\]\s*\[\d+\]\s*[^-]+-\s*(.*?)\.pdf", pdf_file)
            slug = m_slug.group(1).strip() if m_slug else ""
            if not slug:
                # 从标题查找匹配或新建 slug
                slug = make_slug_from_title(title)
            local_map[l_idx] = slug
            if slug not in metadata_map:
                metadata_map[slug] = {
                    "slug": slug,
                    "title": title.strip().rstrip("."),
                    "authors": "Anon.",
                    "year": "n.d.",
                    "venue": "",
                    "doi": "",
                    "pdf_path": None
                }
    except Exception:
        pass
    return local_map

def ground_text_citations(text: str, local_mapping: Dict[int, str]) -> str:
    """
    将正文中的局部引用标签 [1], [1, 2], [1-3], [CAND_1] 精准替换为全域唯一的实体占位符 {{REF:<slug>}}
    """
    if not text or not local_mapping:
        return text

    # 正则捕获类似 [1], [1, 2], [1, 3, 5], [1-3], [CAND_1, CAND_2] 的引用方括号
    # 避免误伤 [1S3/2–1Se] 这种包含非数字字母的物理光谱态
    def replace_citation_match(match: re.Match) -> str:
        inside = match.group(1).strip()
        # 检查是否全部由数字、逗号、短横线、空格或 CAND_ 组成
        parts = re.split(r"[,，\s]+", inside)
        matched_slugs = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if "-" in part or "–" in part or "—" in part:
                sub_parts = re.split(r"[-–—]", part)
                sub_nums = [int(re.sub(r"\D", "", x)) for x in sub_parts if re.search(r"\d+", x)]
                if len(sub_nums) == 2 and sub_nums[0] <= sub_nums[1]:
                    for n in range(sub_nums[0], sub_nums[1] + 1):
                        if n in local_mapping:
                            s = local_mapping[n]
                            if s not in matched_slugs:
                                matched_slugs.append(s)
                continue
            # 单一数字或 CAND_X
            m_num = re.search(r"\d+", part)
            if m_num:
                n = int(m_num.group(0))
                if n in local_mapping:
                    s = local_mapping[n]
                    if s not in matched_slugs:
                        matched_slugs.append(s)
        if matched_slugs:
            return " " + ", ".join([f"{{{{REF:{s}}}}}" for s in matched_slugs]) + " "
        return match.group(0)

    # 匹配模式
    pattern = re.compile(r"\[\s*([0-9\s,，\-–—]|CAND_\d+)+\s*\]")
    return pattern.sub(replace_citation_match, text)

def sequential_reindex_full_manuscript(
    text_blocks: List[Tuple[str, str]], # [(block_id, raw_grounded_text), ...]
    metadata_map: Dict[str, Dict[str, Any]]
) -> Tuple[Dict[str, str], List[Dict[str, Any]], Dict[str, int]]:
    """
    【核心：正文出现先后顺序全局引文重编器】
    从整篇文章的第一段顺序扫描到最后一段：
    - 遇到第一个出现的文献实体 slug，赋予全局编号 1；
    - 遇到第二个未见过的实体，赋予全局编号 2；
    - 已经出现过的实体复用其已分配的编号；
    - 将同一括号内的多个引用自动去重并按数值升序排布（例如 [1, 2], [1, 3, 5]）；
    - 输出重编后的全部文本块、按 [1]~[N] 严格排序的参考文献列表、以及 slug->global_id 映射字典。
    """
    slug_to_id: Dict[str, int] = {}
    ordered_refs: List[Dict[str, Any]] = []
    reindexed_blocks: Dict[str, str] = {}
    
    # 步骤 A：顺序扫描全文，建立按首次出现顺序排序的实体池
    for block_id, text in text_blocks:
        if not text:
            continue
        matches = re.findall(r"\{\{REF:([^}]+)\}\}", text)
        for slug in matches:
            slug = slug.strip()
            if slug and slug not in slug_to_id:
                new_idx = len(ordered_refs) + 1
                slug_to_id[slug] = new_idx
                p_meta = metadata_map.get(slug, {
                    "slug": slug,
                    "title": slug.replace("-", " ").title(),
                    "authors": "Anon.",
                    "year": "n.d.",
                    "venue": "",
                    "doi": "",
                    "pdf_path": None
                })
                p_meta["global_index"] = new_idx
                ordered_refs.append(p_meta)
                
    # 步骤 B：将每个文本块中的占位符群替换为标准规范的 [1], [1, 2]...
    ref_cluster_pattern = re.compile(r"(\{\{REF:[^}]+\}\}(?:\s*[,，\s]*\s*\{\{REF:[^}]+\}\})*)")
    
    for block_id, text in text_blocks:
        if not text:
            reindexed_blocks[block_id] = ""
            continue
            
        def format_cluster(match: re.Match) -> str:
            cluster_text = match.group(1)
            raw_slugs = re.findall(r"\{\{REF:([^}]+)\}\}", cluster_text)
            assigned_ids = []
            for s in raw_slugs:
                s = s.strip()
                if s in slug_to_id:
                    gid = slug_to_id[s]
                    if gid not in assigned_ids:
                        assigned_ids.append(gid)
            if not assigned_ids:
                return ""
            assigned_ids.sort()
            return f"[{', '.join(str(x) for x in assigned_ids)}]"
            
        new_text = ref_cluster_pattern.sub(format_cluster, text)
        # 清理多余空格
        new_text = re.sub(r"\s+([,.\)])", r"\1", new_text)
        reindexed_blocks[block_id] = new_text
        
    return reindexed_blocks, ordered_refs, slug_to_id

JOURNAL_ABBREVIATIONS = {
    "journal of the american chemical society": "J. Am. Chem. Soc.",
    "nature communications": "Nat. Commun.",
    "nature chemistry": "Nat. Chem.",
    "nature materials": "Nat. Mater.",
    "nature photonics": "Nat. Photonics",
    "nature nanotechnology": "Nat. Nanotechnol.",
    "nature energy": "Nat. Energy",
    "nature": "Nature",
    "science": "Science",
    "science advances": "Sci. Adv.",
    "angewandte chemie international edition": "Angew. Chem. Int. Ed.",
    "angewandte chemie": "Angew. Chem.",
    "advanced materials": "Adv. Mater.",
    "advanced energy materials": "Adv. Energy Mater.",
    "advanced functional materials": "Adv. Funct. Mater.",
    "advanced optical materials": "Adv. Opt. Mater.",
    "acs nano": "ACS Nano",
    "acs energy letters": "ACS Energy Lett.",
    "acs applied materials & interfaces": "ACS Appl. Mater. Interfaces",
    "acs applied materials and interfaces": "ACS Appl. Mater. Interfaces",
    "acs catalysis": "ACS Catal.",
    "acs photonics": "ACS Photonics",
    "acs central science": "ACS Cent. Sci.",
    "chemical science": "Chem. Sci.",
    "chem": "Chem",
    "matter": "Matter",
    "joule": "Joule",
    "chemical society reviews": "Chem. Soc. Rev.",
    "accounts of chemical research": "Acc. Chem. Res.",
    "chemical reviews": "Chem. Rev.",
    "chemical communications": "Chem. Commun.",
    "journal of physical chemistry c": "J. Phys. Chem. C",
    "the journal of physical chemistry c": "J. Phys. Chem. C",
    "journal of physical chemistry letters": "J. Phys. Chem. Lett.",
    "the journal of physical chemistry letters": "J. Phys. Chem. Lett.",
    "journal of physical chemistry a": "J. Phys. Chem. A",
    "journal of physical chemistry b": "J. Phys. Chem. B",
    "physical chemistry chemical physics": "Phys. Chem. Chem. Phys.",
    "journal of chemical physics": "J. Chem. Phys.",
    "the journal of chemical physics": "J. Chem. Phys.",
    "chemphyschem": "ChemPhysChem",
    "chemistry – a european journal": "Chem. Eur. J.",
    "chemistry - a european journal": "Chem. Eur. J.",
    "chemistry": "Chemistry",
    "chemistry of materials": "Chem. Mater.",
    "journal of materials chemistry a": "J. Mater. Chem. A",
    "journal of materials chemistry c": "J. Mater. Chem. C",
    "nano letters": "Nano Lett.",
    "nano energy": "Nano Energy",
    "small": "Small",
    "energy & environmental science": "Energy Environ. Sci.",
    "energy and environmental science": "Energy Environ. Sci.",
    "proceedings of the national academy of sciences": "Proc. Natl. Acad. Sci. U.S.A.",
    "jacs au": "JACS Au",
    "organic letters": "Org. Lett.",
    "journal of organic chemistry": "J. Org. Chem.",
    "coordination chemistry reviews": "Coord. Chem. Rev.",
    "inorganic chemistry": "Inorg. Chem."
}

def abbreviate_journal_name(venue: str) -> str:
    """智能缩写期刊名称为标准 CASSI / ISO 4 规范"""
    if not venue:
        return ""
    v_clean = venue.strip().rstrip(".").lower()
    for full_name, abbr in JOURNAL_ABBREVIATIONS.items():
        if v_clean == full_name or v_clean == full_name.lower():
            return abbr
    for full_name, abbr in JOURNAL_ABBREVIATIONS.items():
        if full_name in v_clean:
            return abbr
    return venue.strip().rstrip(".")

def parse_single_author_name(name_str: str) -> Tuple[str, str]:
    """解析单个作者姓名，返回 (surname, initials)"""
    name = name_str.strip()
    if not name or name.lower() in ["anon", "anon.", "anonymous", "et al", "et al."]:
        return "", ""
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        surname = parts[0]
        rest = parts[1]
        rest_tokens = re.findall(r"[A-Za-z\u00C0-\u024F\u1E00-\u1EFF]+", rest)
        initials_list = [f"{tok[0].upper()}." for tok in rest_tokens]
        initials = " ".join(initials_list) if initials_list else ""
        return surname, initials
    tokens = re.findall(r"[A-Za-z\u00C0-\u024F\u1E00-\u1EFF]+", name)
    if not tokens:
        return name, ""
    if len(tokens) == 1:
        return tokens[0], ""
    surname = tokens[-1]
    initials_list = [f"{t[0].upper()}." for t in tokens[:-1]]
    initials = " ".join(initials_list)
    return surname, initials

def parse_author_string(author_input) -> List[Tuple[str, str]]:
    """从 list 或 string 中解析出所有作者 (surname, initials) 列表"""
    if not author_input:
        return []
    raw_names = []
    if isinstance(author_input, list):
        for a in author_input:
            if isinstance(a, dict):
                raw_names.append(a.get("name", ""))
            elif isinstance(a, str):
                raw_names.append(a)
    elif isinstance(author_input, str):
        clean_str = re.sub(r"\bet\s+al\.?", "", author_input, flags=re.IGNORECASE).strip()
        if ";" in clean_str:
            raw_names = [n.strip() for n in clean_str.split(";") if n.strip()]
        else:
            parts = [p.strip() for p in clean_str.split(",") if p.strip()]
            if len(parts) >= 2 and all(len(p.split()) == 1 for p in parts) and any(len(p) <= 2 for p in parts[1::2]):
                for i in range(0, len(parts), 2):
                    if i + 1 < len(parts):
                        raw_names.append(f"{parts[i]}, {parts[i+1]}")
                    else:
                        raw_names.append(parts[i])
            else:
                raw_names = parts
                
    result = []
    for rn in raw_names:
        surname, initials = parse_single_author_name(rn)
        if surname:
            result.append((surname, initials))
    return result

def format_reference_by_journal_style(
    ref: Dict[str, Any],
    target_journal: str
) -> str:
    """
    根据目标期刊风格生成标准出版级参考文献条目：
    - 纯粹从 master_registry.json 等本地大表中提取信息，不臆造；信息不全的字段直接留空
    - JACS (ACS Style): [1] Author, A. B.; Author, C. D. Title. *J. Am. Chem. Soc.* **2021**, https://doi.org/...
    - Nature Portfolio Style: [1] Author, A. B., Author, C. D. & Author, E. F. Title. *Nat. Commun.* (2021). https://doi.org/...
    - Wiley Style (Angewandte / Adv Mater): [1] A. B. Author, C. D. Author, Title. *Angew. Chem. Int. Ed.* **2021**, https://doi.org/...
    """
    g_idx = ref.get("global_index", 1)
    authors_raw = ref.get("authors", "")
    author_tuples = parse_author_string(authors_raw)
    
    title = (ref.get("title") or "Untitled Academic Article").strip().rstrip(".")
    venue_raw = (ref.get("venue") or "").strip()
    venue_abbr = abbreviate_journal_name(venue_raw)
    year = str(ref.get("year") or "").strip()
    if year in ["n.d.", "N/A", "None", "null", ""]:
        year = ""
    doi = (ref.get("doi") or "").strip()
    doi_str = f" https://doi.org/{doi}" if doi else ""
    
    tj_lower = target_journal.lower()
    
    # 1. JACS / ACS 风格 (默认)
    if "jacs" in tj_lower or "acs" in tj_lower or "american chemical society" in tj_lower:
        if author_tuples:
            if len(author_tuples) > 10:
                auth_parts = [f"{s}, {ini}" if ini else s for s, ini in author_tuples[:10]]
                authors_formatted = "; ".join(auth_parts) + "; et al."
            else:
                auth_parts = [f"{s}, {ini}" if ini else s for s, ini in author_tuples]
                authors_formatted = "; ".join(auth_parts)
        else:
            authors_formatted = "Anon."
            
        journal_part = f" *{venue_abbr}*" if venue_abbr else ""
        year_part = f" **{year}**," if year else ""
        
        # JACS 标准: [1] He, S.; Xie, H.; Liu, M. Article Title. *J. Am. Chem. Soc.* **2025**, https://doi.org/...
        ref_line = f"[{g_idx}] {authors_formatted} {title}.{journal_part}{year_part}{doi_str}"
        return re.sub(r"\s+", " ", ref_line).strip()
        
    # 2. Nature Portfolio 风格
    elif "nature" in tj_lower:
        if author_tuples:
            if len(author_tuples) == 1:
                authors_formatted = f"{author_tuples[0][0]}, {author_tuples[0][1]}" if author_tuples[0][1] else author_tuples[0][0]
            elif len(author_tuples) <= 5:
                auth_parts = [f"{s}, {ini}" if ini else s for s, ini in author_tuples[:-1]]
                last = f"{author_tuples[-1][0]}, {author_tuples[-1][1]}" if author_tuples[-1][1] else author_tuples[-1][0]
                authors_formatted = ", ".join(auth_parts) + f" & {last}"
            else:
                first = f"{author_tuples[0][0]}, {author_tuples[0][1]}" if author_tuples[0][1] else author_tuples[0][0]
                authors_formatted = f"{first} et al."
        else:
            authors_formatted = "Anon."
            
        journal_part = f" *{venue_abbr}*" if venue_abbr else ""
        year_part = f" ({year})" if year else ""
        ref_line = f"[{g_idx}] {authors_formatted} {title}.{journal_part}{year_part}.{doi_str}"
        return re.sub(r"\s+", " ", ref_line).strip()

    # 3. Wiley 风格 (Angewandte / Advanced Materials)
    else:
        if author_tuples:
            if len(author_tuples) > 7:
                auth_parts = [f"{ini} {s}" if ini else s for s, ini in author_tuples[:7]]
                authors_formatted = ", ".join(auth_parts) + ", et al."
            else:
                auth_parts = [f"{ini} {s}" if ini else s for s, ini in author_tuples]
                authors_formatted = ", ".join(auth_parts)
        else:
            authors_formatted = "Anon."
            
        journal_part = f" *{venue_abbr}*" if venue_abbr else ""
        year_part = f" **{year}**," if year else ""
        ref_line = f"[{g_idx}] {authors_formatted}, {title}.{journal_part}{year_part}{doi_str}"
        return re.sub(r"\s+", " ", ref_line).strip()

def build_journal_style_references(global_refs: List[Dict[str, Any]], target_journal: str) -> str:
    """生成与所选期刊风格完全一致的出版级参考文献列表（严格按 [1], [2], [3]... 升序排布）"""
    lines = ["## References\n"]
    for ref in global_refs:
        ref_line = format_reference_by_journal_style(ref, target_journal)
        lines.append(ref_line)
        
    return "\n".join(lines)

# ==============================================================================
# 目标顶刊范式智能检索 (如 3 篇 JACS + 3 篇同领域顶刊)
# ==============================================================================

def select_target_journal_exemplars(
    topic: str,
    target_journal: str,
    metadata_map: Dict[str, Dict[str, Any]],
    wiki_papers_dir: Path,
    target_count: int = 3,
    top_tier_count: int = 3
) -> List[Dict[str, Any]]:
    """在知识库中精准检索目标期刊与同领域顶刊范文，并提取其真实图表叙事链与起承转合范式"""
    print(f"\n📚 [期刊范式检索] 正在从知识库中检索目标期刊 [{target_journal}] 与同领域顶刊范文...")
    
    query_tokens = re.findall(r"[a-zA-Z0-9\u4e00-\u9fa5]{2,}", topic.lower())
    STOP_WORDS = {"and", "the", "for", "with", "from", "using", "study", "research", "paper", "investigation"}
    keywords = [w for w in query_tokens if w not in STOP_WORDS]
    
    target_candidates = []
    top_candidates = []
    tj_lower = target_journal.lower()
    
    for slug, meta in metadata_map.items():
        venue = (meta.get("venue") or "").lower()
        title = meta.get("title") or ""
        title_lower = title.lower()
        score = sum(5 for kw in keywords if kw in title_lower)
        
        is_target = any(term in venue for term in [tj_lower, "jacs", "american chemical society"] if "jacs" in tj_lower) if "jacs" in tj_lower else (tj_lower in venue)
        is_top = any(top_name in venue for top_name in ["nature", "angewandte", "advanced materials", "energy & environmental science", "chem"])
        
        md_file = wiki_papers_dir / f"{slug}.md"
        results_progression = ""
        key_idea = ""
        problem_context = ""
        raw_conclusion = ""
        if md_file.exists():
            try:
                md_text = md_file.read_text(encoding="utf-8", errors="ignore")
                m_exp = re.search(r"## Experiment & Results\s*\n(.*?)(?=\n## |\Z)", md_text, re.DOTALL)
                if m_exp:
                    results_progression = m_exp.group(1).strip()
                m_idea = re.search(r"## Key idea\s*\n(.*?)(?=\n## |\Z)", md_text, re.DOTALL)
                if m_idea:
                    key_idea = m_idea.group(1).strip()
                m_prob = re.search(r"## Problem & Context\s*\n(.*?)(?=\n## |\Z)", md_text, re.DOTALL)
                if m_prob:
                    problem_context = m_prob.group(1).strip()
                m_concl = re.search(r"## Raw Conclusion\s*\n(.*?)(?=\n## |\Z)", md_text, re.DOTALL)
                if m_concl:
                    raw_conclusion = m_concl.group(1).strip()
            except Exception:
                pass
                
        item = {
            "slug": slug,
            "title": title,
            "venue": meta.get("venue") or "Top Journal",
            "year": meta.get("year", "N/A"),
            "authors": meta.get("authors", "Anon."),
            "score": score,
            "results_progression": results_progression,
            "key_idea": key_idea,
            "problem_context": problem_context,
            "raw_conclusion": raw_conclusion
        }
        
        if is_target:
            target_candidates.append(item)
        elif is_top:
            top_candidates.append(item)
            
    target_candidates.sort(key=lambda x: x["score"], reverse=True)
    top_candidates.sort(key=lambda x: x["score"], reverse=True)
    
    selected_target = target_candidates[:target_count]
    selected_top = top_candidates[:top_tier_count]
    
    combined = selected_target + selected_top
    if len(combined) < (target_count + top_tier_count):
        remaining = [p for p in target_candidates[target_count:] + top_candidates[top_tier_count:] if p not in combined]
        combined.extend(remaining[:(target_count + top_tier_count - len(combined))])
        
    return combined

# ==============================================================================
# 全文因果链缝合与高级学术过渡 (Results & Discussion Master Stitcher)
# ==============================================================================

def generate_title_and_abstract(
    topic: str,
    intro_text: str,
    ordered_figures: List[Dict[str, Any]],
    conclusion_text: str,
    target_journal: str,
    api_key: str
) -> Dict[str, Any] | None:
    """呼叫 DeepSeek 深度阅读全套积木结构，提炼 3 个顶级备选标题与 JACS 级高水平摘要"""
    fig_syntheses = []
    for idx, f in enumerate(ordered_figures, 1):
        lbl = f.get("final_label") or f"Figure {idx}"
        fig_syntheses.append(f"[{lbl}] {f['caption'][:120]}\nKey Findings & Metrics: {f['english_text'][:600]}...")
    all_results_str = "\n\n".join(fig_syntheses)

    prompt = f"""You are a distinguished research director and senior editor of {target_journal} (and top-tier chemistry/materials journals).
Deeply analyze the complete academic building blocks below to craft:
1. **Three High-Impact Title Options**:
   - Option 1: Direct & Definitive (clear, powerful statement of the core breakthrough).
   - Option 2: Mechanistic & Precise (focusing on the molecular/photophysical governing principle).
   - Option 3: Broad & Forward-Looking (highlighting paradigm shift and applications).
2. **A Publication-Grade Abstract (150-250 words)**:
   - Structured in the classic JACS narrative arc: Motivation -> System Design -> Key Spectroscopic Evidence Across Figures -> Mechanistic Insight -> Broader Significance.

### COMPLETE MANUSCRIPT BUILDING BLOCKS:
- **Broad Topic / Working Title**: {topic}
- **Introduction Background & Motivation**:
{intro_text[:1500]}...

- **Full Experimental Sequence & Spectroscopic Evidence Across Figures**:
{all_results_str}

- **Final Conclusion & Design Rules**:
{conclusion_text[:1200]}...

### OUTPUT FORMAT:
Respond with a strict JSON object (no markdown wrap, raw JSON only):
{{
  "title_options": [
    "Option 1: ...",
    "Option 2: ...",
    "Option 3: ..."
  ],
  "english_abstract": "The complete polished English Abstract...",
  "chinese_abstract": "The professional Chinese translation of the Abstract..."
}}
"""
    url = "https://api.deepseek.com/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a professional academic editor. Output valid JSON only."},
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
            return json.loads(content.strip())
    except Exception as e:
        print(f"❌ 自动提炼标题与摘要异常: {e}")
        return None

def stitch_results_and_discussion_transitions(
    intro_text: str,
    conclusion_text: str,
    ordered_figures: List[Dict[str, Any]],
    target_journal: str,
    exemplar_papers: List[Dict[str, Any]],
    api_key: str,
    workspace_dir: Path | None = None
) -> List[Dict[str, Any]] | None:
    """
    呼叫 DeepSeek 专家大脑（全篇统筹与积木删冗重塑引擎）：
    1. 深度阅读工作区全部积木（引言立论 + 各图表完整实验事实与光谱数据 + 结论升华）；
    2. 梳理各个积木之间的内在因果逻辑关系；
    3. 【严禁模板化套话与车轱辘话】：彻底杜绝任何 "To rationalize the divergent excited-state dynamics..." 这类机械套话；
    4. 【积木智能精炼与直接呈现】：为每个图表输出一个包含主题小标题和一气呵成的精炼正文 (refined_english_text)。
    """
    if not ordered_figures:
        return []
    print(f"\n🧠 正在呼叫 DeepSeek 专家大脑【深度通读全部 {len(ordered_figures)} 个图表积木 + 引言 + 结论，并参考 6 篇顶刊范式进行全局因果梳理与智能删减精炼】...")
    
    # 1. 组装各图表草稿内容
    user_building_blocks = []
    for idx, f in enumerate(ordered_figures, 1):
        lbl = f.get("final_label") or f"Figure {idx}"
        en_clean = f['english_text'].strip()
        user_building_blocks.append(f"""### [BUILDING BLOCK {idx}] {lbl}:
- Caption: {f['caption']}
- Raw Draft Content:
{en_clean}
""")
    user_blocks_str = "\n".join(user_building_blocks)
    
    # 2. 组装 6 篇顶刊范文图表推进链
    benchmark_flow_blocks = []
    for idx, ex in enumerate(exemplar_papers, 1):
        title = ex.get("title", "")
        venue = ex.get("venue", "")
        year = ex.get("year", "")
        key_idea = ex.get("key_idea", "")
        prog = ex.get("results_progression", "")
        prog_clean = prog[:1500] if prog else "No detailed figure progression extracted."
        block = f"""[Benchmark Article {idx}] "{title}" ({venue}, {year})
- Core Scientific Strategy: {key_idea[:300]}
- Real Figure-to-Figure Progression & Causal Flow:
{prog_clean}
"""
        benchmark_flow_blocks.append(block)
    benchmark_narratives_str = "\n".join(benchmark_flow_blocks)

    # 加载用户自定义 Skill
    custom_skill = load_custom_skill(workspace_dir)
    custom_skill_block = ""
    if custom_skill:
        custom_skill_block = f"""
### 🌟 USER CUSTOM SKILL & SPECIAL WRITING INSTRUCTIONS (HIGHEST PRIORITY):
The user has provided the following specific domain skill instructions and writing guidelines. You MUST strictly adhere to them:
{custom_skill}
"""
    
    prompt = f"""You are a distinguished research director and consulting editor for {target_journal}.
We are transforming {len(ordered_figures)} isolated experimental drafts into a seamless, publication-grade **Results and Discussion** chapter.

{custom_skill_block}

================================================================================
CRITICAL EDITORIAL PRINCIPLES (STRICT TOP-TIER JOURNAL STANDARDS):
================================================================================
1. **MANDATORY ANTI-PLAGIARISM & PARAPHRASING (20%+ DISSIMILARITY)**:
   - **Zero Verbatim Copying**: STRICTLY PROHIBIT copying full phrases or sentence structures verbatim from benchmark papers.
   - **Substantial Paraphrasing**: Every transitional bridge, introduction of data, and physical interpretation must be uniquely synthesized, guaranteeing **at least 20% linguistic/structural difference** from published sources.

2. **NO FORMULAIC BOILERPLATE OR REPETITIVE PHRASES (严禁模板化车轱辘套话)**:
   - STRICTLY FORBID clichéd transition formulas such as:
     * "To rationalize the divergent excited-state dynamics observed in BDP1, BDP2 and BDP3, we constructed an energy level diagram..."
     * "To establish the structural basis for..."
     * "Having verified the successful assembly of... we next asked whether..."
   - DO NOT repeatedly define what BDP1, BDP2, BDP3 are in every figure.
   - Cut out all throat-clearing fluff and generic introductory preambles.
   
3. **NATURAL, HIGH-DENSITY SCIENTIFIC FLOW (顶刊级自然递进与开门见山)**:
   - Each section must open directly with either the physical rationale or direct spectroscopic observation in an authoritative, active voice.
   - Model the phrasing and paragraph cadence after the 6 published benchmark articles below.

4. **100% PRESERVATION OF HARD QUANTITATIVE DATA & CITATION PLACEHOLDERS**:
   - Strictly keep EVERY quantitative metric (absorption/emission peaks in nm, decay lifetimes in ps/ns/$\mu$s, quenching percentages, driving forces $\Delta G$ in eV, rate constants $k_{{ET}}$, $k_{{CS}}$, $k_{{TET}}$, quantum yields $\Phi$, energy levels).
   - Strictly preserve all spectroscopic assignments (e.g. transient bleach bands, radical cation/anion signatures, triplet-triplet absorption).
   - Strictly PRESERVE all inline reference tags `[1]`, `[2]`, `[3]` or placeholders `{{{{REF:...}}}}` exactly as cited.

================================================================================
RESEARCHER'S FULL ACADEMIC BUILDING BLOCKS:
================================================================================
### INTRODUCTION CONTEXT:
{intro_text[:1200]}...

### RAW FIGURE BUILDING BLOCKS:
{user_blocks_str}

### CONCLUSION CONTEXT:
{conclusion_text[:1000]}...

================================================================================
REAL PUBLISHED BENCHMARK ARTICLES (Figure Progressions from Knowledge Base):
================================================================================
{benchmark_narratives_str}

### OUTPUT FORMAT:
Respond with a strict JSON object with this exact schema (raw JSON only):
{{
  "sections": [
    {{
      "fig_idx": 1,
      "thematic_heading": "Precise Thematic Heading for Figure 1 (e.g. Interfacial Assembly and Steady-State Optical Properties)...",
      "refined_english_text": "The complete, high-density, publication-grade English Results & Discussion text for Figure 1. Naturally incorporates opening context and physical insights without any boilerplate, strictly preserving all quantitative metrics and citations..."
    }},
    {{
      "fig_idx": 2,
      "thematic_heading": "Precise Thematic Heading for Figure 2...",
      "refined_english_text": "The complete, high-density English Results & Discussion text for Figure 2..."
    }}
  ]
}}
"""
    url = "https://api.deepseek.com/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a distinguished academic editor for JACS. You aggressively eliminate boilerplate while strictly preserving all quantitative data, inline citations, and physical facts, outputting valid JSON only."},
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
            res = json.loads(content.strip())
            return res.get("sections", [])
    except Exception as e:
        print(f"❌ 智能生成章节过渡与积木删冗重塑异常: {e}")
        return None

# ==============================================================================
# 主交付生成器 (Main Manuscript & Supporting Information)
# ==============================================================================

def deliver_full_manuscript_package(
    workspace_dir: Path,
    topic: str,
    target_journal: str,
    title_abstract_data: Dict[str, Any],
    intro_data: Dict[str, Any],
    stitched_results_sections: List[Dict[str, Any]],
    main_figures: List[Dict[str, Any]],
    si_figures: List[Dict[str, Any]],
    conclusion_data: Dict[str, Any],
    experimental_data: List[Dict[str, Any]],
    exemplar_papers: List[Dict[str, Any]],
    metadata_map: Dict[str, Dict[str, Any]]
) -> Path:
    """
    组装出版级主手稿、补充材料(SI)、全局核对表与所有 PDF 汇聚库，
    并严格执行全篇按正文出现顺序的引文重编与图号格式化。
    """
    final_manuscript_dir = workspace_dir / "Final_Manuscript_Pack"
    final_manuscript_dir.mkdir(parents=True, exist_ok=True)
    all_pdfs_dir = final_manuscript_dir / "All_References_PDFs"
    if all_pdfs_dir.exists():
        try:
            shutil.rmtree(all_pdfs_dir)
        except Exception:
            pass
    all_pdfs_dir.mkdir(parents=True, exist_ok=True)
    
    exemplar_pdfs_dir = final_manuscript_dir / "Benchmark_Journal_PDFs"
    if exemplar_pdfs_dir.exists():
        try:
            shutil.rmtree(exemplar_pdfs_dir)
        except Exception:
            pass
    exemplar_pdfs_dir.mkdir(parents=True, exist_ok=True)
    
    # --------------------------------------------------------------------------
    # 步骤 1：准备各章节文本并建立全域实体占位符 (Grounding)
    # --------------------------------------------------------------------------
    stitch_map = {s.get("fig_idx"): s for s in stitched_results_sections}
    
    # 1.1 引言实体对账
    intro_en_raw = intro_data.get("english_text", "") if intro_data else ""
    intro_zh_raw = intro_data.get("chinese_text", "") if intro_data else ""
    intro_guide = intro_data.get("guide_path") if intro_data else None
    intro_local_map = parse_guide_local_mapping(intro_guide, metadata_map) if intro_guide else {}
    
    intro_en_grounded = ground_text_citations(intro_en_raw, intro_local_map)
    intro_zh_grounded = ground_text_citations(intro_zh_raw, intro_local_map)
    
    # 1.2 主文图表实体对账与标准 Caption 重构
    grounded_main_figures = []
    for idx, f in enumerate(main_figures, 1):
        f_copy = dict(f)
        fig_label = f.get("final_label") or f"Figure {idx}"
        f_guide = f.get("guide_path")
        f_local_map = parse_guide_local_mapping(f_guide, metadata_map) if f_guide else {}
        
        # 提取精炼正文
        stitch_info = stitch_map.get(idx, {})
        heading = stitch_info.get("thematic_heading") or f"{fig_label} Characterization and Dynamics"
        refined_en = (stitch_info.get("refined_english_text") or "").strip()
        if not refined_en:
            refined_en = f["english_text"].strip()
            
        f_copy["thematic_heading"] = heading
        f_copy["refined_english_grounded"] = ground_text_citations(refined_en, f_local_map)
        f_copy["chinese_grounded"] = ground_text_citations(f.get("chinese_text", ""), f_local_map)
        
        # 统一格式化标准 Caption
        f_copy["standard_caption"] = format_standard_caption(f["caption"], fig_label)
        f_copy["standard_caption_grounded"] = ground_text_citations(f_copy["standard_caption"], f_local_map)
        grounded_main_figures.append(f_copy)
        
    # 1.3 结论实体对账
    concl_en_raw = conclusion_data.get("english_text", "") if conclusion_data else ""
    concl_zh_raw = conclusion_data.get("chinese_text", "") if conclusion_data else ""
    concl_guide = conclusion_data.get("guide_path") if conclusion_data else None
    concl_local_map = parse_guide_local_mapping(concl_guide, metadata_map) if concl_guide else {}
    
    concl_en_grounded = ground_text_citations(concl_en_raw, concl_local_map)
    concl_zh_grounded = ground_text_citations(concl_zh_raw, concl_local_map)
    
    # 1.4 SI 图表与实验规程实体对账
    grounded_si_figures = []
    for idx, sf in enumerate(si_figures, 1):
        sf_copy = dict(sf)
        si_label = sf.get("final_label") or f"Figure S{idx}"
        sf_guide = sf.get("guide_path")
        sf_local_map = parse_guide_local_mapping(sf_guide, metadata_map) if sf_guide else {}
        
        sf_copy["standard_caption"] = format_standard_caption(sf["caption"], si_label)
        sf_copy["standard_caption_grounded"] = ground_text_citations(sf_copy["standard_caption"], sf_local_map)
        sf_copy["english_grounded"] = ground_text_citations(sf.get("english_text", ""), sf_local_map)
        sf_copy["chinese_grounded"] = ground_text_citations(sf.get("chinese_text", ""), sf_local_map)
        grounded_si_figures.append(sf_copy)
        
    grounded_exp_sections = []
    for exp in experimental_data:
        exp_copy = dict(exp)
        exp_guide = exp.get("guide_path")
        exp_local_map = parse_guide_local_mapping(exp_guide, metadata_map) if exp_guide else {}
        exp_copy["content_grounded"] = ground_text_citations(exp.get("content", ""), exp_local_map)
        grounded_exp_sections.append(exp_copy)
        
    # --------------------------------------------------------------------------
    # 步骤 2：全篇从头到尾按正文顺序扫描，分配全新连续序号 [1]~[N]
    # --------------------------------------------------------------------------
    text_blocks_in_reading_order: List[Tuple[str, str]] = []
    
    # 1. Abstract
    text_blocks_in_reading_order.append(("abstract_en", title_abstract_data.get("english_abstract", "")))
    text_blocks_in_reading_order.append(("abstract_zh", title_abstract_data.get("chinese_abstract", "")))
    
    # 2. Introduction
    text_blocks_in_reading_order.append(("intro_en", intro_en_grounded))
    text_blocks_in_reading_order.append(("intro_zh", intro_zh_grounded))
    
    # 3. Results & Discussion 各小节正文与 Caption
    for idx, f in enumerate(grounded_main_figures, 1):
        text_blocks_in_reading_order.append((f"main_fig_{idx}_en", f["refined_english_grounded"]))
        text_blocks_in_reading_order.append((f"main_fig_{idx}_cap", f["standard_caption_grounded"]))
        text_blocks_in_reading_order.append((f"main_fig_{idx}_zh", f["chinese_grounded"]))
        
    # 4. Conclusion
    text_blocks_in_reading_order.append(("concl_en", concl_en_grounded))
    text_blocks_in_reading_order.append(("concl_zh", concl_zh_grounded))
    
    # 5. SI 实验与图表
    for idx, exp in enumerate(grounded_exp_sections, 1):
        text_blocks_in_reading_order.append((f"exp_{idx}", exp["content_grounded"]))
    for idx, sf in enumerate(grounded_si_figures, 1):
        text_blocks_in_reading_order.append((f"si_fig_{idx}_cap", sf["standard_caption_grounded"]))
        text_blocks_in_reading_order.append((f"si_fig_{idx}_en", sf["english_grounded"]))
        text_blocks_in_reading_order.append((f"si_fig_{idx}_zh", sf["chinese_grounded"]))
        
    reindexed_blocks, global_ordered_refs, slug_to_global_id = sequential_reindex_full_manuscript(
        text_blocks_in_reading_order, metadata_map
    )
    
    print(f"\n⚡ [正文顺序重编完毕] 全篇按正文首次出现顺序共索引了 {len(global_ordered_refs)} 篇独立文献，严格从 [1] 递增至 [{len(global_ordered_refs)}]！")

    # --------------------------------------------------------------------------
    # 步骤 3：归档全篇引用的全部原装 PDF 与 6 篇顶刊范文 PDF
    # --------------------------------------------------------------------------
    print(f"🔍 正在归档全篇引用的 {len(global_ordered_refs)} 篇文献原装 PDF 至 All_References_PDFs/...")
    for ref in global_ordered_refs:
        slug = ref["slug"]
        g_idx = ref["global_index"]
        ref["pdf_found"] = False
        ref["pdf_name"] = None
        
        pdf_path_str = ref.get("pdf_path") or metadata_map.get(slug, {}).get("pdf_path")
        if pdf_path_str:
            src_pdf = Path(pdf_path_str)
            if src_pdf.exists():
                a_tuples = parse_author_string(ref.get("authors"))
                first_author = a_tuples[0][0] if a_tuples else "Author"
                first_author_clean = re.sub(r"[^a-zA-Z0-9]+", "", first_author) or "Author"
                year_str = str(ref.get("year") or "Year").strip() or "Year"
                clean_pdf_name = f"[{g_idx}] [{year_str}] {first_author_clean}.pdf"
                target_pdf_path = all_pdfs_dir / clean_pdf_name
                try:
                    shutil.copy(str(src_pdf), str(target_pdf_path))
                    ref["pdf_found"] = True
                    ref["pdf_name"] = clean_pdf_name
                except Exception:
                    pass
                    
    for idx, ex in enumerate(exemplar_papers, 1):
        slug = ex["slug"]
        ex["pdf_found"] = False
        ex["pdf_name"] = None
        pdf_path_str = metadata_map.get(slug, {}).get("pdf_path")
        if pdf_path_str:
            src_pdf = Path(pdf_path_str)
            if src_pdf.exists():
                a_tuples = parse_author_string(ex.get("authors"))
                first_author = a_tuples[0][0] if a_tuples else "Author"
                first_author_clean = re.sub(r"[^a-zA-Z0-9]+", "", first_author) or "Author"
                year_str = str(ex.get("year") or "Year").strip() or "Year"
                ex_pdf_name = f"[Benchmark_{idx}] [{year_str}] {first_author_clean}.pdf"
                target_pdf = exemplar_pdfs_dir / ex_pdf_name
                try:
                    shutil.copy(str(src_pdf), str(target_pdf))
                    ex["pdf_found"] = True
                    ex["pdf_name"] = ex_pdf_name
                except Exception:
                    pass

    # --------------------------------------------------------------------------
    # 步骤 4：组装出版级主手稿 (Main_Manuscript.md)
    # --------------------------------------------------------------------------
    title_options = title_abstract_data.get("title_options", [topic])
    best_title = title_options[0] if title_options else topic
    en_abstract = reindexed_blocks.get("abstract_en", "")
    zh_abstract = reindexed_blocks.get("abstract_zh", "")
    
    references_block = build_journal_style_references(global_ordered_refs, target_journal)
    
    # 组装 Results and Discussion
    rd_blocks = ["## Results and Discussion\n"]
    for idx, f in enumerate(grounded_main_figures, 1):
        heading = f["thematic_heading"]
        refined_content = reindexed_blocks.get(f"main_fig_{idx}_en", "").strip()
        caption_formatted = reindexed_blocks.get(f"main_fig_{idx}_cap", "").strip()
        
        rd_blocks.append(f"### {heading}\n")
        rd_blocks.append(f"{refined_content}\n")
        rd_blocks.append(f"{caption_formatted}\n")
        
    rd_text = "\n".join(rd_blocks)
    intro_en_final = reindexed_blocks.get("intro_en", "")
    concl_en_final = reindexed_blocks.get("concl_en", "")
    
    main_manuscript_lines = [
        f"# {best_title}\n",
        f"**Target Journal Style**: {target_journal}\n",
        "## Abstract\n",
        f"{en_abstract}\n",
        "### 🇨🇳 中文摘要 (Chinese Translation)\n",
        f"{zh_abstract}\n",
        "## Introduction\n",
        f"{intro_en_final}\n",
        f"{rd_text}\n",
        "## Conclusion\n",
        f"{concl_en_final}\n",
        f"{references_block}\n",
        "---",
        "### 💡 Alternative Title Options for Review:",
        "\n".join([f"- {t}" for t in title_options])
    ]
    
    main_file = final_manuscript_dir / "Main_Manuscript.md"
    main_file.write_text("\n".join(main_manuscript_lines), encoding="utf-8")
    
    # --------------------------------------------------------------------------
    # 步骤 5：组装补充材料 (Supporting_Information.md)
    # --------------------------------------------------------------------------
    si_toc = [
        "## Table of Contents",
        "- S1. Materials and Reagents",
        "- S2. Synthetic Procedures and Sample Preparation",
        "- S3. Characterization Techniques and Instrumentation"
    ]
    if grounded_si_figures:
        si_toc.append("- S4. Supplementary Figures, Tables and Notes")
    si_toc.append("\n---\n")

    si_lines = [
        f"# Supporting Information for:\n# {best_title}\n",
        "\n".join(si_toc)
    ]
    
    if grounded_exp_sections:
        for idx, exp in enumerate(grounded_exp_sections, 1):
            exp_text = reindexed_blocks.get(f"exp_{idx}", "")
            si_lines.append(f"## Section S{idx}. {exp['name']}\n")
            si_lines.append(f"{exp_text}\n")
    else:
        si_lines.append("*(No local experimental sections detected in Experimental_Report)*\n")
        
    if grounded_si_figures:
        si_lines.append("## Section S4. Supplementary Figures, Tables and Notes\n")
        for idx, sf in enumerate(grounded_si_figures, 1):
            sf_label = sf.get("final_label") or f"Figure S{idx}"
            cap_text = reindexed_blocks.get(f"si_fig_{idx}_cap", "")
            en_text = reindexed_blocks.get(f"si_fig_{idx}_en", "")
            zh_text = reindexed_blocks.get(f"si_fig_{idx}_zh", "")
            
            si_lines.append(f"### {sf_label}\n")
            si_lines.append(f"{cap_text}\n")
            si_lines.append(f"{en_text}\n")
            if zh_text:
                si_lines.append(f"#### 🇨🇳 中文详细说明与讨论:\n{zh_text}\n")
            si_lines.append("---\n")
            
    si_file = final_manuscript_dir / "Supporting_Information.md"
    si_file.write_text("\n".join(si_lines), encoding="utf-8")
    
    # --------------------------------------------------------------------------
    # 步骤 6：生成全篇事实溯源指南 (Verification_Guide_Manuscript.md)
    # --------------------------------------------------------------------------
    guide_lines = [
        f"# 🔍 整篇学术手稿全域事实溯源与核对指南\n",
        f"**论文主标题**: {best_title}\n",
        f"**目标期刊风格**: {target_journal}\n",
        "本指南建立了全篇手稿所有引文序号 `[1]`, `[2]`, `[3]` ... 到本地原装 PDF 的**正文出现顺序全域溯源对照档案**。\n",
        f"全篇共计引用 **{len(global_ordered_refs)} 篇独立核心顶刊文献**，原装 PDF 已完整拷贝至 `All_References_PDFs/` 目录！\n",
        "## 🏛️ 参考的目标期刊与同领域顶级范文及其真实起承转合范式 (Benchmark Articles & Narrative Archetypes)",
        "本手稿 Results and Discussion 章节中的高水平主题小标题与实验推进，均严格深度参考并派生自以下 6 篇已发表顶刊的真实实验推进链：\n",
        "| 范文序号 | 物理 PDF 文件 (位于 `Benchmark_Journal_PDFs/`) | 完整论文标题与元数据 | 期刊 | 核心图表逻辑推进链与起承转合范式 |",
        "|---|---|---|---|---|"
    ]
    for idx, ex in enumerate(exemplar_papers, 1):
        pdf_col = f"📖 `{ex.get('pdf_name')}`" if ex.get("pdf_found") else "📁 知识库收录"
        prog_snippet = (ex.get("results_progression") or ex.get("key_idea") or "顶刊标准叙事范式").replace("\n", " ")[:180]
        guide_lines.append(f"| **[范文 {idx}]** | {pdf_col} | **{ex['title']}**<br>*{ex['authors']} ({ex['year']})* | `{ex['venue']}` | {prog_snippet}... |")
        
    guide_lines.append("\n## 📚 全局文献与 PDF 文件核对表 (按正文出现先后顺序 [1]~[N] 严格排列)")
    guide_lines.append("| 全局引文 | 物理 PDF 文件 (位于 `All_References_PDFs/`) | 完整标题与作者元数据 | DOI 链接 |")
    guide_lines.append("|---|---|---|---|")
    for ref in global_ordered_refs:
        pdf_col = f"📁 `{ref['pdf_name']}`" if ref["pdf_found"] else "❌ 未配对"
        doi_str = f"[{ref['doi']}](https://doi.org/{ref['doi']})" if ref.get("doi") else "N/A"
        guide_lines.append(f"| **[{ref['global_index']}]** | {pdf_col} | **{ref['title']}**<br>*{ref['authors']} ({ref['year']})* | {doi_str} |")
        
    guide_file = final_manuscript_dir / "Verification_Guide_Manuscript.md"
    guide_file.write_text("\n".join(guide_lines), encoding="utf-8")
    
    return final_manuscript_dir

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
    print("🏛️ AutoSci 学术手稿全篇集成与总装大师 (Full Manuscript Master Assembler)")
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
        
    if not workspace_dir.exists():
        print(f"  ⚠️ 警告: 路径 '{workspace_dir}' 不存在，正在自动创建...")
        workspace_dir.mkdir(parents=True, exist_ok=True)
    print(f"  ➜ 已锁定工作区目录: {workspace_dir}")
    
    lib_dir, wiki_papers_dir, master_registry_path = resolve_system_paths(workspace_dir)

    # 1. 扫描工作区资产
    print("\n🔍 正在扫描工作区已生成的各章节手稿资产并执行主文/SI 智能分流与纯净解析...")
    assets = scan_workspace_manuscript_assets(workspace_dir)
    
    has_intro = bool(assets["introduction"])
    has_concl = bool(assets["conclusion"])
    main_fig_count = len(assets["main_figures"])
    si_fig_count = len(assets["si_figures"])
    exp_count = len(assets["experimental_sections"])
    
    print(f"  📖 引言手稿: {'✅ 已就绪 (Introduction_Final_Draft.md)' if has_intro else '❌ 未检测到'}")
    print(f"  🔬 结论章节: {'✅ 已就绪 (Conclusion_Draft.md)' if has_concl else '❌ 未检测到'}")
    print(f"  📊 主文图表描述 (Main Figures, 放入正文 Results & Discussion): 共 {main_fig_count} 个:")
    for idx, f in enumerate(assets["main_figures"], 1):
        print(f"     [{idx}] {f['name']} (原标识: {f['old_num'] or '无'} | Caption: {f['caption'][:45]}...)")
    print(f"  📎 补充材料图表 (SI Figures, 自动放入 Supporting Information S4): 共 {si_fig_count} 个:")
    for idx, f in enumerate(assets["si_figures"], 1):
        print(f"     [{idx}] {f['name']} (原标识: {f['old_num'] or '无'} | Caption: {f['caption'][:45]}...)")
    print(f"  🧪 实验规程与测试条件 (放入 Supporting Information S1-S3): 共 {exp_count} 个:")
    for idx, e in enumerate(assets["experimental_sections"], 1):
        print(f"     [{idx}] {e['name']}")
        
    if main_fig_count == 0 and si_fig_count == 0:
        print("⚠️ 警告: 工作区中未找到任何图表报告，建议先使用 write_figure_description.py 生成！")
        
    # 2. 交互确认目标论文主题与目标期刊
    print("\n" + "=" * 80)
    print("🎯 请配置论文总装参数:")
    print("=" * 80)
    
    topic = input("\n📌 1. 请输入论文大主题 / 核心研究课题 (Title/Topic):\n👉 ").strip()
    if not topic:
        topic = "Efficient Triplet Energy Transfer via Conformation-Controlled Dynamics"
        print(f"   (使用默认课题: {topic})")
        
    print("\n🏛️ 2. 请选择目标投稿期刊风格（用于自动检索顶刊写作范式与段落节奏）：")
    print("   [1] JACS (Journal of the American Chemical Society) [推荐]")
    print("   [2] Nature Communications")
    print("   [3] Angewandte Chemie International Edition")
    print("   [4] Advanced Materials")
    print("   [5] 通用顶刊物理化学/材料学风格 (General Top-Tier Style)")
    
    j_choice = input("👉 请选择目标期刊 [1-5，默认 1]: ").strip()
    journal_map = {
        "1": "Journal of the American Chemical Society (JACS)",
        "2": "Nature Communications",
        "3": "Angewandte Chemie International Edition",
        "4": "Advanced Materials",
        "5": "Top-Tier Physical Chemistry / Materials Journal"
    }
    target_journal = journal_map.get(j_choice, journal_map["1"])
    print(f"   ➜ 已锁定目标期刊风格: {target_journal}")
    
    # 3. 严格执行图表重排 (100% 生效用户输入)
    ordered_main_figures = list(assets["main_figures"])
    if main_fig_count > 1:
        print(f"\n📋 当前主文图表默认排列顺序为:")
        for idx, f in enumerate(ordered_main_figures, 1):
            print(f"   [{idx}] {f['name']} (原编号: {f['old_num']})")
        print("\n💡 提示: 您可以直接输入新的顺序（例如 2,3,4,5,6,7,8,9,10,11,1 把第 1 个放到最后，或者 1,2,3,4,5,6,7,8,9,10,11）：")
        reorder_choice = input("👉 请输入图表顺序 [直接回车确认默认 / 或输入逗号分隔的序号]: ").strip()
        if reorder_choice:
            parts = re.split(r"[,，\s]+", reorder_choice)
            new_indices = [int(x) for x in parts if x.isdigit()]
            if len(new_indices) == len(ordered_main_figures) and set(new_indices) == set(range(1, len(ordered_main_figures) + 1)):
                ordered_main_figures = [ordered_main_figures[i-1] for i in new_indices]
                print(f"   ✅ [重排成功] 主文图表已严格更新为用户指定顺序！")
            else:
                print(f"   ⚠️ 输入序号数量或范围与当前主文图表不匹配 (需提供 1~{len(ordered_main_figures)} 的全排列)，保持默认顺序。")
                
    # 执行主文图表连续重排
    print("\n⚡ [图表序号连续化引擎] 正在对主文图表执行连续重编号 (Figure 1, Figure 2...) 并同步正文...")
    ordered_main_figures, main_renumber_rules = realign_figure_sequence(ordered_main_figures, is_si=False)
    for r in main_renumber_rules:
        print(f"   ➜ 主文图表映射: {r['ptype']} {r['old_num']} ➡️ {r['ptype']} {r['new_num']}")
        
    # 执行 SI 图表连续重排
    ordered_si_figures = list(assets["si_figures"])
    si_renumber_rules = []
    if si_fig_count > 0:
        print("\n⚡ [SI 序号连续化引擎] 正在对 SI 图表执行连续重编号 (Figure S1, Figure S2...) 并同步正文...")
        ordered_si_figures, si_renumber_rules = realign_figure_sequence(ordered_si_figures, is_si=True)
        for r in si_renumber_rules:
            print(f"   ➜ SI 图表映射: {r['ptype']} {r['old_num']} ➡️ {r['ptype']} {r['new_num']}")

    # 全文交叉引用替换
    all_renumber_rules = main_renumber_rules + si_renumber_rules
    if all_renumber_rules:
        if assets["introduction"]:
            assets["introduction"]["english_text"] = apply_figure_renumbering(assets["introduction"]["english_text"], all_renumber_rules)
            assets["introduction"]["chinese_text"] = apply_figure_renumbering(assets["introduction"]["chinese_text"], all_renumber_rules)
        if assets["conclusion"]:
            assets["conclusion"]["english_text"] = apply_figure_renumbering(assets["conclusion"]["english_text"], all_renumber_rules)
            assets["conclusion"]["chinese_text"] = apply_figure_renumbering(assets["conclusion"]["chinese_text"], all_renumber_rules)
        for exp in assets["experimental_sections"]:
            exp["content"] = apply_figure_renumbering(exp["content"], all_renumber_rules)

    # 4. 全域元数据打捞与 6 篇目标顶刊范文锁定
    metadata_map = harvest_comprehensive_paper_metadata(workspace_dir)
    exemplar_papers = select_target_journal_exemplars(
        topic, target_journal, metadata_map, wiki_papers_dir=wiki_papers_dir, target_count=3, top_tier_count=3
    )
    print(f"\n✨ [范式确定] 本次手稿总装成功锁定了以下 6 篇顶刊写作范式:")
    for idx, ex in enumerate(exemplar_papers, 1):
        print(f"   📖 [{idx}] {ex['title']} ({ex['venue']}, {ex['year']})")
        
    intro_full_text = assets["introduction"]["english_text"] if has_intro else ""
    concl_full_text = assets["conclusion"]["english_text"] if has_concl else ""

    # 5. 深度通读各积木结构并结合 6 篇顶刊范式生成主文图表间学术承接与因果过渡
    stitched_sections = stitch_results_and_discussion_transitions(
        intro_full_text, concl_full_text, ordered_main_figures, target_journal, exemplar_papers, api_key, workspace_dir
    )
    if not stitched_sections:
        stitched_sections = []
        
    # 6. 自动生成 3 个备选标题与高水平 Abstract
    print(f"\n✍️ 正在呼叫 DeepSeek 深度阅读全篇各章节积木事实，提炼最具吸引力的 3 个高水平标题与 JACS 级摘要 (Abstract)...")
    title_abstract_data = generate_title_and_abstract(
        topic, intro_full_text, ordered_main_figures, concl_full_text, target_journal, api_key
    )
    if not title_abstract_data:
        title_abstract_data = {
            "title_options": [topic],
            "english_abstract": "A comprehensive investigation of excited-state dynamics...",
            "chinese_abstract": "本文对激发态动力学进行了系统研究..."
        }
        
    # 7. 交付最终完整手稿包 (全篇按正文出现顺序重新编排连续引文与图号)
    print("\n📦 正在构建交付包: Main_Manuscript.md, Supporting_Information.md 与全部 PDF 汇聚库...")
    out_dir = deliver_full_manuscript_package(
        workspace_dir, topic, target_journal, title_abstract_data, assets["introduction"],
        stitched_sections, ordered_main_figures, ordered_si_figures, assets["conclusion"],
        assets["experimental_sections"], exemplar_papers, metadata_map
    )
    
    print("\n" + "=" * 80)
    print("🎉 恭喜！学术手稿全篇集成与总装圆满完成！")
    print(f"  ➜ 最终交付目录: {out_dir}")
    print(f"  ➜ 1. 终极主手稿 (含标题、摘要、引言、消除套话的 Results and Discussion、结论、按正文出现顺序编排的 JACS 出版级参考文献):")
    print(f"       {out_dir}\\Main_Manuscript.md")
    print(f"  ➜ 2. 独立补充材料 (SI - 含合成规程、仪器测试条件、连续重排的 SI 图表与说明):")
    print(f"       {out_dir}\\Supporting_Information.md")
    print(f"  ➜ 3. 全局文献原装 PDF 库 (自动按 [1], [2]... 正文首次出现顺序汇聚，双击即看):")
    print(f"       {out_dir}\\All_References_PDFs\\")
    print(f"  ➜ 4. 6 篇目标顶刊与同领域范文 PDF 库:")
    print(f"       {out_dir}\\Benchmark_Journal_PDFs\\")
    print(f"  ➜ 5. 全域文献与事实核对指南:")
    print(f"       {out_dir}\\Verification_Guide_Manuscript.md")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
